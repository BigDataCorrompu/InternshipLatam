from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from typing import TypedDict
from langchain_tavily import TavilySearch
import streamlit as st

class WebSearchState(TypedDict):
    queries: list[str]
    what_to_find: str
    web_result: str
    summary: str


def generate_summary(state: WebSearchState, llm, session_id: str = "default") -> dict:
    web_result = state.get('web_result', '')
    what_to_find = state.get('what_to_find', '')

    if not web_result or not web_result[0]:
        return {"summary": "No web results found."}

    prompt = f"""Based on the search results below, answer: {what_to_find}
                {web_result}
                Give a concise, factual summary."""

    llm_with_cache = llm.bind(prompt_cache_key=f"dashboard-{session_id}")
    response = llm_with_cache.invoke(prompt)
    return {"summary": response.content}


def search_web(state: WebSearchState) -> dict:
    tavily_search = TavilySearch(max_results=3, tavily_api_key=st.secrets["tavily"]["api_key"])
    queries = state.get('queries', [])

    sections = []
    for query in queries:
        data = tavily_search.invoke({"query": query})
        results = data.get("results", [])

        docs_text = "\n\n".join(
            f'<Document href="{doc.get("url", "unknown")}">\n{doc.get("content", "")}\n</Document>'
            for doc in results
        ) or "No results found."

        sections.append(f'<Query text="{query}">\n{docs_text}\n</Query>')

    formatted = "\n\n---\n\n".join(sections)
    return {"web_result": formatted}