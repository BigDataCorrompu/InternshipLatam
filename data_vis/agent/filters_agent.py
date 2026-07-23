from typing import Literal

from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage

CONTEXT = """
        Extract job search filters from the user query, as incremental actions (add/remove/set)
        on top of whatever is already filtered. Only include an action or field if the user
        clearly mentions it — otherwise leave it out / null.

        Per-field formatting rules (apply these when producing `values` for each field):

        - country: full country names (e.g. "Chile", "Argentina", "Uruguay"), not codes.
        - city: city names as mentioned, no country attached.
        - companies: company names as mentioned by the user.
        - contract_types: map natural language to exactly one of
        ["internship", "fulltime", "parttime", "freelance"].
        Examples: "stage"/"internship" → internship, "full-time"/"CDI" → fulltime,
        "part-time" → parttime, "freelance"/"contractor" → freelance.
        - seniority: map natural language to exactly one of ["junior", "mid", "senior"].
        Examples: "entry-level"/"intern" → junior, "experienced" → mid, "expert"/"lead" → senior.
        - offer_languages: full language names (English, Spanish, French), never ISO codes.
        Only include a language if the user explicitly asks for it, or states they are
        proficient enough to work in it. If the user says they are a beginner in a language,
        do NOT include it.
        - keywords: job titles (e.g. "data engineer"), programming languages (e.g. "sql", "python"),
        frameworks/tools (e.g. "airflow", "aws", "power bi"), aptitudes (e.g. "architectural
        decision-making"), or soft skills (e.g. "communication").
        - date_range : map natural language time expressions to the closest valid value
        among [1, 3, 7, 14, 30, 60, 90]:
            - "today"/"aujourd'hui" → 1
            - "this week"/"cette semaine" → 7
            - "last 2 weeks" → 14
            - "this month"/"ce mois" → 30
            - If no time expression is mentioned, leave date_range null (don't reset it).


        Use 'add'/'remove' when the user is modifying an existing filter (e.g. "also add Chile",
        "remove Argentina", "drop the internship filter"). Use 'set' when the user gives a fresh
        complete list, says "only X", or is filtering that field for the first time.

        You can include several actions in the same request, on the same field or different fields.

        ALWAYS REPLY IN ENGLISH.
        """

# ═══════════════════════════════════════════════════════════════════════
# SCHÉMA
# ═══════════════════════════════════════════════════════════════════════
class FieldAction(BaseModel):
    field: Literal[
        "country", "city", "companies", "contract_types",
        "seniority", "offer_languages", "keywords",
    ] = Field(description="Which list-based filter this action applies to. See system prompt for formatting rules per field.")
    action: Literal["add", "remove", "set"] = Field(description="""
        'add': add these values to the existing filter, keeping what was already selected.
        'remove': remove these values from the existing filter, keeping the rest.
        'set': replace the existing filter entirely with these values.
        """)
    values: list[str] = Field(description="Values to add/remove/set, formatted per the rules for this field (see system prompt).")

class FilterCriteria(BaseModel):
    actions: list[FieldAction] | None = Field(default=None, description="""
        Incremental changes to list-based filters: country, city, companies,
        contract_types, seniority, offer_languages, keywords.
        Use 'add'/'remove' when the user says things like "also add Chile",
        "remove Argentina", "take out the internship filter".
        Use 'set' when the user gives a fresh complete list, or says "only X",
        or is filtering from scratch (no prior mention of that field).
        You can include several actions in the same request, e.g. one 'add' for
        country and one 'remove' for another country, or actions on different fields.
        """)

    min_score: float | None = Field(default=None, description="""
        Each offer has a relevancy score from 0 to 10.
        Return the minimum score requested by the user, if mentioned.
        """)

    max_score: float | None = Field(default=None, description="""
        The maximum relevancy score requested (0 to 10).
        Use this when the user wants offers below a certain score,
        or specifies a score range (e.g. "between 4 and 7").
        """)

    is_remote: bool | None = Field(default=None, description="""
        True if the user wants remote/hybrid work, False if they want on-site only.
        Return null if not mentioned.
        """)

    date_range: Literal[1, 3, 7, 14, 30, 60, 90] | None = Field(default=None, description="""
        The number of days since the offer was posted.
        """)


# ═══════════════════════════════════════════════════════════════════════
# EXTRACTION (un seul appel LLM)
# ═══════════════════════════════════════════════════════════════════════
def extract_filters(query: str, llm, session_id: str = "default") -> FilterCriteria:
    """Extrait un FilterCriteria depuis la requête utilisateur. `llm` = ChatMistralAI (ou compatible)."""
    llm_with_cache = llm.bind(prompt_cache_key=f"dashboard-{session_id}")
    llm_extract = llm_with_cache.with_structured_output(FilterCriteria)
    system = SystemMessage(content=CONTEXT)  
    return llm_extract.invoke([system, HumanMessage(content=query)])


# ═══════════════════════════════════════════════════════════════════════
# CONVERSION vers le dict de filtres de l'app
# ═══════════════════════════════════════════════════════════════════════
# Maps a FieldAction.field name -> the actual key used in the app's filter dict
_FIELD_TO_FILTER_KEY = {
    "country": "countries",
    "city": "cities",
    "companies": "companies",
    "contract_types": "contracts",
    "seniority": "seniorities",
    "offer_languages": "languages",
    "keywords": "search",  # special-cased below: stored as a comma string, not a list
}


def _get_current_list(f: dict, filter_key: str) -> list[str]:
    """Read the current value of a list-based filter as an actual list,
    handling `search` (stored as a comma-separated string) specially."""
    if filter_key == "search":
        raw = f.get("search", "")
        return [w.strip() for w in raw.split(",") if w.strip()]
    return list(f.get(filter_key, []))


def _set_list(f: dict, filter_key: str, values: list[str]) -> None:
    """Write back a list-based filter, handling `search` specially."""
    if filter_key == "search":
        f["search"] = ", ".join(values)
    else:
        f[filter_key] = values

_VALID_VALUES = {
    "contract_types": {"internship", "fulltime", "parttime", "freelance"},
    "seniority": {"junior", "mid", "senior"},
}
def _apply_action(f: dict, action: FieldAction) -> None:
    filter_key = _FIELD_TO_FILTER_KEY[action.field]
    valid_set = _VALID_VALUES.get(action.field)
    values = [v for v in action.values if valid_set is None or v.lower() in valid_set]
    current = _get_current_list(f, filter_key)

    if action.action == "set":
        new_values = list(dict.fromkeys(action.values))  # dedupe, keep order
    elif action.action == "add":
        new_values = list(dict.fromkeys(current + action.values))
    elif action.action == "remove":
        to_remove = {v.lower() for v in action.values}
        new_values = [v for v in current if v.lower() not in to_remove]
    else:
        new_values = current

    _set_list(f, filter_key, new_values)


def criteria_to_filter_dict(criteria: FilterCriteria, current_filters: dict) -> dict:
    """
    Convertit le FilterCriteria du LLM en dict compatible avec apply_filters,
    en partant des filtres actuels. Les champs liste sont modifiés de façon
    incrémentale (add/remove/set) via `criteria.actions`; les champs scalaires
    (score, remote, date) écrasent directement s'ils sont mentionnés.
    """
    f = dict(current_filters)

    if criteria.actions:
        for action in criteria.actions:
            _apply_action(f, action)

    if criteria.min_score is not None or criteria.max_score is not None:
        current_lo, current_hi = f.get("score_range", (0, 10))
        lo = float(criteria.min_score) if criteria.min_score is not None else current_lo
        hi = float(criteria.max_score) if criteria.max_score is not None else current_hi
        f["score_range"] = (lo, hi)
    if criteria.is_remote is not None:
        f["remote"] = criteria.is_remote
    if criteria.date_range is not None:
        f["max_days"] = criteria.date_range

    return f


# ═══════════════════════════════════════════════════════════════════════
# Message de confirmation (facultatif, pour le chat)
# ═══════════════════════════════════════════════════════════════════════
def summarize_criteria(criteria: FilterCriteria) -> str:
    """Petit récap en langage naturel des filtres détectés (affiché dans le chat)."""
    parts: list[str] = []

    if criteria.actions:
        for action in criteria.actions:
            verb = {"add": "added", "remove": "removed", "set": "set"}[action.action]
            parts.append(f"{action.field} {verb}: {', '.join(action.values)}")

    if criteria.is_remote is not None:
        parts.append("remote" if criteria.is_remote else "on-site")
    if criteria.min_score is not None:
        parts.append(f"min score: {criteria.min_score}")
    if criteria.max_score is not None:
        parts.append(f"max score: {criteria.max_score}")
    if criteria.date_range is not None:
        parts.append(f"last {criteria.date_range} days")

    if not parts:
        return "I didn't detect any filter change in your message. Try e.g. “add Chile, remove Argentina”."
    return "✅ Filters updated → " + " · ".join(parts)