"""
dashboard_agent.py
───────────────────────────────────────────────────────────────────────────
Logique de l'agent du chat (FILTER / MATCH / INFO) — VERSION SIMPLIFIÉE.

Changement : plus aucun calcul de score de pertinence.
  - FILTER : applique des filtres simples (réutilise apply_filters de Streamlit).
  - MATCH  : extrait les mots-clés du profil (cloud, aws, python, …) et remonte
             par fuzzy les offres qui les contiennent. PAS de scoring LLM.
  - INFO   : répond en langage naturel à partir du README.

Principe de design : ce module est PUR.
  - aucun import de streamlit
  - ne mute jamais st.session_state
  - ne dépend plus du scoring de silver_enrichment

La couche Streamlit injecte les helpers liés au DataFrame
(`apply_filters_fn`, `default_filters_fn`) et applique les effets de bord
(merge des filtres, rerun, surlignage). `run_agent` ne fait que RETOURNER
une description de ce qu'il faut faire (`AgentResult`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Callable

import pandas as pd
from rapidfuzz import fuzz, process
from pydantic import BaseModel, Field
from langchain_core.messages import SystemMessage, HumanMessage


# ═══════════════════════════════════════════════════════════════════════
# CONFIG CENTRALE
# ═══════════════════════════════════════════════════════════════════════
@dataclass(frozen=True)
class AgentSettings:
    fuzzy_threshold: int = 70        # seuil partial_ratio (60 était trop permissif)
    max_results: Optional[int] = 25  # nb max d'offres remontées par MATCH (None = toutes)
    multiword_logic: str = "OR"      # OR-gate + classement par couverture
    min_keyword_len: int = 2         # ignore les tokens d'1 caractère (bruit)
    info_context_chars: int = 12000  # taille max du README injecté dans INFO


SETTINGS = AgentSettings()


# ═══════════════════════════════════════════════════════════════════════
# SCHÉMAS PYDANTIC
# ═══════════════════════════════════════════════════════════════════════
class AgentIntent(BaseModel):
    """Classification de l'intention en un seul appel LLM."""
    wants_filter: bool = Field(
        description="The user wants to search/filter offers (country, city, seniority, remote, keywords)."
    )
    wants_match: bool = Field(
        description="The user wants offers matching THEIR OWN profile/skills (keyword matching, no scoring)."
    )
    wants_info: bool = Field(
        description="The user asks a general question about the project, the data, the dashboard or how it works."
    )


class FilterUpdate(BaseModel):
    """Filtres extraits du message en langage naturel (FILTER + pré-filtre MATCH)."""
    search: Optional[str] = None
    countries: list[str] = Field(default_factory=list)
    cities: list[str] = Field(default_factory=list)
    seniorities: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    remote: Optional[bool] = None
    min_score: Optional[int] = None


class ProfileKeywords(BaseModel):
    """Mots-clés extraits du profil utilisateur (mis en cache côté Streamlit)."""
    skills: list[str] = Field(
        default_factory=list,
        description="Technical skills: languages, frameworks, tools, aptitudes (e.g. python, aws, cloud, airflow, docker).",
    )
    titles: list[str] = Field(
        default_factory=list,
        description="Job titles the user is looking for (e.g. data engineer, data analyst).",
    )


class AgentResponse(BaseModel):
    message: str = ""
    offer_ids: list[str] = Field(default_factory=list)
    filters_changed: bool = False


@dataclass
class AgentResult:
    """
    Ce que run_agent retourne. Streamlit en déduit les effets de bord :
      - new_filters  -> merge dans st.session_state["filters"] + dirty + rerun
      - match_table  -> tableau de résultats + surlignage des offer_ids
    """
    response: AgentResponse
    new_filters: Optional[dict] = None
    match_table: Optional[pd.DataFrame] = None
    intent: Optional[AgentIntent] = None


# ═══════════════════════════════════════════════════════════════════════
# HELPERS — colonnes / id
# ═══════════════════════════════════════════════════════════════════════
_ID_CANDIDATES = ("id_job", "job_id", "id", "offer_id")


def resolve_id_column(df: pd.DataFrame) -> Optional[str]:
    """Trouve la colonne identifiant des offres, sinon None (on utilisera l'index)."""
    for c in _ID_CANDIDATES:
        if c in df.columns:
            return c
    return None


def with_offer_id(df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute une colonne stable `_offer_id` (str) — base du surlignage et des offer_ids."""
    out = df.copy()
    id_col = resolve_id_column(out)
    out["_offer_id"] = out[id_col].astype(str) if id_col else out.index.astype(str)
    return out


def _normalize_to_options(values: list[str], options: list[str], cutoff: int = 80) -> list[str]:
    """
    Recale les valeurs renvoyées par le LLM sur les valeurs réellement présentes
    dans le df (insensible aux fautes/casse). Évite les filtres vides à cause
    d'un 'Chili' vs 'Chile' ou d'une majuscule.
    """
    if not values or not options:
        return []
    norm: list[str] = []
    for v in values:
        if v in options:
            norm.append(v)
            continue
        best = process.extractOne(v, options, scorer=fuzz.WRatio)
        if best and best[1] >= cutoff:
            norm.append(best[0])
    return list(dict.fromkeys(norm))  # dédoublonne en gardant l'ordre


# ═══════════════════════════════════════════════════════════════════════
# EXTRACTIONS LLM (structured output)
# ═══════════════════════════════════════════════════════════════════════
def extract_intent(llm, message: str) -> AgentIntent:
    structured = llm.with_structured_output(AgentIntent)
    system = SystemMessage(content=(
        "Classify the user's message about a job-offer dashboard. "
        "Set wants_filter=true if they want to filter/search offers by criteria. "
        "Set wants_match=true if they want offers matching THEIR OWN profile/skills. "
        "Set wants_info=true if it's a general question about the project/data/how it works. "
        "More than one can be true; the consuming code applies its own precedence."
    ))
    return structured.invoke([system, HumanMessage(content=message)])


def extract_filter_update(llm, message: str, options: dict) -> FilterUpdate:
    structured = llm.with_structured_output(FilterUpdate)
    system = SystemMessage(content=f"""
        Extract ONLY the filter values explicitly requested by the user.
        Leave everything else null / empty. Map the user's wording to the CLOSEST available value.

        Available countries:   {options.get('countries')}
        Available cities:       {options.get('cities')}
        Available seniorities:  {options.get('seniorities')}
        Available companies:    {options.get('companies')}

        remote: true if they want remote/telework, false if on-site, null if unspecified.
        search: free keywords (job title / tech) only if relevant.
    """)
    return structured.invoke([system, HumanMessage(content=message)])


def extract_profile_keywords(llm, profile_text: str) -> ProfileKeywords:
    structured = llm.with_structured_output(ProfileKeywords)
    system = SystemMessage(content=(
        "Extract the user's technical skills (languages, frameworks, tools, aptitudes — "
        "e.g. python, aws, cloud, airflow, docker) and the job titles they target. "
        "Be exhaustive but use ONLY what is stated. Return short keywords, not sentences."
    ))
    return structured.invoke([system, HumanMessage(content=profile_text or "")])


def answer_info(llm, question: str, readme_text: str, settings: AgentSettings = SETTINGS) -> str:
    system = SystemMessage(content=f"""
        You explain a personal data-engineering project: an automated pipeline that collects and
        enriches Data-Engineering internship/job offers in Latin America, plus a Streamlit dashboard.
        Answer ONLY from the documentation below. If the answer is not there, say so briefly.
        Be concise (a few sentences). Answer in the user's language.

        --- DOCUMENTATION ---
        {(readme_text or '')[:settings.info_context_chars]}
    """)
    resp = llm.invoke([system, HumanMessage(content=question)])
    return resp.content


# ═══════════════════════════════════════════════════════════════════════
# FUZZY KEYWORD MATCHING  (remplace l'ancien scoring)
# ═══════════════════════════════════════════════════════════════════════
def _skill_blob(row: dict) -> str:
    """Concatène les compétences d'une offre en un texte cherchable (lower)."""
    parts: list[str] = []
    for col in ("skills_languages", "skills_framework", "skills_frameworks",
                "skills_aptitudes", "alternative_job_titles", "job_title"):
        v = row.get(col)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, str):
            parts.append(v)
    return " ".join(p.lower() for p in parts if p)


def fuzzy_match_offers(df: pd.DataFrame, keywords: list[str], settings: AgentSettings = SETTINGS) -> pd.DataFrame:
    """
    Remonte les offres dont les compétences correspondent aux mots-clés du profil.

    Logique multi-mots : OR-gate + classement par couverture.
      - OR-gate : une offre est retenue si AU MOINS un mot-clé dépasse le seuil
                  (un profil a beaucoup de skills ; un AND strict viderait le résultat).
      - Ranking : on classe par NOMBRE de mots-clés couverts, puis par ratio moyen.
                  Les offres touchant plusieurs compétences remontent en tête.

    Retour : DataFrame [_offer_id, job_title, company_name, matched, coverage]
             trié du plus pertinent au moins pertinent. Aucun score LLM.
    """
    df = df if "_offer_id" in df.columns else with_offer_id(df)
    kws = [k.lower().strip() for k in keywords
           if k and len(k.strip()) >= settings.min_keyword_len]

    if df.empty or not kws:
        return df.iloc[0:0].copy()

    rows: list[dict] = []
    for row in df.to_dict("records"):
        blob = _skill_blob(row)
        if not blob:
            continue
        matched_kw: list[str] = []
        ratios: list[float] = []
        for kw in kws:
            r = fuzz.partial_ratio(kw, blob)
            if r >= settings.fuzzy_threshold:
                matched_kw.append(kw)
                ratios.append(r)
        if not matched_kw:                       # OR-gate
            continue
        rows.append({
            "_offer_id": str(row.get("_offer_id")),
            "job_title": row.get("job_title"),
            "company_name": row.get("company_name"),
            "matched": matched_kw,
            "coverage": len(matched_kw),
            "_avg": sum(ratios) / len(ratios),
        })

    if not rows:
        return df.iloc[0:0].copy()

    res = (
        pd.DataFrame(rows)
        .sort_values(["coverage", "_avg"], ascending=False)
        .drop(columns="_avg")
        .reset_index(drop=True)
    )
    if settings.max_results:
        res = res.head(settings.max_results)
    return res


# ═══════════════════════════════════════════════════════════════════════
# BRANCHES
# ═══════════════════════════════════════════════════════════════════════
def _options_from_df(df: pd.DataFrame) -> dict:
    return {
        "countries":   sorted(df["country"].dropna().unique().tolist())      if "country" in df else [],
        "cities":      sorted(df["city"].dropna().unique().tolist())         if "city" in df else [],
        "seniorities": sorted(df["seniority"].dropna().unique().tolist())    if "seniority" in df else [],
        "companies":   sorted(df["company_name"].dropna().unique().tolist()) if "company_name" in df else [],
    }


def _filterupdate_to_partial(fu: FilterUpdate, options: dict, current_filters: dict) -> dict:
    """Convertit un FilterUpdate (clés LLM) vers un partiel du dict de filtres Streamlit."""
    new: dict = {}
    if fu.search:
        new["search"] = fu.search
    c = _normalize_to_options(fu.countries, options.get("countries", []))
    if c:
        new["countries"] = c
    ci = _normalize_to_options(fu.cities, options.get("cities", []))
    if ci:
        new["cities"] = ci
    se = _normalize_to_options(fu.seniorities, options.get("seniorities", []))
    if se:
        new["seniorities"] = se
    co = _normalize_to_options(fu.companies, options.get("companies", []))
    if co:
        new["companies"] = co
    if fu.remote is not None:
        new["remote"] = fu.remote
    if fu.min_score is not None:
        cur_hi = current_filters.get("score_range", (0, 10))[1]
        new["score_range"] = (max(0, min(10, int(fu.min_score))), cur_hi)
    return new


def _do_filter(llm, message, df, current_filters, intent) -> AgentResult:
    options = _options_from_df(df)
    fu = extract_filter_update(llm.llama3_smart, message, options)
    new = _filterupdate_to_partial(fu, options, current_filters)
    if new:
        bits = ", ".join(f"{k}={v}" for k, v in new.items())
        msg = f"Filters updated: {bits}."
    else:
        msg = "I couldn't extract a usable filter from your message. Try e.g. “remote data jobs in Chile”."
    resp = AgentResponse(message=msg, filters_changed=bool(new))
    return AgentResult(response=resp, new_filters=new or None, intent=intent)


def _format_match_message(matched: pd.DataFrame, top: int = 3) -> str:
    if matched.empty:
        return "No offer matched your profile keywords with the current constraints."
    lines = ["Offers matching your profile:"]
    for _, r in matched.head(top).iterrows():
        kws = ", ".join(r["matched"]) if isinstance(r["matched"], list) else ""
        lines.append(f"• {r['job_title']} — {r['company_name']} (matched: {kws})")
    if len(matched) > top:
        lines.append(f"… and {len(matched) - top} more in the results table below.")
    return "\n".join(lines)


def _do_match(llm, message, df, user_profile, current_filters,
              apply_filters_fn, default_filters_fn, profile_keywords, settings, intent) -> AgentResult:
    if not (user_profile or "").strip():
        return AgentResult(
            response=AgentResponse(message="Please fill in your profile first (skills + target role) so I can match offers."),
            intent=intent,
        )

    # 1) Mots-clés du profil (cache géré côté Streamlit ; sinon extraction directe)
    pk = profile_keywords or extract_profile_keywords(llm.llama4_smart, user_profile)

    # 2) Pré-filtre STATELESS depuis le message (ne touche jamais session_state)
    options = _options_from_df(df)
    fu = extract_filter_update(llm.llama3_smart, message, options)
    ephemeral = default_filters_fn()
    ephemeral.update(_filterupdate_to_partial(fu, options, ephemeral))
    pre = apply_filters_fn(df, ephemeral)
    if pre.empty:
        return AgentResult(
            response=AgentResponse(message="No offers match those constraints. Loosen the filters and try again."),
            intent=intent,
        )

    # 3) Fuzzy keyword matching (PAS de scoring)
    pre = with_offer_id(pre)
    keywords = list(dict.fromkeys((pk.skills or []) + (pk.titles or [])))
    matched = fuzzy_match_offers(pre, keywords, settings)
    resp = AgentResponse(
        message=_format_match_message(matched),
        offer_ids=matched["_offer_id"].tolist() if not matched.empty else [],
        filters_changed=False,
    )
    return AgentResult(response=resp, match_table=matched, intent=intent)


def _do_info(llm, message, readme_text, settings, intent) -> AgentResult:
    msg = answer_info(llm.llama3_smart, message, readme_text, settings)
    return AgentResult(response=AgentResponse(message=msg), intent=intent)


# ═══════════════════════════════════════════════════════════════════════
# ORCHESTRATEUR
# ═══════════════════════════════════════════════════════════════════════
def run_agent(
    *,
    llm,                                  # instance LLM de silver_enrichment (.llama3_smart / .llama4_smart)
    message: str,
    df: pd.DataFrame,
    user_profile: str,
    current_filters: dict,
    readme_text: str,
    apply_filters_fn: Callable[[pd.DataFrame, dict], pd.DataFrame],
    default_filters_fn: Callable[[], dict],
    profile_keywords: Optional[ProfileKeywords] = None,
    settings: AgentSettings = SETTINGS,
) -> AgentResult:
    """
    Point d'entrée unique. Retourne un AgentResult ; Streamlit applique les effets de bord.
    Précédence des intentions : MATCH > FILTER > INFO.
    """
    intent = extract_intent(llm.llama3_smart, message)

    if intent.wants_match:
        return _do_match(llm, message, df, user_profile, current_filters,
                         apply_filters_fn, default_filters_fn, profile_keywords, settings, intent)
    if intent.wants_filter:
        return _do_filter(llm, message, df, current_filters, intent)
    return _do_info(llm, message, readme_text, settings, intent)