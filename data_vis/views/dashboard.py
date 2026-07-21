"""
════════════════════════════════════════════════════════════════════════════
InternshipLatam — AI-Powered Job Offer Dashboard (LATAM)
════════════════════════════════════════════════════════════════════════════
Streamlit dashboard that loads enriched job offers from the Gold layer
(serving.job_offer on Neon), lets the user filter them (manually via the
sidebar OR through the LLM chatbot), and visualises them on an interactive
map + charts.

Performance notes:
- All DB access and heavy transforms are cached (@st.cache_data / cache_resource).
- The map aggregation (groupby by location) is cached separately so that UI-only
  reruns (e.g. opening/closing the chat) don't recompute it.
════════════════════════════════════════════════════════════════════════════
"""

# ════════════════════════════════════════════════════════════════════
# Imports
# ════════════════════════════════════════════════════════════════════
import os
import sys
import re
import time
import importlib.util
from collections import defaultdict
from pathlib import Path

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from rapidfuzz import process, fuzz
import country_converter as coco
import pycountry
from langchain_groq import ChatGroq

# ════════════════════════════════════════════════════════════════════
# Local module resolution (project is a monorepo, DB lives in ingestion/)
# ════════════════════════════════════════════════════════════════════
# dashboard.py is at: <root>/data_vis/views/dashboard.py  (or ingestion/python/user_interface/views/)
# We add the sibling source folders to sys.path so local modules import cleanly.
_PARENT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for _folder in [
    _PARENT,
    os.path.join(_PARENT, "LangGraph_Agent"),
    os.path.join(_PARENT, "src"),
    os.path.join(_PARENT, "user_interface"),
]:
    if _folder not in sys.path:
        sys.path.append(_folder)

# Load the Database class by absolute path (avoids namespace collision with the
# top-level `database/` SQL folder, which Python would otherwise treat as a package).
_DB_PATH = Path(__file__).resolve().parents[2] / "ingestion" / "python" / "src" / "database.py"
_spec = importlib.util.spec_from_file_location("db_module", _DB_PATH)
_db_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_module)
Database = _db_module.Database

from dashboard_agent import (
    extract_filters,
    criteria_to_filter_dict,
    summarize_criteria,
)

# ════════════════════════════════════════════════════════════════════
# Page config
# ════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="AI Job Offer Dashboard Latam", page_icon="🏙️", layout="wide")
st.title("🏙️ AI Powered pipeline Job offers LATAM")


# ════════════════════════════════════════════════════════════════════
# Cached resources (persistent objects: DB connection, LLM client)
# ════════════════════════════════════════════════════════════════════
@st.cache_resource
def get_db_connection() -> Database:
    """Persistent Database object (HTTP to Neon). Cached for the whole app process."""
    return Database(**st.secrets["database"])


@st.cache_resource
def get_llm() -> ChatGroq:
    """Groq LLM client (independent from the Silver enrichment / Ollama stack)."""
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=st.secrets["groq"]["api_key"],
        temperature=0,
    )


# ════════════════════════════════════════════════════════════════════
# Data loading (cached — one round-trip to Neon, refreshed on TTL)
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner="Fetching real data from database...")
def load_real_offers() -> list:
    """Fetch enriched offers from the Gold serving view. Refreshes the view if stale."""
    db = get_db_connection()
    query = """
    SELECT
        id_offer as job_id,
        api_source,
        job_title,
        contract_type,
        is_remote,
        offer_languages,
        seniority,
        skills_languages,
        skills_frameworks,
        skills_aptitudes,
        skills_soft,
        alternative_job_titles,
        score_relevancy,
        explanation,
        company_name,
        website,
        primary_type,
        city,
        country,
        lat as latitude,
        lon as longitude,
        offer_url,
        published_at,
        collected_at
    FROM serving.job_offer;
    """
    # Refresh view old version
    #db.execute("SELECT serving.refresh_job_offer_if_stale();")
    return db.execute(query)


# ════════════════════════════════════════════════════════════════════
# Reverse index for fast keyword search
# ════════════════════════════════════════════════════════════════════
def generate_reverse_index(df: pd.DataFrame) -> dict:
    """Build {keyword -> [offer indices]} from the combined `all_keywords` column."""
    index = defaultdict(set)
    for idx, row in df.iterrows():
        keywords = row.get("all_keywords", [])
        if not isinstance(keywords, list):
            continue
        # Normalise, dedupe, and skip any non-string / None element
        unique_words = {kw.lower().strip() for kw in keywords if isinstance(kw, str)}
        for kw in unique_words:
            index[kw].add(idx)
    return {k: list(v) for k, v in index.items()}


# ════════════════════════════════════════════════════════════════════
# Language code -> full name conversion (memoised)
# ════════════════════════════════════════════════════════════════════
_LANG_CACHE: dict[str, str] = {}


def convert_language_list(code_list) -> list:
    """Convert ISO 639 codes (e.g. 'es', 'en') to full language names, cached per code."""
    if not isinstance(code_list, list):
        return []
    names = []
    for code in code_list:
        c = str(code).strip().lower()
        if not c:
            continue
        if c in _LANG_CACHE:
            names.append(_LANG_CACHE[c])
            continue
        lang = pycountry.languages.get(alpha_2=c) or pycountry.languages.get(alpha_3=c)
        name = lang.name if lang else c
        _LANG_CACHE[c] = name
        names.append(name)
    return names


# ════════════════════════════════════════════════════════════════════
# Main load + transform (cached — the expensive one-time preparation)
# ════════════════════════════════════════════════════════════════════
@st.cache_data
def load_and_transform_dataframe() -> tuple[pd.DataFrame, dict]:
    """Load raw offers, clean, enrich (country/language full names, keyword blob),
    and build the reverse index. Everything downstream reads from this cached result."""
    df = pd.DataFrame(load_real_offers())
    df.set_index("job_id", inplace=True)

    # ── Basic cleaning ──
    df["is_remote"] = df["is_remote"].fillna(False)
    df["country"] = df["country"].fillna("Not specified")
    df["company_name"] = df["company_name"].fillna("unknown")
    if "collected_at" in df.columns:
        df["collected_at"] = pd.to_datetime(df["collected_at"])

    # ── Full country names (only for non-null rows) ──
    cc = coco.CountryConverter()
    mask_country = df["country"].notna()
    mask_language = df["offer_languages"].notna()

    df.loc[mask_country, "country_full"] = cc.convert(
        df.loc[mask_country, "country"].tolist(), to="name_short"
    )
    df["country_full"] = df["country_full"].replace("not found", np.nan)

    # ── Full language names ──
    df.loc[mask_language, "offer_languages_full"] = (
        df.loc[mask_language, "offer_languages"].apply(convert_language_list)
    )

    # ── Combined keyword column (from separate skill columns) for search ──
    KEYWORD_COLS = [
        "skills_languages", "skills_frameworks", "skills_aptitudes",
        "skills_soft", "alternative_job_titles",
    ]

    def _combine_keywords(row) -> list:
        combined = []
        for col in KEYWORD_COLS:
            val = row.get(col)
            if isinstance(val, list):
                combined.extend(kw for kw in val if isinstance(kw, str))
        return combined

    df["all_keywords"] = df.apply(_combine_keywords, axis=1)

    dict_reversed_index = generate_reverse_index(df)
    return df, dict_reversed_index


@st.cache_data
def build_city_country_map(df: pd.DataFrame) -> dict:
    """Map each city to its full country name.
    Prevents e.g. 'Santiago del Estero' (Argentina) from matching a 'Santiago' (Chile) filter."""
    mapping = {}
    for _, row in df.dropna(subset=["city", "country"]).iterrows():
        mapping[row["city"]] = row["country_full"]
    return mapping


@st.cache_data
def get_filter_options(df: pd.DataFrame, dict_reversed_index: dict) -> dict:
    """Precompute all option lists used by the sidebar widgets."""
    if not df["score_relevancy"].empty:
        min_score, max_score = int(df["score_relevancy"].min()), int(df["score_relevancy"].max())
    else:
        min_score, max_score = 0, 10

    return {
        "all_keywords": list(dict_reversed_index.keys()),
        "min_score": min_score,
        "max_score": max_score,
        "contracts": sorted(df["contract_type"].dropna().unique().tolist()),
        "cities": sorted(df["city"].dropna().unique().tolist()),
        "seniorities": sorted(df["seniority"].dropna().unique().tolist()),
        "companies": sorted(df["company_name"].dropna().unique().tolist()),
        "countries": sorted(df["country_full"].dropna().unique().tolist()),
        "languages": sorted(set(
            lang for sub in df["offer_languages_full"].dropna() for lang in sub
        )),
        "remote_labels": {None: "All", True: "Remote", False: "On-site"},
        "day_options": [7, 14, 30, 60, 90, "All time"],
    }


# ════════════════════════════════════════════════════════════════════
# Load data & derive shared constants
# ════════════════════════════════════════════════════════════════════
df, dict_reversed_index = load_and_transform_dataframe()
filters = get_filter_options(df, dict_reversed_index)
city_country_map = build_city_country_map(df)

REMOTE_LABELS = filters["remote_labels"]
REMOTE_VALUES = {v: k for k, v in REMOTE_LABELS.items()}
ALL_COMPANIES = sorted(df["company_name"].dropna().unique().tolist())

if "highlighted_job_id" not in st.session_state:
    st.session_state["highlighted_job_id"] = None


# ════════════════════════════════════════════════════════════════════
# Filtering logic
# ════════════════════════════════════════════════════════════════════
def get_fuzzy_matching_ids(user_input: str, dict_reversed_index: dict, threshold: int = 55) -> set:
    """Return offer indices whose indexed keywords fuzzy-match the user input."""
    matches = process.extract(
        user_input, dict_reversed_index.keys(), scorer=fuzz.WRatio, limit=5
    )
    matching_ids = set()
    for word, score, _ in matches:
        if score >= threshold:
            matching_ids.update(dict_reversed_index.get(word, []))
    return matching_ids


def apply_filters(df: pd.DataFrame, f: dict, dict_reversed_index: dict, city_country_map: dict) -> pd.DataFrame:
    """Apply the active filter dict `f` to the offers DataFrame and return the subset."""
    out = df.copy()

    # ── Keyword search (fuzzy, ranked by number of matching words) ──
    if f["search"]:
        search_words = f["search"].lower().split()
        match_counts: dict = {}
        for word in search_words:
            for idx in get_fuzzy_matching_ids(word, dict_reversed_index):
                match_counts[idx] = match_counts.get(idx, 0) + 1
        if match_counts:
            out = out.loc[out.index.isin(match_counts.keys())].copy()
            out["_keyword_match_count"] = out.index.map(match_counts)
            out = out.sort_values("_keyword_match_count", ascending=False)
        else:
            return out.iloc[0:0]

    # ── Score range ──
    lo, hi = f["score_range"]
    out = out[(out["score_relevancy"] >= lo) & (out["score_relevancy"] <= hi)]

    # ── Contract type ──
    if f["contracts"]:
        out = out[out["contract_type"].isin(f["contracts"])]

    # ── Cities (substring match; infer country when only a city is given) ──
    if f["cities"]:
        pattern = "|".join(re.escape(c) for c in f["cities"])
        out = out[out["city"].str.contains(pattern, case=False, na=False)]

        inferred_countries = {city_country_map[c] for c in f["cities"] if c in city_country_map}
        if inferred_countries and not f["countries"]:
            out = out[out["country_full"].isin(inferred_countries)]

    # ── Countries ──
    if f["countries"]:
        pattern = "|".join(re.escape(c) for c in f["countries"])
        out = out[out["country_full"].str.contains(pattern, case=False, na=False)]

    # ── Languages (exact match on normalised full names) ──
    if f["languages"]:
        out = out[out["offer_languages_full"].apply(
            lambda langs: any(l in langs for l in f["languages"]) if langs else False
        )]

    # ── Seniority (exact; constrained by Pydantic Literal upstream) ──
    if f["seniorities"]:
        out = out[out["seniority"].isin(f["seniorities"])]

    # ── Companies (substring; LLM-extracted names may vary slightly) ──
    if f.get("companies"):
        pattern = "|".join(re.escape(c) for c in f["companies"])
        out = out[out["company_name"].str.contains(pattern, case=False, na=False)]

    # ── Remote ──
    if f["remote"] is not None:
        out = out[out["is_remote"] == f["remote"]]

    # ── Date range ("All time" = no filter) ──
    if f["max_days"] != "All time" and "collected_at" in out.columns:
        column_tz = out["collected_at"].dt.tz
        cutoff = pd.Timestamp.now(tz=column_tz) - pd.Timedelta(days=f["max_days"])
        out = out[out["collected_at"] >= cutoff]

    return out


# ════════════════════════════════════════════════════════════════════
# Default filters — source of truth: st.session_state["filters"]
# ════════════════════════════════════════════════════════════════════
def default_filters(options: dict) -> dict:
    return {
        "search":      "",
        "score_range": (max(0, options.get("min_score", 0)), min(10, options.get("max_score", 10))),
        "contracts":   list(options["contracts"]),
        "cities":      [],
        "countries":   [],
        "languages":   [],
        "seniorities": list(options["seniorities"]),  # all checked by default (intentional)
        "remote":      None,                            # None = "All"
        "max_days":    30,
        "companies":   [],
    }


if "filters" not in st.session_state:
    st.session_state["filters"] = default_filters(filters)

f = st.session_state["filters"]

# ════════════════════════════════════════════════════════════════════
# Sync dict -> widgets, BEFORE creating the widgets.
# Runs on first load OR when the reset button / chatbot just modified `f`.
# ════════════════════════════════════════════════════════════════════
if st.session_state.pop("_filters_dirty", False) or "w_score" not in st.session_state:
    st.session_state["w_search"]      = f["search"]
    st.session_state["w_score"]       = f["score_range"]
    st.session_state["w_contracts"]   = f["contracts"]
    st.session_state["w_cities"]      = f["cities"]
    st.session_state["w_countries"]   = f["countries"]
    st.session_state["w_languages"]   = f["languages"]
    st.session_state["w_seniorities"] = f["seniorities"]
    st.session_state["w_remote"]      = REMOTE_LABELS[f["remote"]]
    st.session_state["w_maxdays"]     = f["max_days"]
    st.session_state["w_companies"]   = f["companies"]


# ════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
    section[data-testid="stSidebar"] > div:first-child { padding-top: 0.5rem; }
    section[data-testid="stSidebar"] .element-container { margin-bottom: -0.5rem; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.header("🔎 Filters")

    if st.button("♻️ Reset filters"):
        st.session_state["filters"] = default_filters(filters)
        st.session_state["_filters_dirty"] = True
        st.rerun()

    st.text_input(
        "🔍 Keywords (title, skills...)",
        key="w_search",
        placeholder="e.g. data engineering, airflow, python",
    )
    st.slider(
        "⭐ Relevancy score",
        filters["min_score"], max(filters["max_score"], filters["min_score"] + 1),
        key="w_score",
    )
    st.multiselect("🌎 Country", filters["countries"], key="w_countries")
    st.multiselect("🏙️ City", filters["cities"], key="w_cities")
    st.multiselect("🗣️ Offer language", filters["languages"], key="w_languages")
    st.multiselect("📈 Seniority", filters["seniorities"], key="w_seniorities")
    st.multiselect("📄 Contract type", filters["contracts"], key="w_contracts")
    st.multiselect("🏢 Company", ALL_COMPANIES, key="w_companies")
    st.select_slider("📅 Date range", options=filters["day_options"], key="w_maxdays")
    st.radio(
        "🏠 Remote work",
        list(filters["remote_labels"].values()),
        key="w_remote",
        horizontal=True,
    )

# ════════════════════════════════════════════════════════════════════
# Copy widgets -> dict (after rendering, captures manual input)
# ════════════════════════════════════════════════════════════════════
f["companies"]   = st.session_state["w_companies"]
f["search"]      = st.session_state["w_search"]
f["score_range"] = st.session_state["w_score"]
f["contracts"]   = st.session_state["w_contracts"]
f["cities"]      = st.session_state["w_cities"]
f["countries"]   = st.session_state["w_countries"]
f["languages"]   = st.session_state["w_languages"]
f["seniorities"] = st.session_state["w_seniorities"]
f["remote"]      = REMOTE_VALUES[st.session_state["w_remote"]]
f["max_days"]    = st.session_state["w_maxdays"]


# ════════════════════════════════════════════════════════════════════
# Chart / map helpers
# ════════════════════════════════════════════════════════════════════
def group_small_categories(counts: pd.Series, threshold_pct: float = 0.01, other_label: str = "Other") -> pd.Series:
    """Fold categories under `threshold_pct` of the total into a single 'Other' slice."""
    total = counts.sum()
    mask = counts / total < threshold_pct
    if mask.any():
        other_total = counts[mask].sum()
        counts = counts[~mask]
        counts.loc[other_label] = other_total
    return counts


def compute_zoom_for_bounds(lats, lons, padding_factor: float = 1.3) -> float:
    """Empirical zoom level that fits all given points in view."""
    if len(lats) <= 1:
        return 8
    max_range = max(max(lats) - min(lats), max(lons) - min(lons)) * padding_factor
    if max_range == 0:
        return 8
    zoom = 8 - np.log2(max_range + 0.01)
    return max(2, min(zoom, 10))


@st.cache_data
def build_map_groups(d: pd.DataFrame) -> pd.DataFrame | None:
    """Aggregate offers by (lat, lon) into one row per location, with hover text.

    Cached: this groupby + hover construction is the map's heavy step. Isolating it
    means UI-only reruns (opening the chat, toggling a checkbox) don't recompute it —
    only the selection-dependent highlight/opacity is recomputed each run.
    """
    if not {"latitude", "longitude"}.issubset(d.columns):
        return None
    map_df = d.dropna(subset=["latitude", "longitude"]).reset_index()
    if map_df.empty:
        return None

    grouped = (
        map_df.groupby(["latitude", "longitude"])
              .agg(
                  count=("job_id", "count"),
                  job_ids=("job_id", list),
                  titles=("job_title", list),
                  companies=("company_name", list),
                  avg_score=("score_relevancy", "mean"),
              )
              .reset_index()
    )
    grouped["hover_text"] = grouped.apply(
        lambda row: "<br>".join(
            f"• {t} @ {c}" for t, c in zip(row["titles"][:8], row["companies"][:8])
        ) + ("<br>…" if row["count"] > 8 else ""),
        axis=1,
    )
    return grouped


# ════════════════════════════════════════════════════════════════════
# Offers table (mirror-selected with the map via map_selected_job_ids)
# ════════════════════════════════════════════════════════════════════
def render_offers_table(d: pd.DataFrame) -> None:
    header_col1, header_col2, header_col3 = st.columns([3, 1.5, 1])
    with header_col1:
        st.subheader("📋 Offers")
    with header_col2:
        sort_choice = st.selectbox(
            "Sort by", ["Relevancy ↓", "Relevancy ↑", "Company A-Z", "Most recent"],
            key="offers_sort_choice", label_visibility="collapsed",
        )
    with header_col3:
        if st.button("🗑️ Clear selection", key="clear_offers_selection"):
            st.session_state["map_selected_job_ids"] = set()
            st.rerun()

    if d.empty:
        st.info("No offers to display.")
        return

    if "map_selected_job_ids" not in st.session_state:
        st.session_state["map_selected_job_ids"] = set()
    selected_ids = st.session_state["map_selected_job_ids"]

    display_df = d.reset_index()
    if "offer_languages" in display_df.columns:
        display_df["languages"] = display_df["offer_languages"].apply(
            lambda x: ", ".join(l for l in x if isinstance(l, str)).upper() if isinstance(x, list) else ""
        )

    # ── Keywords as a joined string ──
    if "all_keywords" in display_df.columns:
        display_df["keywords_str"] = display_df["all_keywords"].apply(
            lambda x: ", ".join(sorted(set(k for k in x if isinstance(k, str)))) if isinstance(x, list) else ""
        )

    # ── Date: published_at, fallback to collected_at ──
    if "published_at" in display_df.columns:
        published = pd.to_datetime(display_df["published_at"], errors="coerce")
        collected = pd.to_datetime(display_df.get("collected_at"), errors="coerce")

        today = pd.Timestamp.now(tz=published.dt.tz if published.dt.tz else None)
        is_valid = published.notna() & (published >= pd.Timestamp("2015-01-01", tz=published.dt.tz)) & (published <= today)

        display_df["date"] = published.where(is_valid, collected)
        display_df["date"] = display_df["date"].dt.strftime("%Y-%m-%d")
    elif "collected_at" in display_df.columns:
        display_df["date"] = display_df["collected_at"].dt.strftime("%Y-%m-%d")

    if sort_choice == "Relevancy ↓":
        display_df = display_df.sort_values("score_relevancy", ascending=False)
    elif sort_choice == "Relevancy ↑":
        display_df = display_df.sort_values("score_relevancy", ascending=True)
    elif sort_choice == "Company A-Z":
        display_df = display_df.sort_values("company_name", ascending=True)
    elif sort_choice == "Most recent" and "collected_at" in display_df.columns:
        display_df = display_df.sort_values("collected_at", ascending=False)

    # ── FEATURE DÉTAILS : SÉLECTION ──
    display_df["_is_selected"] = display_df["job_id"].isin(selected_ids)

    # Note : Le tri par "_is_selected" a bien été supprimé pour éviter le bug de clic !

    show_cols = [c for c in ["job_title", "company_name", "city", "country_full",
                             "seniority", "languages", "date", "score_relevancy"]
                 if c in display_df.columns]

    display_df.insert(0, "Select", display_df["_is_selected"])

    edited = st.data_editor(
        display_df[["Select", "job_id"] + show_cols],
        hide_index=True,
        width="stretch",
        disabled=show_cols + ["job_id"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Détails", width="small"),
            "job_id": None,
            "job_title": st.column_config.TextColumn("Title", width="large"),
            "company_name": st.column_config.TextColumn("Company", width="small"),
            "city": st.column_config.TextColumn("City", width="medium"),
            "country_full": st.column_config.TextColumn("Country", width="small"),
            "seniority": st.column_config.TextColumn("Level", width="small"),
            "languages": st.column_config.TextColumn("Languages", width="small"),
            "date": st.column_config.TextColumn("Collected", width="small"),
            "score_relevancy": st.column_config.NumberColumn("Relevancy", width="small"),
        },
        key="offers_editor",
    )

    new_selected = set(edited.loc[edited["Select"], "job_id"].tolist())
    if new_selected != selected_ids:
        st.session_state["map_selected_job_ids"] = new_selected
        st.rerun()

    # ── FEATURE DÉTAILS : AFFICHAGE SOUS LE TABLEAU ──
    if new_selected:
        st.markdown("### 💡 Selected Offer Details")
        
        # 1. Fonction pour renvoyer la couleur Streamlit ET l'émoji pour le menu
        def get_score_visuals(score):
            if score >= 7:
                return "green", "🟢"   # Vert pour les scores >= 7
            elif score >= 4:
                return "orange", "🟡"  # Jaune/Orange pour les scores entre 4 et 7
            else:
                return "red", "🔴"     # Rouge pour les scores < 4

        # 2. Préparer le dictionnaire avec la puce de couleur dans le texte
        options_dict = {}
        for job_id in new_selected:
            match = display_df[display_df["job_id"] == job_id]
            if not match.empty:
                selected_job = match.iloc[0]
                title = selected_job.get("job_title", "Offer")
                company = selected_job.get("company_name", "")
                score = selected_job.get("score_relevancy", 0)
                
                _, emoji = get_score_visuals(score)
                
                # On ajoute l'émoji directement dans le libellé du menu déroulant !
                options_dict[job_id] = f"{emoji} [{score}/10] {title} ({company})"
        
        # 3. Menu déroulant pour sélectionner l'offre
        selected_job_id_to_display = st.selectbox(
            "Select an offer to view details:",
            options=list(options_dict.keys()),
            format_func=lambda x: options_dict[x],
            key="details_offer_selector"
        )
        
        # 4. Affichage des détails sous le menu
        if selected_job_id_to_display:
            match = display_df[display_df["job_id"] == selected_job_id_to_display]
            if not match.empty:
                job = match.iloc[0]
                title = job.get("job_title", "Offer")
                company = job.get("company_name", "")
                score = job.get("score_relevancy", 0)
                
                color, _ = get_score_visuals(score)
                
                # Le titre de l'expander garde son formatage couleur Markdown
                expander_title = f"📌 :{color}[**[{score}/10]**] **{title}** ({company})"
                
                with st.expander(expander_title, expanded=True):
                    st.markdown(f"**Explanation:** {job.get('explanation', 'No explanation available.')}")
                    st.markdown(f"**Keywords:** `{job.get('keywords_str', 'None')}`")

# ════════════════════════════════════════════════════════════════════
# Dashboard (metrics + map + charts + company table)
# ════════════════════════════════════════════════════════════════════
def build_dashboard(d: pd.DataFrame, d_filtered_without_company: pd.DataFrame) -> None:
    # ── Metrics ──────────────────────────────────────────────────
    metric_col1, metric_col2 = st.columns(2)
    with metric_col1:
        st.metric("📦 Offers currently displayed", len(d))
    with metric_col2:
        st.metric("🏢 Companies", d["company_name"].nunique())

    # ── Map ──────────────────────────────────────────────────────
    grouped = build_map_groups(d)

    if grouped is None:
        st.info("No geolocated offers to display on the map.")
    else:
        grouped = grouped.copy()

        if "map_selected_job_ids" not in st.session_state:
            st.session_state["map_selected_job_ids"] = set()
        selected_ids_set = st.session_state["map_selected_job_ids"]

        grouped["is_highlighted"] = grouped["job_ids"].apply(
            lambda ids: bool(selected_ids_set & set(ids))
        )

        highlighted_points = grouped[grouped["is_highlighted"]]
        if not highlighted_points.empty:
            lats = highlighted_points["latitude"].tolist()
            lons = highlighted_points["longitude"].tolist()
            map_center = dict(lat=sum(lats) / len(lats), lon=sum(lons) / len(lons))
            map_zoom = compute_zoom_for_bounds(lats, lons)
        else:
            map_center = dict(lat=-25, lon=-60)
            map_zoom = 3

        import plotly.graph_objects as go
        fig_map = go.Figure()

        # ── Base layer: density "glow" — large, semi-transparent circles ──
        fig_map.add_trace(go.Scattermapbox(
            lat=grouped["latitude"], lon=grouped["longitude"],
            mode="markers",
            marker=dict(
                size=grouped["count"].clip(upper=10) * 4 + 10,  # bigger where offers stack
                color=grouped["avg_score"],
                colorscale="RdYlGn",
                cmin=grouped["avg_score"].min(), cmax=grouped["avg_score"].max(),
                showscale=True, colorbar=dict(title="Avg score"),
                opacity=0.35,
            ),
            customdata=list(zip(grouped["job_ids"], grouped["count"])),
            text=grouped["hover_text"],
            hovertemplate="<b>%{customdata[1]} offer(s)</b><br>%{text}<extra></extra>",
            name="density",
        ))

        # ── Overlay: sharp, opaque markers for the current selection ──
        if not highlighted_points.empty:
            fig_map.add_trace(go.Scattermapbox(
                lat=highlighted_points["latitude"], lon=highlighted_points["longitude"],
                mode="markers",
                marker=dict(size=10, color="#2ECC71", opacity=1.0),
                hoverinfo="skip",
                showlegend=False,
                name="selected",
            ))

        fig_map.update_layout(
            mapbox=dict(
                style="carto-darkmatter", pitch=0, bearing=0,
                center=map_center, zoom=map_zoom,
            ),
            margin=dict(l=0, r=0, t=0, b=0),
            dragmode="select",
            selectdirection="any",
            clickmode="event+select",
            uirevision="offers_map",
            showlegend=False,
        )

        event = st.plotly_chart(
            fig_map, width="stretch",
            on_select="rerun", selection_mode="points",
            key="offers_map",
            config={"scrollZoom": True, "displayModeBar": True},
        )

        if event.selection.points:
            clicked_ids = set()
            for pt in event.selection.points:
                # Only trace 0 (density/base layer) carries the real job_ids to click on
                if pt.get("curve_number", 0) == 0:
                    clicked_ids.update(grouped.iloc[pt["point_index"]]["job_ids"])
            if clicked_ids and clicked_ids != st.session_state["map_selected_job_ids"]:
                st.session_state["map_selected_job_ids"] = clicked_ids
                st.rerun()
        else:
            st.caption("💡 Drag a small box around one or more points to select them.")

    # ── Offers table (mirrors the map selection) ─────────────────
    render_offers_table(d)

    # ── Country pie + language bar ───────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        country_counts = group_small_categories(d["country_full"].value_counts()).reset_index()
        country_counts.columns = ["country", "count"]
        st.plotly_chart(
            px.pie(country_counts, names="country", values="count", title="Offers by country"),
            width="stretch",
        )
    with col2:
        # Bar chart, not pie: an offer can have several languages, so pie % wouldn't sum to 100%.
        lang_counts = d["offer_languages_full"].dropna().explode().dropna()
        lang_counts = lang_counts[
            ~lang_counts.astype(str).str.strip().str.lower().isin(["none", "nan", ""])
        ]
        lang_counts = group_small_categories(lang_counts.value_counts()).reset_index()
        lang_counts.columns = ["language", "count"]
        st.plotly_chart(
            px.bar(lang_counts, x="language", y="count",
                   title="Offers by language (an offer can have several)"),
            width="stretch",
        )

    # ── Seniority pie + top skills bar ───────────────────────────
    col3, col4 = st.columns(2)
    with col3:
        seniority_counts = d["seniority"].value_counts().reset_index()
        seniority_counts.columns = ["seniority", "count"]
        st.plotly_chart(
            px.pie(seniority_counts, names="seniority", values="count", title="Offers by seniority"),
            width="stretch",
        )
    with col4:
        st.markdown("**🛠️ Top required skills & frameworks**")
        KEYWORD_CATEGORIES = {
            "Language": "skills_languages",
            "Framework": "skills_frameworks",
            "Aptitude": "skills_aptitudes",
            "Soft skill": "skills_soft",
        }
        records = []
        for label, col in KEYWORD_CATEGORIES.items():
            if col in d.columns:
                exploded = d[col].dropna().explode().dropna()
                exploded = exploded[exploded.apply(lambda x: isinstance(x, str))]
                exploded = exploded[exploded.str.strip() != ""]
                for kw in exploded:
                    records.append({"keyword": kw.strip().lower(), "category": label})

        kw_df = pd.DataFrame(records)
        if not kw_df.empty:
            top_kw = (
                kw_df.groupby(["keyword", "category"])
                     .size().reset_index(name="count")
                     .sort_values("count", ascending=False)
                     .head(15)
            )
            fig_kw = px.bar(
                top_kw, x="count", y="keyword", orientation="h",
                color="category", title="Top 15 required skills/keywords",
            )
            fig_kw.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig_kw, width="stretch")
        else:
            st.info("No keywords found in the filtered offers.")

    # ── Company poster table (checkbox-selectable, mirrors f["companies"]) ──
    st.markdown("**🏆 Job posters companies**")

    # Built from data filtered by everything EXCEPT company, so checking one
    # company doesn't make the others disappear from the list.
    d_base = d_filtered_without_company
    d_with_site = d_base[d_base["website"].notna() & (d_base["website"] != "")]

    company_count = d_with_site["company_name"].value_counts().reset_index()
    company_count.columns = ["company_name", "nb_offers"]
    company_info = (
        d_with_site.groupby("company_name")
        .agg({
            "website": "first",
            "city": lambda x: ", ".join(sorted(set(x.dropna()))),
            "country_full": lambda x: ", ".join(sorted(set(x.dropna()))),
        })
        .reset_index()
    )

    all_companies = (
        company_count.merge(company_info, on="company_name", how="left")
        .sort_values("nb_offers", ascending=False)
        .rename(columns={
            "company_name": "Company", "city": "City",
            "country_full": "Countries", "website": "Website", "nb_offers": "Offers",
        })
    )
    all_companies.insert(0, "Select", all_companies["Company"].isin(f["companies"]))

    edited = st.data_editor(
        all_companies[["Select", "Company", "Website", "Offers", "City", "Countries"]],
        hide_index=True,
        width="stretch",
        height=350,
        disabled=["Company", "Website", "Offers", "City", "Countries"],
        column_config={
            "Select": st.column_config.CheckboxColumn("", width="small"),
            "Company": st.column_config.TextColumn("Company"),
            "Website": st.column_config.LinkColumn(
                "Website", display_text=r"https?://(?:www\.)?([^/]+)", width="small",
            ),
            "Offers": st.column_config.NumberColumn("Offers", width="small"),
            "City": st.column_config.TextColumn("City"),
        },
        key="company_editor",
    )

    newly_selected = edited.loc[edited["Select"], "Company"].tolist()
    if set(newly_selected) != set(f["companies"]):
        st.session_state["filters"]["companies"] = newly_selected
        st.session_state["_filters_dirty"] = True
        st.rerun()


# ════════════════════════════════════════════════════════════════════
# Apply filters and render the dashboard
# ════════════════════════════════════════════════════════════════════
filtered_df = apply_filters(df, f, dict_reversed_index, city_country_map)

# Same filters minus "companies" — feeds the company poster table so the full
# company list stays visible regardless of which companies are checked.
filters_without_company = dict(f)
filters_without_company["companies"] = []
d_filtered_without_company = apply_filters(df, filters_without_company, dict_reversed_index, city_country_map)

st.subheader("📊 Dashboard")
build_dashboard(filtered_df, d_filtered_without_company)
st.caption(
    f"**{len(filtered_df)}** offers match the filters (out of {len(df)}) — "
    f"**{filtered_df['company_name'].nunique()}** companies (out of {df['company_name'].nunique()})."
)


# ════════════════════════════════════════════════════════════════════
# 💬 Chatbot — floating bar pinned bottom-right
# ════════════════════════════════════════════════════════════════════
if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "chat_open" not in st.session_state:
    st.session_state["chat_open"] = False

# ── Floating widget CSS (targets anchor divs to scope the styling) ──
st.markdown("""
<style>
    /* Toggle button */
    div[data-testid="stVerticalBlock"]:has(> div.element-container .btn-anchor) {
        position: fixed !important;
        bottom: 90px !important; right: 30px !important;
        width: auto !important; z-index: 99999 !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div.element-container .btn-anchor) button {
        border-radius: 50% !important;
        width: 45px !important; height: 45px !important;
        background-color: #262730 !important; color: white !important;
        border: 2px solid #4a4b55 !important;
        font-size: 18px !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.4) !important;
        padding: 0 !important;
    }
    div[data-testid="stVerticalBlock"]:has(> div.element-container .btn-anchor) button:hover {
        background-color: #3a3b45 !important;
        border-color: #ff4b4b !important; color: #ff4b4b !important;
    }
    /* Chat history panel */
    div[data-testid="stVerticalBlock"]:has(> div.element-container .chat-anchor) {
        position: fixed !important;
        bottom: 145px !important; right: 30px !important;
        width: 350px !important; max-height: 400px !important;
        overflow-y: auto !important;
        background-color: #0e1117 !important;
        border: 1px solid #4a4b55 !important; border-radius: 12px !important;
        padding: 15px !important; z-index: 99998 !important;
        box-shadow: 0px 10px 20px rgba(0,0,0,0.6) !important;
        display: flex !important; flex-direction: column !important;
    }
</style>
""", unsafe_allow_html=True)

# ── History panel (floating, only when open) ──
if st.session_state["chat_open"]:
    with st.container():
        st.markdown('<div class="chat-anchor"></div>', unsafe_allow_html=True)
        for role, content in st.session_state["chat_history"]:
            with st.chat_message(role):
                st.markdown(content)

# ── Toggle button (floating) ──
with st.container():
    st.markdown('<div class="btn-anchor"></div>', unsafe_allow_html=True)
    arrow_label = "✖" if st.session_state["chat_open"] else "💬"
    if st.button(arrow_label, key="chat_toggle"):
        st.session_state["chat_open"] = not st.session_state["chat_open"]
        st.rerun()

# ── Input bar (native, always visible bottom of page) ──
prompt = st.chat_input("Ask me anything...")

# ── Force le retour en haut de page ──
# st.chat_input pousse Streamlit à auto-scroller vers le bas après le rendu ;
# on corrige pendant 1.5s juste après (le temps que ce comportement se déclenche).
st.html(f"""
<script>
    (function() {{
        let tries = 0;
        const forceTop = setInterval(() => {{
            window.scrollTo(0, 0);
            tries++;
            if (tries > 15) clearInterval(forceTop);
        }}, 100);
    }})();
</script>
<!-- run:{time.time()} -->
""", unsafe_allow_javascript=True)

if prompt and prompt.strip():
    st.session_state["chat_open"] = True
    st.session_state["chat_history"].append(("user", prompt))

    with st.spinner("Thinking..."):
        criteria = extract_filters(prompt, get_llm())
        new_filters = criteria_to_filter_dict(criteria, st.session_state["filters"])
        st.session_state["filters"] = new_filters
        st.session_state["_filters_dirty"] = True

    st.session_state["chat_history"].append(("assistant", summarize_criteria(criteria)))
    st.rerun()