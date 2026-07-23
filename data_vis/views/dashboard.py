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
import uuid
import importlib.util
from collections import defaultdict
from pathlib import Path
import plotly.graph_objects as go
import plotly.colors as pc
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from rapidfuzz import process, fuzz
import country_converter as coco
import pycountry
from langchain_groq import ChatGroq
sys.path.append(os.path.join(os.path.dirname(__file__), "../agent/"))
sys.path.append(os.path.join(os.path.dirname(__file__), "../../ingestion/python/src"))

from dashboard_agent import DashboardAgent
from LLMprovider import LLM
from agent_tools import build_agent_tools

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

from data_vis.agent.filters_agent import (
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
def get_llm_provider() -> LLM:
    return LLM(mistral_key=st.secrets["mistral"]["api_key"])

@st.cache_resource
def get_llm():
    llm = get_llm_provider()
    return llm.smart



# ════════════════════════════════════════════════════════════════════
# Data loading (cached — one round-trip to Neon, refreshed on TTL)
# ════════════════════════════════════════════════════════════════════
@st.cache_data(show_spinner="Fetching real data from database...")
def get_data_fingerprint() -> str:
    """Cheap query to detect if serving.job_offer has actually changed."""
    db = get_db_connection()
    result = db.execute("SELECT MAX(collected_at)::text AS max_date, COUNT(*) AS nb_rows FROM serving.job_offer;")
    row = result[0] if result else {}
    return f"{row.get('max_date')}_{row.get('nb_rows')}"


@st.cache_data(show_spinner="Fetching real data from database...")
def load_real_offers(fingerprint: str) -> list:
    """Fetch enriched offers from the Gold serving view.
    Cached per fingerprint — refetches automatically when the underlying view changes,
    instead of relying on a blind time-based TTL."""
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
def load_and_transform_dataframe(fingerprint: str) -> tuple[pd.DataFrame, dict]:
    """Load raw offers, clean, enrich (country/language full names, keyword blob),
    and build the reverse index. Everything downstream reads from this cached result."""
    fingerprint = get_data_fingerprint()
    df = pd.DataFrame(load_real_offers(fingerprint))
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


@st.cache_data(hash_funcs={pd.DataFrame: lambda _: None})
def build_city_country_map(df: pd.DataFrame) -> dict:
    """Map each city to its full country name.
    Prevents e.g. 'Santiago del Estero' (Argentina) from matching a 'Santiago' (Chile) filter."""
    mapping = {}
    for _, row in df.dropna(subset=["city", "country"]).iterrows():
        mapping[row["city"]] = row["country_full"]
    return mapping


@st.cache_data(hash_funcs={pd.DataFrame: lambda _: None})
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
        "day_options": [1, 3, 7, 14, 30, 60, 90, "All time"],
    }



# ════════════════════════════════════════════════════════════════════
# Load data & derive shared constants
# ════════════════════════════════════════════════════════════════════
fingerprint = get_data_fingerprint()
df, dict_reversed_index = load_and_transform_dataframe(fingerprint)
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
    # Uses published_at when valid, falls back to collected_at otherwise.
    if f["max_days"] != "All time":
        column_tz = out["collected_at"].dt.tz if "collected_at" in out.columns else None
        today = pd.Timestamp.now(tz=column_tz)
        min_valid_date = pd.Timestamp("2015-01-01", tz=column_tz)

        if "published_at" in out.columns:
            published = pd.to_datetime(out["published_at"], errors="coerce")
            is_published_valid = published.notna() & (published >= min_valid_date) & (published <= today)
        else:
            published = pd.Series(pd.NaT, index=out.index)
            is_published_valid = pd.Series(False, index=out.index)

        collected = out["collected_at"] if "collected_at" in out.columns else pd.Series(pd.NaT, index=out.index)
        effective_date = published.where(is_published_valid, collected)

        cutoff = today - pd.Timedelta(days=f["max_days"])
        out = out[effective_date >= cutoff]

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
    st.caption('Older offers can be less precise due to workflow updates')

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

def _score_to_rgb(score, vmin, vmax):
    t = 0.5 if vmax == vmin else max(0, min(1, (score - vmin) / (vmax - vmin)))
    return pc.sample_colorscale("RdYlGn", [t])[0]  # ex: "rgb(200,50,30)"


def _blend_grey(rgb_str, weight=0.25):
    """weight=0 -> pure grey, weight=1 -> original color untouched."""
    r, g, b = pc.unlabel_rgb(rgb_str)
    return f"rgb({r*weight + 128*(1-weight):.0f},{g*weight + 128*(1-weight):.0f},{b*weight + 128*(1-weight):.0f})"



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
    if "map_selected_job_ids" not in st.session_state:
        st.session_state["map_selected_job_ids"] = set()
    selected_ids = st.session_state["map_selected_job_ids"]
    
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
            # On vide aussi le cache du tableau lors du clear
            if "offers_editor" in st.session_state:
                del st.session_state["offers_editor"]
            st.rerun()

    if selected_ids:
        st.info(f"📍 Charts below reflect your **{len(selected_ids)} selected offer(s)**, not the full filtered set.")

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

    # ── FEATURE SÉLECTION & TRI EN HAUT RÉACTIVÉ ──
    display_df["_is_selected"] = display_df["job_id"].isin(selected_ids)
    display_df = display_df.sort_values("_is_selected", ascending=False, kind="stable")

    show_cols = [c for c in ["job_title", "company_name", "city", "country_full",
                             "seniority", "languages", "date", "score_relevancy"]
                 if c in display_df.columns]

    display_df.insert(0, "Select", display_df["_is_selected"])

    # ── NOUVEAU : MARQUAGE VISUEL DE L'OFFRE INSPECTÉE DANS LE TABLEAU ──
    # On crée une copie temporaire pour l'affichage du tableau
    table_to_edit = display_df[["Select", "job_id"] + show_cols].copy()
    
    # On récupère l'ID de l'offre actuellement choisie dans le menu déroulant du bas
    active_job_id = st.session_state.get("details_offer_selector")
    
    if active_job_id and "job_title" in table_to_edit.columns:
        # On ajoute un pointeur bien visible (👉 🔍) devant le titre du poste actif !
        table_to_edit["job_title"] = table_to_edit.apply(
            lambda r: f"👉 🔍 {r['job_title']}" if r["job_id"] == active_job_id else r["job_title"],
            axis=1
        )

    # On passe table_to_edit (et non plus display_df) au data_editor
    edited = st.data_editor(
        table_to_edit,
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
        if "offers_editor" in st.session_state:
            del st.session_state["offers_editor"]
        st.rerun()

    # ── FEATURE DÉTAILS : AFFICHAGE SOUS LE TABLEAU ──
    if new_selected:
        st.markdown("### 💡 Selected Offer Details")
        
        def get_score_visuals(score):
            if score >= 7:
                return "green", "🟢"
            elif score >= 4:
                return "orange", "🟡"
            else:
                return "red", "🔴"

        options_dict = {}
        for job_id in new_selected:
            match = display_df[display_df["job_id"] == job_id]
            if not match.empty:
                selected_job = match.iloc[0]
                title = selected_job.get("job_title", "Offer")
                company = selected_job.get("company_name", "")
                score = selected_job.get("score_relevancy", 0)
                
                _, emoji = get_score_visuals(score)
                options_dict[job_id] = f"{emoji} [{score}/10] {title} ({company})"
        
        selected_job_id_to_display = st.selectbox(
            "Select an offer to view details:",
            options=list(options_dict.keys()),
            format_func=lambda x: options_dict[x],
            key="details_offer_selector"
        )
        
        if selected_job_id_to_display:
            match = display_df[display_df["job_id"] == selected_job_id_to_display]
            if not match.empty:
                job = match.iloc[0]
                title = job.get("job_title", "Offer")
                company = job.get("company_name", "")
                score = job.get("score_relevancy", 0)
                
                color, _ = get_score_visuals(score)
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

    # ── If a map/table selection is active, restrict all analysis
    # (charts, skills, company list) to that subset. The offers TABLE
    # itself keeps showing everything, so the user can still see and
    # adjust the selection. ──
    if "map_selected_job_ids" not in st.session_state:
        st.session_state["map_selected_job_ids"] = set()
    selected_ids = st.session_state["map_selected_job_ids"]

    if selected_ids:
        d_analysis = d[d.index.isin(selected_ids)]
        d_company_base = d_filtered_without_company[d_filtered_without_company.index.isin(selected_ids)]
    else:
        d_analysis = d
        d_company_base = d_filtered_without_company

    # ── Map ──────────────────────────────────────────────────────
    grouped = build_map_groups(d)

    if grouped is None:
        st.info("No geolocated offers to display on the map.")
        grouped = pd.DataFrame(columns=["latitude", "longitude", "count", "job_ids",
                                        "titles", "companies", "avg_score", "hover_text"])

    grouped = grouped.copy()
    selected_ids_set = st.session_state["map_selected_job_ids"]

    if not grouped.empty:
        grouped["is_highlighted"] = grouped["job_ids"].apply(
            lambda ids: bool(selected_ids_set & set(ids))
        )
    else:
        grouped["is_highlighted"] = pd.Series(dtype=bool)

    highlighted_points = grouped[grouped["is_highlighted"]]

    # ── Map center/zoom: remember the last known position instead of
    # resetting to the default view whenever there's no active selection ──
    if not highlighted_points.empty:
        lats = highlighted_points["latitude"].tolist()
        lons = highlighted_points["longitude"].tolist()
        map_center = dict(lat=sum(lats) / len(lats), lon=sum(lons) / len(lons))
        map_zoom = compute_zoom_for_bounds(lats, lons)
        st.session_state["last_map_center"] = map_center
        st.session_state["last_map_zoom"] = map_zoom
    else:
        map_center = st.session_state.get("last_map_center", dict(lat=-25, lon=-60))
        map_zoom = st.session_state.get("last_map_zoom", 3)

    # ── Base layer: density "glow" — large, semi-transparent circles ──
    vmin = grouped["avg_score"].min() if not grouped.empty else 0
    vmax = grouped["avg_score"].max() if not grouped.empty else 10

    fig_map = go.Figure()

    if highlighted_points.empty:
        # No selection: keep the normal color-scaled behavior, colorbar included.
        base_color = grouped["avg_score"]
        base_colorscale = "RdYlGn"
        base_showscale = True
        base_opacity = 0.35
    else:
        # A selection is active: grey out + fade everything NOT selected.
        grouped["_rgb"] = grouped["avg_score"].apply(lambda s: _score_to_rgb(s, vmin, vmax))
        grouped["_final_color"] = grouped.apply(
            lambda row: row["_rgb"] if row["is_highlighted"] else _blend_grey(row["_rgb"], weight=0.5),
            axis=1,
        )
        base_color = grouped["_final_color"]
        base_colorscale = None
        base_showscale = False
        base_opacity = grouped["is_highlighted"].map({True: 1.0, False: 0.45})

    if not grouped.empty:
        fig_map.add_trace(go.Scattermapbox(
            lat=grouped["latitude"], lon=grouped["longitude"],
            mode="markers",
            marker=dict(
                size=grouped["count"].clip(upper=10) * 4 + 10,
                color=base_color,
                colorscale=base_colorscale,
                cmin=vmin, cmax=vmax,
                showscale=base_showscale,
                colorbar=dict(title="Avg score") if base_showscale else None,
                opacity=base_opacity,
            ),
            customdata=list(zip(grouped["job_ids"], grouped["count"])),
            text=grouped["hover_text"],
            hovertemplate="<b>%{customdata[1]} offer(s)</b><br>%{text}<extra></extra>",
            name="density",
        ))

        # ── Overlay: sharp, opaque markers for the current selection — SAME color scale as base ──
        if not highlighted_points.empty:
            fig_map.add_trace(go.Scattermapbox(
                lat=highlighted_points["latitude"], lon=highlighted_points["longitude"],
                mode="markers",
                marker=dict(
                    size=10,
                    color=highlighted_points["avg_score"],
                    colorscale="RdYlGn",
                    cmin=vmin, cmax=vmax,
                    showscale=False,
                    opacity=1.0,
                ),
                hoverinfo="skip",
                showlegend=False,
                name="selected",
            ))
    else:
        # Invisible anchor trace: forces Plotly to render a mapbox map
        # (not a generic cartesian chart) even with zero offers.
        fig_map.add_trace(go.Scattermapbox(
            lat=[map_center["lat"]], lon=[map_center["lon"]],
            mode="markers",
            marker=dict(size=0, opacity=0),
            hoverinfo="skip",
            showlegend=False,
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

    if event.selection.points and not grouped.empty:
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
        country_counts = group_small_categories(d_analysis["country_full"].value_counts()).reset_index()
        country_counts.columns = ["country", "count"]
        st.plotly_chart(
            px.pie(country_counts, names="country", values="count", title="Offers by country"),
            width="stretch",
        )
    with col2:
        lang_counts = d_analysis["offer_languages_full"].dropna().explode().dropna()
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
        seniority_counts = d_analysis["seniority"].value_counts().reset_index()
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
            if col in d_analysis.columns:
                exploded = d_analysis[col].dropna().explode().dropna()
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
    d_base = d_company_base

    company_count = d_base["company_name"].value_counts().reset_index()
    company_count.columns = ["company_name", "nb_offers"]
    company_info = (
        d_base.groupby("company_name")
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

    visible_companies = set(all_companies["Company"])
    checked_in_table = set(edited.loc[edited["Select"], "Company"].tolist())
    unchecked_in_table = visible_companies - checked_in_table  # décochées explicitement par l'utilisateur

    # Nouvelle liste = ce qui était déjà sélectionné, moins ce qui vient d'être décoché,
    # peu importe si d'autres entreprises sélectionnées ailleurs ne sont pas visibles ici.
    current_selection = set(f["companies"])
    new_selection = (current_selection - unchecked_in_table) | checked_in_table

    if new_selection != current_selection:
        st.session_state["filters"]["companies"] = list(new_selection)
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
#  LLM Function
# ════════════════════════════════════════════════════════════════════
def summarize_dataframe_for_llm(d: pd.DataFrame) -> str:
    """Build a lightweight text summary of the currently filtered offers,
    meant to be returned to the LLM after it applies filters — gives it
    just enough context to comment intelligently, without ever passing
    the raw DataFrame."""
    if d.empty:
        return "No offers match the current filters."

    nb_offers = len(d)
    nb_companies = d["company_name"].nunique()
    avg_score = d["score_relevancy"].mean()

    top_countries = d["country_full"].value_counts().head(3)
    countries_str = ", ".join(f"{c} ({n})" for c, n in top_countries.items())

    top_cities = d["city"].value_counts().head(3)
    cities_str = ", ".join(f"{c} ({n})" for c, n in top_cities.items())

    seniority_counts = d["seniority"].value_counts()
    seniority_str = ", ".join(f"{s} ({n})" for s, n in seniority_counts.items())

    remote_count = int(d["is_remote"].sum())
    onsite_count = nb_offers - remote_count

    top_companies = d["company_name"].value_counts().head(5)
    companies_str = ", ".join(f"{c} ({n})" for c, n in top_companies.items())

    return (
        f"{nb_offers} offers currently match, from {nb_companies} companies. "
        f"Average relevancy score: {avg_score:.1f}/10. "
        f"Top countries: {countries_str}. "
        f"Top cities: {cities_str}. "
        f"Seniority breakdown: {seniority_str}. "
        f"Remote: {remote_count}, on-site: {onsite_count}. "
        f"Top companies posting: {companies_str}."
    )

def get_current_filters():
    return st.session_state["filters"]

def on_filter_applied(filtered_df, new_filters):
    st.session_state["filters"] = new_filters
    st.session_state["_filters_dirty"] = True

def get_df_schema_context(df) -> str:
    """Short schema description injected into the agent's system prompt,
    so it knows what fields exist without ever seeing the DataFrame itself."""
    cols = ", ".join(df.columns.tolist())
    return f"The offers dataset has these columns available: {cols}."

# ════════════════════════════════════════════════════════════════════
# 💬 Chatbot — floating bar pinned bottom-right
# ════════════════════════════════════════════════════════════════════
# Session for prompt caching
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())

# Tools for LLM
tools = build_agent_tools(
    df, dict_reversed_index, city_country_map,
    get_current_filters, on_filter_applied,
    apply_filters,               
    summarize_dataframe_for_llm,
    get_llm_provider(),
    session_id=st.session_state["session_id"],
)

# LLM
agent = DashboardAgent(
    llm=get_llm(), tools=tools, max_iterations=4,
    session_id=st.session_state["session_id"],
)                  

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "chat_open" not in st.session_state:
    st.session_state["chat_open"] = False
if "agent_history" not in st.session_state:
    st.session_state["agent_history"] = []

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
# ── Scroll le panneau de chat (pas la page) vers son propre bas ──
st.html(f"""
<script>
    (function() {{
        let tries = 0;
        const scrollChatToBottom = setInterval(() => {{
            const panels = document.querySelectorAll('div[data-testid="stVerticalBlock"]');
            for (const panel of panels) {{
                if (panel.querySelector('.chat-anchor')) {{
                    panel.scrollTop = panel.scrollHeight;
                }}
            }}
            tries++;
            if (tries > 15) clearInterval(scrollChatToBottom);
        }}, 100);
    }})();
</script>
<!-- run:{time.time()} -->
""", unsafe_allow_javascript=True)


if prompt and prompt.strip():
    st.session_state["chat_open"] = True
    st.session_state["chat_history"].append(("user", prompt))

    with st.spinner("Thinking..."):
        response_text, updated_history = agent(prompt, st.session_state["agent_history"])
        st.session_state["agent_history"] = updated_history

    st.session_state["chat_history"].append(("assistant", response_text))
    st.rerun()

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []


