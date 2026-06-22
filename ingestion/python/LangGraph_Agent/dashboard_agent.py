from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage


# ═══════════════════════════════════════════════════════════════════════
# SCHÉMA
# ═══════════════════════════════════════════════════════════════════════
class FilterCriteria(BaseModel):
    all_keywords: list[str] | None = Field(default=None, description="""
        A list of keywords described by the user.
        It includes:
        job titles: data engineer, database administrator
        programming languages: sql, python, terraform
        frameworks: AWS, airflow, PowerBI
        aptitudes: architectural decision-making
        skills soft: communication
        """)

    offer_languages: list[str] | None = Field(default=None, description="""
        A list of languages like English, Spanish, etc.
        Only include a language if the user explicitly asks for it,
        or if the user states they are proficient enough to work in it.
        If level beginner don't include it in the list.
        Return as full language names (English, Spanish, French), not ISO codes.
        """)

    min_score: float | None = Field(default=None, description="""
        Each offer has a relevancy score from 0 to 10.
        Return the minimum score requested by the user, if mentioned.
        """)

    city: list[str] | None = Field(default=None, description="""
        A list of cities where the user is searching for a job offer.
        """)

    country: Literal["Chile", "Argentina", "Uruguay"] | list[Literal["Chile", "Argentina", "Uruguay"]] | None = Field(
        default=None,
        description="""
        The country (or countries) where the user is searching for a job offer.
        If the user only mentions a city but no country, return null for this field.
        """,
    )

    companies: list[str] | None = Field(default=None, description="""
        A list of company names mentioned by the user.
        """)

    contract_types: list[Literal["internship", "fulltime", "parttime", "freelance"]] | None = Field(
        default=None,
        description="""
        The contract type(s) requested by the user.
        Map from natural language: 'stage'/'internship' → internship,
        'full-time'/'CDI' → fulltime, 'part-time' → parttime, 'freelance'/'contractor' → freelance.
        """,
    )

    is_remote: bool | None = Field(default=None, description="""
        True if the user wants remote/hybrid work, False if they want on-site only.
        Return null if not mentioned.
        """)

    seniority: list[Literal["junior", "mid", "senior"]] | None = Field(default=None, description="""
        The seniority level(s) requested by the user.
        Map: 'entry-level'/'intern' → junior, 'experienced' → mid, 'expert'/'lead' → senior.
        """)

    date_range: int | None = Field(default=None, description="""
        The number of days since the offer was collected.
        """)


# ═══════════════════════════════════════════════════════════════════════
# EXTRACTION (un seul appel LLM)
# ═══════════════════════════════════════════════════════════════════════
def extract_filters(query: str, llm) -> FilterCriteria:
    """Extrait un FilterCriteria depuis la requête utilisateur. `llm` = ChatGroq (ou compatible)."""
    llm_extract = llm.with_structured_output(FilterCriteria)
    system = SystemMessage(content=(
        "Extract job search filters from the user query. "
        "Only fill a field if the user clearly mentions it, otherwise leave it null. "
        "ALWAYS REPLY IN ENGLISH."
    ))
    return llm_extract.invoke([system, HumanMessage(content=query)])


# ═══════════════════════════════════════════════════════════════════════
# CONVERSION vers le dict de filtres de l'app
# ═══════════════════════════════════════════════════════════════════════
def criteria_to_filter_dict(criteria: FilterCriteria, current_filters: dict) -> dict:
    """
    Convertit le FilterCriteria du LLM en dict compatible avec apply_filters,
    en partant des filtres actuels (on ne réinitialise que ce que l'utilisateur a mentionné).
    """
    f = dict(current_filters)  # copie : conserve score_range, languages, etc. déjà actifs

    if criteria.all_keywords:
        f["search"] = " ".join(criteria.all_keywords)
    if criteria.offer_languages:
        f["languages"] = criteria.offer_languages
    if criteria.city:
        f["cities"] = criteria.city
    if criteria.country:
        f["countries"] = criteria.country if isinstance(criteria.country, list) else [criteria.country]
    if criteria.companies:
        f["companies"] = criteria.companies
    if criteria.contract_types:
        f["contracts"] = criteria.contract_types
    if criteria.is_remote is not None:
        f["remote"] = criteria.is_remote
    if criteria.seniority:
        f["seniorities"] = criteria.seniority
    if criteria.min_score is not None:
        _, hi = f.get("score_range", (0, 10))
        f["score_range"] = (criteria.min_score, hi)
    if criteria.date_range is not None:
        f["max_days"] = criteria.date_range

    return f


# ═══════════════════════════════════════════════════════════════════════
# Message de confirmation (facultatif, pour le chat)
# ═══════════════════════════════════════════════════════════════════════
def summarize_criteria(criteria: FilterCriteria) -> str:
    """Petit récap en langage naturel des filtres détectés (affiché dans le chat)."""
    parts: list[str] = []
    if criteria.all_keywords:
        parts.append(f"keywords: {', '.join(criteria.all_keywords)}")
    if criteria.country:
        c = criteria.country if isinstance(criteria.country, list) else [criteria.country]
        parts.append(f"country: {', '.join(c)}")
    if criteria.city:
        parts.append(f"city: {', '.join(criteria.city)}")
    if criteria.companies:
        parts.append(f"companies: {', '.join(criteria.companies)}")
    if criteria.contract_types:
        parts.append(f"contract: {', '.join(criteria.contract_types)}")
    if criteria.seniority:
        parts.append(f"seniority: {', '.join(criteria.seniority)}")
    if criteria.offer_languages:
        parts.append(f"language: {', '.join(criteria.offer_languages)}")
    if criteria.is_remote is not None:
        parts.append("remote" if criteria.is_remote else "on-site")
    if criteria.min_score is not None:
        parts.append(f"min score: {criteria.min_score}")
    if criteria.date_range is not None:
        parts.append(f"last {criteria.date_range} days")

    if not parts:
        return "I didn't detect any filter in your message. Try e.g. “remote data engineer jobs in Chile”."
    return "✅ Filters applied → " + " · ".join(parts)