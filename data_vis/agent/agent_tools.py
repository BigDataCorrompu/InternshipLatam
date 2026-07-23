import sys, os
sys.path.append(os.path.join(os.path.dirname(__file__), "../../ingestion/python/src"))

from LLMprovider import LLM
from filters_agent import FilterCriteria, criteria_to_filter_dict, extract_filters, summarize_criteria
from websearch_agent import WebSearchState, generate_summary, search_web
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from typing import Literal

from pydantic import BaseModel, Field
from typing import Literal
from langchain_core.tools import tool
import streamlit as st
import pandas as pd
import json

def _reconcile_city_country(f: dict, city_country_map: dict) -> dict:
    """If both country and city filters are active, drop any city that doesn't
    belong to one of the selected countries — prevents impossible combinations
    like city=Buenos Aires + country=Chile silently returning zero offers."""
    if f.get("countries") and f.get("cities"):
        f["cities"] = [c for c in f["cities"] if city_country_map.get(c) in f["countries"]]
    return f


class DataQueryArgs(BaseModel):
    query_type: Literal["top_offers", "top_companies", "offer_detail"] = Field(
        description="""
        'top_offers': rank individual offers (e.g. top 5 best-scored offers).
        'top_companies': rank companies by offer count or average score.
        'offer_detail': get full details (keywords, explanation, score) for ONE specific offer,
        identified by job_title and/or company_name.
        """
    )
    sort_by: Literal["score", "date", "count"] = Field(
        default="score",
        description="What to rank by. 'count' only applies to top_companies (number of offers posted).",
    )
    ascending: bool = Field(default=False, description="True for lowest-first (e.g. worst scores).")
    limit: int = Field(default=5, description="How many results to return (ignored for offer_detail).")
    job_title: str | None = Field(default=None, description="Used only for offer_detail: partial job title to search.")
    company_name: str | None = Field(default=None, description="Used only for offer_detail or to filter top_offers/top_companies.")


def build_agent_tools(df, dict_reversed_index, city_country_map, get_current_filters, on_filter_applied, apply_filters_fn, summarize_dataframe_fn, llm, session_id: str = "default"):
    @st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: lambda _: None})
    def _cached_apply_filters(description: str, current_filters_key: str) -> tuple[str, dict]:
        current_filter = json.loads(current_filters_key)
        criteria = extract_filters(description, llm.fast, session_id)
        f = criteria_to_filter_dict(criteria, current_filter)
        f = _reconcile_city_country(f, city_country_map) 
        filtered = apply_filters_fn(df, f, dict_reversed_index, city_country_map)
        if filtered.empty:
            return "No offer match these criteria", f
        return f"{summarize_criteria(criteria)}\n\n{summarize_dataframe_fn(filtered)}", f

    @tool
    def apply_filters_tool(description: str) -> str:
        """Extract the filter-related part of the user's message and pass it here
        VERBATIM — do not rephrase, translate, or reformat it yourself, this tool
        parses it internally using the filter schema already in your context.
        This includes time expressions like "this week", "today", "last 3 days" —
        these ARE filters (date range), always route them here, never answer
        that no such filter exists.
        Returns a summary of the resulting offer pool (count, average score, top
        countries/cities/companies) after the filters are applied."""
        result_text, new_filters = _cached_apply_filters(description, json.dumps(get_current_filters(), sort_keys=True, default=str))
        filtered = apply_filters_fn(df, new_filters, dict_reversed_index, city_country_map)
        on_filter_applied(filtered, new_filters)
        return result_text

    @st.cache_data(show_spinner=False)
    def _cached_search_web(queries: tuple, what_to_find: str) -> str:
        state: WebSearchState = {"queries": list(queries), "what_to_find": what_to_find, "web_result": "", "summary": ""}
        state.update(search_web(state))
        state.update(generate_summary(state, llm.smart, session_id))
        return state["summary"]

    @tool
    def search_web_tool(queries: list[str], what_to_find: str) -> str:
        """Search the web for information NOT available in the local dataset (e.g. average
        salaries for a role/location, company reputation, industry trends, recent news).
        You formulate the search queries yourself: `queries` is a list of concise web search
        strings (like you'd type into a search engine), and `what_to_find` tells this tool
        what question to answer from the results, so it can return a focused, factual summary
        instead of raw search results."""
        return _cached_search_web(tuple(queries), what_to_find)

    @st.cache_data(show_spinner=False, hash_funcs={pd.DataFrame: lambda _: None})
    def _cached_query_data(query_type, sort_by, ascending, limit, job_title, company_name, current_filters_key: str) -> str:
        current_filter = json.loads(current_filters_key)
        current = apply_filters_fn(df, current_filter, dict_reversed_index, city_country_map)
        if company_name:
            current = current[current["company_name"].str.contains(company_name, case=False, na=False)]
        if current.empty:
            return "No offers match the current filters."

        if query_type == "offer_detail":
            subset = current
            if job_title:
                subset = subset[subset["job_title"].str.contains(job_title, case=False, na=False)]
            if subset.empty:
                return f"No offer found matching title='{job_title}', company='{company_name}'."
            row = subset.iloc[0]
            keywords = row.get("all_keywords", [])
            keywords_str = ", ".join(sorted(set(k for k in keywords if isinstance(k, str)))) if isinstance(keywords, list) else "None"
            return (f"Offer: {row.get('job_title')} @ {row.get('company_name')}\n"
                    f"Score: {row.get('score_relevancy')} — Explanation: {row.get('explanation', 'N/A')}\n"
                    f"Keywords: {keywords_str}")

        if query_type == "top_offers":
            sort_col = {"score": "score_relevancy", "date": "collected_at"}.get(sort_by, "score_relevancy")
            ranked = current.sort_values(sort_col, ascending=ascending).head(limit)
            lines = [f"- {r['job_title']} @ {r['company_name']} (score: {r['score_relevancy']})" for _, r in ranked.iterrows()]
            return f"Top {limit} offers by {sort_by}:\n" + "\n".join(lines)

        if query_type == "top_companies":
            if sort_by == "count":
                ranked = current["company_name"].value_counts().head(limit)
                lines = [f"- {name}: {count} offers" for name, count in ranked.items()]
            else:
                ranked = current.groupby("company_name")["score_relevancy"].mean().sort_values(ascending=ascending).head(limit)
                lines = [f"- {name}: avg score {score:.1f}" for name, score in ranked.items()]
            return f"Top {limit} companies by {sort_by}:\n" + "\n".join(lines)

        return f"Unknown query_type: {query_type}"

    @tool(args_schema=DataQueryArgs)
    def query_data_tool(query_type: str, sort_by: str = "score", ascending: bool = False,
                          limit: int = 5, job_title: str | None = None, company_name: str | None = None) -> str:
        """Read specific data points from the offers currently shown on the dashboard:
        top individual offers, top companies, or the full detail (keywords, explanation,
        score) of one specific offer. Only use this when the user asks a SPECIFIC question
        about the current results (e.g. "what are the top 5 offers", "which company posts
        the most", "why does this offer have that score") — if the user is just filtering
        or asking a general question, this tool is not needed.
        Always operates on the CURRENT filter state — call apply_filters_tool first if the
        user is also asking to change the filters."""
        return _cached_query_data(query_type, sort_by, ascending, limit, job_title, company_name,
                                    json.dumps(get_current_filters(), sort_keys=True, default=str))

    return [apply_filters_tool, search_web_tool, query_data_tool]

