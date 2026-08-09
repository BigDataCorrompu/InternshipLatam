# STATE AND NODES — email finding cascade (find_mails DAG)
import os
import re
import sys
import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END
from ddgs import DDGS

sys.path.append("../ingestion/python/src")
from APIendpoint import HunterAPI, QuotaExceededError
from silver_enrichment import Extract, call_with_retry


# ___ Search queries schema __________________________________________
class SearchQueryOutput(BaseModel):
    search_queries_mails: list[str] = Field(
        description=(
            "List of up to 3 short, focused search queries to find contact emails at this company. "
            "Target different departments: HR/recruitment, IT/Data Engineering team, and general manager/direction. "
            "Each query must be a single line, max 8 words."
        )
    )


# ___ Email schema __________________________________________
class EmailItem(BaseModel):
    email: str
    score: float
    reason: str
    source: str = ""  # Filled in by each node after extraction, not by the LLM


class EmailResults(BaseModel):
    emails: list[EmailItem] = Field(
        description=(
            "List of relevant contact emails found. Return an empty list [] for the emails field "
            "if none are found, do not return an empty array as the entire response."
        )
    )


# ___ Company state __________________________________________
class CompanyState(TypedDict):
    id_company: int
    company_name: str
    website: str

    id_location: int
    city: str
    country: str

    highest_grade: float
    average_grades: float
    contacts: Annotated[list[dict], operator.add]  # Accumulated email candidates (email/score/reason/source)


# Shared system prompt for structured email extraction from raw text.
_EXTRACTION_SYSTEM_PROMPT = SystemMessage(content="""
    You are an assistant that extracts company contact emails.
    I am looking to apply for a job/internship at this company.
    From the search results provided, identify the most relevant emails.
    1. Technical/data/IT team emails involved in HIRING or team contact (score 0.8-1.0)
    2. HR/recruitment emails (score 0.8-1.0)
    3. CEO/executive (score 0.6-0.8)
    4. Generic emails info@/contact@ (score 0.3-0.5)
    EXCLUDE emails for internal support, helpdesk, access management, IT ticketing,
    customer service, or any address whose purpose is NOT hiring/recruitment/team contact —
    even if it contains words like "IT" or "technical" in its name.
    ONLY use emails present in the provided search results.
    NEVER generate an email from your general knowledge.
    You MUST respond ONLY using the structured format provided.
    Never write conversational text. Always use the function call format.
    If no email is found, do not write any explanatory text.
    """)

class MailScrapping:
    """Node 1: LLM generates search queries -> DDG search -> LLM extracts emails."""

    def __init__(self, llm):
        self._generate_query = Extract(
            llm=llm.smart,
            task=(
                "Generate UP TO 3 short search queries to find contact emails at this company, "
                "each targeting a DIFFERENT department:\n"
                "1. IT / Data Engineering team contact (e.g. 'equipo data', 'IT department', 'data engineer team') "
                "-- NOT internal support/helpdesk/access management\n"
                "2. HR / recruitment contact (e.g. 'RRHH', 'recursos humanos', 'talent acquisition')\n"
                "3. General manager / direction contact (e.g. 'gerente general', 'direccion')\n"
                "If you know the company website, use 'site:domain.com' plus ONE relevant keyword per query. "
                "Otherwise, use the company name plus a department keyword. "
                "Each query must be a SINGLE LINE, max 8 words, no line breaks. "
                "Use the location to determine the query language, for example Spanish for Latin America. "
                "Return fewer than 3 queries only if a department is clearly irrelevant for this company."
            ),
            output_key="search_queries_mails",
            schema=SearchQueryOutput,
            fields=["company_name", "website", "city", "country"],
        )
        self._llm_structured = llm.mailfinder.with_structured_output(EmailResults)

    def __call__(self, state: CompanyState) -> dict:
        company = state.get("company_name")

        if not company or company == "null":
            print("⚠️  find_mails: no company_name, search aborted")
            return {"contacts": []}

        # 1. Ask the LLM to produce up to 3 targeted search queries.
        query_result = self._generate_query(state)
        search_queries_mails = query_result["search_queries_mails"]
        print(f"🔍 find_mails: {company} — queries={search_queries_mails}")

        # 2. Clean queries; fall back to a basic query if the LLM produced nothing usable.
        cleaned_queries = []
        for q in (search_queries_mails or []):
            q = q.replace("\n", " ").strip()
            if q and q.lower() != "null":
                cleaned_queries.append(q)

        if not cleaned_queries:
            country = state.get("country", "")
            cleaned_queries = [f"{company} RRHH contacto email {country}".strip()]
            print(f"⚠️  find_mails: no valid LLM query for {company}, basic fallback → '{cleaned_queries[0]}'")

        # 3. Run every query and concatenate results into a single block
        #    (economical: one single LLM extraction call for all queries).
        combined_results = []
        for q in cleaned_queries:
            result = self._search_ddg(q)
            if result:
                combined_results.append(f"[Query: {q}]\n{result}")
            else:
                print(f"⚠️  find_mails: no DDG result for {company} — query='{q}'")

        if not combined_results:
            print(f"⚠️  find_mails: no DDG result on any query for {company}")
            return {"contacts": []}

        results_text = "\n\n".join(combined_results)
        print(f"📄 find_mails: {len(results_text)} chars received for {company} — {len(cleaned_queries)} query(ies)")

        # 4. Extract structured emails from the concatenated text, tag the source.
        user = HumanMessage(content=f"Company: {company}\nResults:\n{results_text}")
        try:
            response = call_with_retry(lambda: self._llm_structured.invoke([_EXTRACTION_SYSTEM_PROMPT, user]))
            contacts = [{**item.model_dump(), "source": "ddg_llm"} for item in response.emails]
            if not contacts:
                print(f"⚠️  find_mails: LLM found no email for {company}")
            else:
                print(f"✅ find_mails: {len(contacts)} contact(s) for {company}")
            return {"contacts": contacts}
        except Exception as e:
            # The LLM sometimes returns "[]" in the wrong format instead of a valid empty result.
            if "'[]'" in str(e) or "failed_generation': '[]'" in str(e):
                print(f"⚠️  find_mails: empty response intercepted for {company}")
                return {"contacts": []}
            print(f"❌ find_mails: error for {company}: {e}")
            return {"contacts": []}

    def _search_ddg(self, query: str, max_results: int = 10) -> str:
        try:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=max_results)
                if not results:
                    return ""
                return "\n".join([r["body"] for r in results])
        except Exception as e:
            print(f"DDG error: {e}")
            return ""


def _extract_text(content) -> str:
    """
    response.content can be a str or a list of content blocks (text/tool_use)
    depending on whether the model used tools internally (e.g. google_search
    grounding). Normalize it into a plain string for downstream processing.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts)
    return str(content)


class MailGrounder:
    """Node 2: Gemini with native Google Search grounding -> LLM extracts emails."""

    def __init__(self, llm):
        self._grounded_llm = llm.grounder  # Fixed: removed trailing comma (was a 1-tuple)
        self._llm_structured = llm.mailfinder.with_structured_output(EmailResults)

    def __call__(self, state: CompanyState) -> dict:
        company = state.get("company_name")

        if not company or company == "null":
            print("⚠️  find_mails (grounder): no company_name, search aborted")
            return {"contacts": []}

        website = state.get("website", "")
        country = state.get("country", "")
        city = state.get("city", "")

        prompt = (
            f"Find contact emails for {company}"
            f"{f' (website: {website})' if website else ''}, located in {city}, {country}. "
            "I am looking to apply for a job/internship. "
            "Search for HR/recruitment contacts, IT/Data Engineering team contacts involved in hiring, "
            "general manager/direction contacts, or generic contact emails. "
            "EXCLUDE internal support, helpdesk, IT ticketing, access management, or customer service "
            "addresses — these are NOT useful for a job application, even if they mention 'IT' or 'technical'. "
            "Report every relevant email address you find, along with where you found it."
        )

        # 1. Grounded search: Gemini searches the web and returns free text.
        try:
            response = call_with_retry(lambda: self._grounded_llm.invoke(prompt))
            grounded_text = _extract_text(response.content)
            print(f"🌐 find_mails (grounder): {len(grounded_text)} grounded chars for {company}")
        except Exception as e:
            print(f"❌ find_mails (grounder): grounding error for {company}: {e}")
            return {"contacts": []}

        if not grounded_text or not grounded_text.strip():
            print(f"⚠️  find_mails (grounder): empty grounded response for {company}")
            return {"contacts": []}

        # 2. Extract structured emails from the grounded text, tag the source.
        user = HumanMessage(content=f"Company: {company}\nResults:\n{grounded_text}")
        try:
            structured_response = call_with_retry(
                lambda: self._llm_structured.invoke([_EXTRACTION_SYSTEM_PROMPT, user])
            )
            contacts = [{**item.model_dump(), "source": "gemini_grounding"} for item in structured_response.emails]
            if not contacts:
                print(f"⚠️  find_mails (grounder): no email extracted for {company}")
            else:
                print(f"✅ find_mails (grounder): {len(contacts)} contact(s) for {company}")
            return {"contacts": contacts}
        except Exception as e:
            if "'[]'" in str(e) or "failed_generation': '[]'" in str(e):
                print(f"⚠️  find_mails (grounder): empty response intercepted for {company}")
                return {"contacts": []}
            print(f"❌ find_mails (grounder): extraction error for {company}: {e}")
            return {"contacts": []}


class MailFinderAPI:
    """Node 3: one method per email-finder API provider. Takes CompanyState, returns {"contacts": [...]}."""

    def __init__(self, hunter_api_key: str = None):
        self._hunter = HunterAPI(hunter_api_key)
        # Extensible registry: add "snov", "apollo"... as new methods here later.
        self._providers = {
            "hunter": self._hunter_domain_search,
        }

    def __call__(self, state: CompanyState, provider: str = "hunter") -> dict:
        company = state.get("company_name")

        if not company or company == "null":
            print(f"⚠️  find_mails ({provider}): no company_name, search aborted")
            return {"contacts": []}

        if provider not in self._providers:
            raise ValueError(f"Unknown provider: {provider}. Available: {list(self._providers)}")

        return self._providers[provider](state)

    def _hunter_domain_search(self, state: CompanyState) -> dict:
        company = state.get("company_name")
        website = state.get("website")
        domain = self._extract_domain(website) if website else None

        if not domain:
            print(f"⚠️  find_mails (hunter): no domain for {company}, search aborted")
            return {"contacts": []}

        # QuotaExceededError is re-raised so the caller (graph) can fall back to the next provider.
        try:
            result = self._hunter.search_domain(domain=domain, company=company)
        except QuotaExceededError:
            print(f"⚠️  find_mails (hunter): quota exceeded for {company}")
            raise
        except ValueError as e:
            print(f"⚠️  find_mails (hunter): {e}")
            return {"contacts": []}

        emails = result.get("data", {}).get("emails", [])
        contacts = []
        for e in emails:
            email = e.get("value")
            if not email:
                continue

            # Read raw fields once.
            position = e.get("position", "") or ""
            department = e.get("department", "") or ""
            seniority = e.get("seniority", "") or ""
            email_type = e.get("type", "")  # "personal" or "generic"
            confidence = e.get("confidence")
            verification_status = (e.get("verification") or {}).get("status")
            linkedin = e.get("linkedin")
            first_name = e.get("first_name", "") or ""
            last_name = e.get("last_name", "") or ""

            # Score from role keywords (lowercased position + department).
            role_text = (position + department).lower()
            if any(k in role_text for k in ["data", "it", "engineer", "tech", "developer", "devops", "software"]):
                score = 0.9
            elif any(k in role_text for k in ["hr", "recruit", "talent", "rrhh", "recursos humanos"]):
                score = 0.9
            elif any(k in role_text for k in ["ceo", "cto", "cfo", "founder", "director", "gerente", "president", "vp", "executive"]):
                score = 0.7
            else:
                score = 0.4

            # Full context string for the downstream email-writing LLM.
            reason_parts = [f"Hunter match: {first_name} {last_name}".strip()]
            if position:
                reason_parts.append(f"Position: {position}")
            if department:
                reason_parts.append(f"Department: {department}")
            if seniority:
                reason_parts.append(f"Seniority: {seniority}")
            if email_type:
                reason_parts.append(f"Type: {email_type}")
            if confidence is not None:
                reason_parts.append(f"Confidence: {confidence}")
            if verification_status:
                reason_parts.append(f"Verification: {verification_status}")
            if linkedin:
                reason_parts.append(f"LinkedIn: {linkedin}")

            contacts.append({
                "email": email,
                "score": score,
                "reason": " | ".join(reason_parts),
                "source": "hunter",
            })

        if not contacts:
            print(f"⚠️  find_mails (hunter): no usable email for {company}")
        else:
            print(f"✅ find_mails (hunter): {len(contacts)} contact(s) for {company}")

        return {"contacts": contacts}

    @staticmethod
    def _extract_domain(website: str) -> str | None:
        if not website:
            return None
        domain = re.sub(r"^https?://", "", website)
        domain = re.sub(r"^www\.", "", domain)
        domain = domain.split("/")[0].strip()
        return domain or None





    
# ___ Routing functions __________________________________________
def has_relevant_email(state: CompanyState, min_score: float = 0.75) -> bool:
    """A 'relevant' email is HR or IT/Data, per the scoring convention (score >= 0.7)."""
    contacts = state.get("contacts") or []
    return any(c.get("score", 0) >= min_score for c in contacts)



def route_by_grade(state: CompanyState, threshold: int = 8) -> str:
    grade = state.get("highest_grade", 0)
    if grade >= threshold:
        return "grounder"
    return "scrapping"


def route_after_scrapping(state: CompanyState, threshold: int = 8) -> str:
    grade = state.get("highest_grade", 0)
    if has_relevant_email(state):
        return "end"
    if grade >= threshold:
        return "hunter"
    return "end"

def route_after_grounder(state: CompanyState) -> str:
    if has_relevant_email(state):
        return "end"
    return "scrapping"  # Free fallback before spending Hunter quota



# ___ Graph assembly __________________________________________


def build_find_mails_graph(llm, hunter_api_key: str = None, high_relevance_grade: int = 8):
    mail_scrapping = MailScrapping(llm)
    mail_grounder = MailGrounder(llm)
    mail_finder_api = MailFinderAPI(hunter_api_key)

    graph = StateGraph(CompanyState)

    graph.add_node("scrapping", mail_scrapping)
    graph.add_node("grounder", mail_grounder)
    graph.add_node("hunter", lambda state: mail_finder_api(state, provider="hunter"))

    # functools.partial binds the threshold, since add_conditional_edges only
    # passes the state to the routing function — it can't pass extra args itself.
    from functools import partial

    graph.add_conditional_edges(
        START,
        partial(route_by_grade, threshold=high_relevance_grade),
        {"scrapping": "scrapping", "grounder": "grounder"},
    )
    graph.add_conditional_edges(
        "grounder",
        route_after_grounder,
        {"end": END, "scrapping": "scrapping"},
    )
    graph.add_conditional_edges(
        "scrapping",
        partial(route_after_scrapping, threshold=high_relevance_grade),
        {"end": END, "hunter": "hunter"},
    )
    graph.add_edge("hunter", END)

    return graph.compile()