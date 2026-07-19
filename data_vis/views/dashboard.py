import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px          
# from fake_offer import fake_job_offers
from collections import defaultdict
import time
import os
import sys
from rapidfuzz import process, fuzz
import country_converter as coco
import pydeck as pdk
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
import pycountry
import re
import json
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[4]
# 1. Récupère le chemin absolu du dossier 'python' (parent commun)
# __file__ est dans user_interface/, son parent ('..') est python/
dossier_parent = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))

# 2. Construit les chemins vers les dossiers contenant vos modules
# Note : 'database' est généralement dans 'user_interface' ou à la racine de 'python'
dossier_agent = os.path.join(dossier_parent, "LangGraph_Agent")
dossier_src = os.path.join(dossier_parent, "src")
dossier_ui = os.path.join(dossier_parent, "user_interface")

# 3. Ajoute les dossiers au système de recherche de Python s'ils n'y sont pas
for dossier in [dossier_parent, dossier_agent, dossier_src, dossier_ui]:
    if dossier not in sys.path:
        sys.path.append(dossier)

# 4. Importations des modules locaux
import importlib.util
from pathlib import Path

_db_path = Path(__file__).resolve().parents[2] / "ingestion" / "python" / "src" / "database.py"
_spec = importlib.util.spec_from_file_location("db_module", _db_path)
_db_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_db_module)
Database = _db_module.Database
import sys
import os
from dashboard_agent import (
    extract_filters,
    criteria_to_filter_dict,
    summarize_criteria,
)
import dashboard_agent
# st.caption(f"agent loaded from: {dashboard_agent.__file__}")


st.set_page_config(page_title="AI Job Offer Dashboard Latam", page_icon="🏙️", layout="wide")
st.title("🏙️ AI Powered pipeline Job offers LATAM")

# Force scroll to the top of the pages
st.markdown("""
    <script>
        window.scrollTo(0, 0);
    </script>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════════
# Ressources & cache (LLM, Database, Data)
# ══════════════════════════════════════════════════════════════════
# # 1. Connexion persistante (Resource)
@st.cache_resource
def get_db_connection():
    # Retourne ton objet Database
    return Database(**st.secrets["database"])

@st.cache_resource
def get_llm():
    # Client Groq direct — indépendant de silver_enrichment / Ollama
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=st.secrets["groq"]["api_key"],
        temperature=0,
    )

@st.cache_data(ttl=600, show_spinner="Fetching real data from database...")
def load_real_offers():
    # Connects automatically using [connections.postgresql] from secrets.toml
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
    db.execute('SELECT serving.refresh_job_offer_if_stale();')
    return db.execute(query)



# Accelerate research by keywords
def generate_reverse_index(df) -> dict:
    index = defaultdict(set)
    
    for idx, row in df.iterrows():
        # 1. Nettoyage : Récupère la liste, normalise chaque mot, supprime les doublons
        keywords = row.get('all_keywords', [])
        if not isinstance(keywords, list): continue
            
        mots_uniques = {kw.lower().strip() for kw in keywords if isinstance(kw, str)}
        
        # 2. Indexation : Ajoute l'index de l'offre à chaque mot-clé
        for kw in mots_uniques:
            index[kw].add(idx)
            
    # Convertit les sets en listes pour une manipulation facilitée
    return {k: list(v) for k, v in index.items()}


_LANG_CACHE = {}


def convert_language_list(liste_codes):
    if not isinstance(liste_codes, list):
        return []
    
    noms = []
    for code in liste_codes:
        c = str(code).strip().lower()
        if not c:  # ignore les valeurs vides
            continue
        if c in _LANG_CACHE:
            noms.append(_LANG_CACHE[c])
            continue
        lang = pycountry.languages.get(alpha_2=c) or pycountry.languages.get(alpha_3=c)
        nom = lang.name if lang else c
        _LANG_CACHE[c] = nom
        noms.append(nom)
    return noms

@st.cache_data
def load_and_transform_dataframe() -> list:
    df = pd.DataFrame(load_real_offers())
    df.set_index('job_id', inplace=True)
    df["is_remote"] = df["is_remote"].fillna(False)
    df["country"] = df["country"].fillna("Not specified")
    df["company_name"] = df["company_name"].fillna("unknown")

    if "collected_at" in df.columns:
        df["collected_at"] = pd.to_datetime(df["collected_at"])

    # ── FULL COUNTRY NAME ──
    cc = coco.CountryConverter()

    # ── Only convert non NaN ──
    mask = df['country'].notna()
    mask_language = df['offer_languages'].notna()

    # ── Apply conversion ──
    df.loc[mask, 'country_full'] = cc.convert(
    df.loc[mask, 'country'].tolist(), 
    to='name_short'
    )
    # ── Fill NaN with Nan ──
    df['country_full'] = df['country_full'].replace('not found', np.nan)
    df.loc[mask_language, 'offer_languages_full'] = df.loc[mask_language, 'offer_languages'].apply(convert_language_list)

    # ── Construit all_keywords en Python, à partir des colonnes séparées ──
    KEYWORD_COLS = ["skills_languages", "skills_frameworks", "skills_aptitudes",
                     "skills_soft", "alternative_job_titles"]

    def _combine_keywords(row):
        combined = []
        for col in KEYWORD_COLS:
            val = row.get(col)
            if isinstance(val, list):
                combined.extend(val)
        return combined

    df["all_keywords"] = df.apply(_combine_keywords, axis=1)

    dict_reversed_index = generate_reverse_index(df)
    return df, dict_reversed_index


@st.cache_data
def build_city_country_map(df: pd.DataFrame) -> dict:
    """
    Associate each city with his country
    Santiago del Estero is a city in argentina, filtering on the city Santiago shouldn't makes it apppear
    """
    mapping = {}
    for _, row in df.dropna(subset=["city", "country"]).iterrows():
        mapping[row["city"]] = row["country_full"]
    return mapping



@st.cache_data
def get_filter_options(df, dict_reversed_index):
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
        "countries": sorted(df["country_full"].dropna().unique().tolist()), # Utilise la version "Full"
        "languages": sorted(set(lang for sub in df["offer_languages_full"].dropna() for lang in sub)),
        "remote_labels": {None: "All", True: "Remote", False: "On-site"},
        "day_options": [7, 14, 30, 60, 90, "All time"]
    }

df, dict_reversed_index = load_and_transform_dataframe()
filters = get_filter_options(df, dict_reversed_index)
city_country_map = build_city_country_map(df)

# Mapping for the "Remote" radio (None = no filter)
REMOTE_LABELS = filters["remote_labels"]
REMOTE_VALUES = {v: k for k, v in REMOTE_LABELS.items()}

# ══════════════════════════════════════════════════════════════════
# Lists for widgets
# ══════════════════════════════════════════════════════════════════
SEARCH_COLUMNS = ["all_keywords"]
ALL_COMPANIES = sorted(df["company_name"].dropna().unique().tolist())


# ___ Map highlight ___
if "highlighted_job_id" not in st.session_state:
    st.session_state["highlighted_job_id"] = None

# ══════════════════════════════════════════════════════════════════
# Filtering logic
# ══════════════════════════════════════════════════════════════════
def get_fuzzy_matching_ids(user_input, dict_reversed_index, threshold=55):
    matches = process.extract(user_input, dict_reversed_index.keys(), scorer=fuzz.WRatio, limit=5)
    
    # 2. Récupération des IDs pour les clés trouvées
    matching_ids = set()
    for word, score, index_in_dict in matches:
        if score >= threshold:
            matching_ids.update(dict_reversed_index.get(word, []))
            
    return matching_ids

def apply_filters(df: pd.DataFrame, f: dict, dict_reversed_index: dict, city_country_map: dict) -> pd.DataFrame:
    out = df.copy()

    # Keywords 
    if f["search"]:
        search_words = f["search"].lower().split()
        match_counts = {}
        final_ids = set()
        for word in search_words:
            # On cherche les correspondances floues dans les clés de l'index
            word_ids = get_fuzzy_matching_ids(word, dict_reversed_index)
            for idx in word_ids:
                match_counts[idx] = match_counts.get(idx, 0) + 1
        if match_counts:
            matched_ids = list(match_counts.keys())
            out = out.loc[out.index.isin(matched_ids)].copy()
            out['_keyword_match_count'] = out.index.map(match_counts)
            out = out.sort_values('_keyword_match_count', ascending=False)
        else:
            return out.iloc[0:0]
            

    lo, hi = f["score_range"]
    out = out[(out["score_relevancy"] >= lo) & (out["score_relevancy"] <= hi)]

    if f["contracts"]:
        out = out[out["contract_type"].isin(f["contracts"])]

    if f["cities"]:
        # reverse_geocoder → stable, contains suffit
        pattern = "|".join(re.escape(c) for c in f["cities"])
        out = out[out["city"].str.contains(pattern, case=False, na=False)]

        # Deduct country from the city
        inferred_countries = {city_country_map[c] for c in f["cities"] if c in city_country_map}
        if inferred_countries and not f["countries"]:
            # apply deduced country
            out = out[out["country_full"].isin(inferred_countries)]

    if f["countries"]:
        # reverse_geocoder → stable, contains suffit
        pattern = "|".join(re.escape(c) for c in f["countries"])
        out = out[out["country_full"].str.contains(pattern, case=False, na=False)]

    if f["languages"]:
        # codes ISO normalisés en amont → comparaison exacte suffit
        out = out[out["offer_languages_full"].apply(lambda langs: any(l in langs for l in f["languages"]) if langs else False)]

    if f["seniorities"]:
        # valeurs contraintes par Literal dans le schéma Pydantic → comparaison exacte suffit
        out = out[out["seniority"].isin(f["seniorities"])]

    if f.get("companies"):
        # extrait par LLM → risque de variation, contains plus robuste qu'isin
        pattern = "|".join(re.escape(c) for c in f["companies"])
        out = out[out["company_name"].str.contains(pattern, case=False, na=False)]

    if f["remote"] is not None:
        # booléen strict → comparaison exacte
        out = out[out["is_remote"] == f["remote"]]

    # "All time" = no date filter
    if f["max_days"] != "All time" and "collected_at" in out.columns:
        # Extract the timezone from the column (returns None if naive, or the tz if aware)
        column_tz = out["collected_at"].dt.tz
        
        # Inject that timezone into the current timestamp
        cutoff = pd.Timestamp.now(tz=column_tz) - pd.Timedelta(days=f["max_days"])
        out = out[out["collected_at"] >= cutoff]

    return out


# ══════════════════════════════════════════════════════════════════
# Default filters — source of truth: st.session_state["filters"]
# ══════════════════════════════════════════════════════════════════
def default_filters(options: dict) -> dict:
    return {
        "search":      "",
        "score_range": (max(0, options.get("min_score", 0)), min(10, options.get("max_score", 10))),
        "contracts":   list(options['contracts']),
        "cities":      [],
        "countries":   [],
        "languages":   [],
        "seniorities": list(options['seniorities']),   # all checked by default (intentional)
        "remote":      None,                     # None = "All" (no filter)
        "max_days":    30,
        "companies":   [],
    }

if "filters" not in st.session_state:
    st.session_state["filters"] = default_filters(filters)

f = st.session_state["filters"]

# ══════════════════════════════════════════════════════════════════
# Sync dict -> widgets, BEFORE creating the widgets.
# First run OR the reset button / chat just modified f.
# ══════════════════════════════════════════════════════════════════
if st.session_state.pop("_filters_dirty", False) or "w_score" not in st.session_state:
    st.session_state["w_companies"] = f["companies"]
    st.session_state["w_search"]      = f["search"]
    st.session_state["w_score"]       = f["score_range"]
    st.session_state["w_contracts"]   = f["contracts"]
    st.session_state["w_cities"]      = f["cities"]
    st.session_state["w_countries"]   = f["countries"]
    st.session_state["w_languages"]   = f["languages"]
    st.session_state["w_seniorities"] = f["seniorities"]
    st.session_state["w_remote"]      = REMOTE_LABELS[f["remote"]]
    st.session_state["w_maxdays"]     = f["max_days"]
    #Table company 
    st.session_state["w_companies"] = f["companies"]


# ══════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════
st.markdown("""
<style>
    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 0.5rem;
    }
    section[data-testid="stSidebar"] .element-container {
        margin-bottom: -0.5rem;
    }
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

    st.select_slider(
        "📅 Date range",
        options=filters["day_options"],
        key="w_maxdays",
    )

    st.radio(
        "🏠 Remote work",
        list(filters["remote_labels"].values()),
        key="w_remote",
        horizontal=True,
    )




# ══════════════════════════════════════════════════════════════════
# Copy widgets -> dict (after rendering, captures manual input)
# ══════════════════════════════════════════════════════════════════
f["companies"] = st.session_state["w_companies"]
f["search"]      = st.session_state["w_search"]
f["score_range"] = st.session_state["w_score"]
f["contracts"]   = st.session_state["w_contracts"]
f["cities"]      = st.session_state["w_cities"]
f["countries"]   = st.session_state["w_countries"]
f["languages"]   = st.session_state["w_languages"]
f["seniorities"] = st.session_state["w_seniorities"]
f["remote"]      = REMOTE_VALUES[st.session_state["w_remote"]]
f["max_days"]    = st.session_state["w_maxdays"]



# ══════════════════════════════════════════════════════════════════
# DashBoard
# ══════════════════════════════════════════════════════════════════
def group_small_categories(counts: pd.Series, threshold_pct: float = 0.01, other_label: str = "Other") -> pd.Series:
    """Under a certain % label it 'Other'."""
    total = counts.sum()
    mask = counts / total < threshold_pct
    if mask.any():
        other_total = counts[mask].sum()
        counts = counts[~mask]
        counts.loc[other_label] = other_total
    return counts

# ══════════════════════════════════════════════════════════════════
# Offers table
# ══════════════════════════════════════════════════════════════════
def render_offers_table(d: pd.DataFrame, selected_job_ids: list | None = None) -> None:
    if d.empty:
        st.subheader("📋 Offers")
        st.info("No offers to display.")
        return

    table_source = d
    if selected_job_ids:
        table_source = d[d.index.isin(selected_job_ids)]
        st.caption(f"📍 Showing {len(table_source)} offer(s) at the selected location(s).")

    display_df = table_source.copy()
    if "offer_languages_full" in display_df.columns:
        display_df["languages"] = display_df["offer_languages_full"].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else ""
        )

    show_cols = [c for c in ["job_title", "company_name", "city", "country_full",
                              "seniority", "languages", "score_relevancy"]
                 if c in display_df.columns]

    st.subheader("📋 Offers")
    event = st.dataframe(
        display_df[show_cols],
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        key="offers_table",
    )

    if event.selection.rows:
            clicked_row_idx = event.selection.rows[0]
            if clicked_row_idx < len(display_df):
                clicked_job_id = display_df.index[clicked_row_idx]
                if st.session_state.get("highlighted_job_id") != clicked_job_id:
                    st.session_state["highlighted_job_id"] = clicked_job_id
                    st.rerun()
            else:
                # Sélection périmée (le tableau a changé de taille) — on l'ignore silencieusement
                st.session_state["highlighted_job_id"] = None


def build_dashboard(d: pd.DataFrame, d_filtered_without_company: pd.DataFrame) -> None:
    # ── Metric ───────────────────────────────────────────────────
    st.metric("📦 Offers currently displayed", len(d))

    # ── Map (Plotly, clickable, stacked by location, highlight + recenter) ──
    selected_job_ids = None

    if {"latitude", "longitude"}.issubset(d.columns):
        map_df = d.dropna(subset=["latitude", "longitude"]).reset_index()  # job_id redevient une colonne

        if not map_df.empty:
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

            # ── Highlight du point sélectionné depuis le tableau ──────────
            highlighted_id = st.session_state.get("highlighted_job_id")

            grouped["is_highlighted"] = grouped["job_ids"].apply(
                lambda ids: highlighted_id in ids if highlighted_id else False
            )
            grouped["marker_color"] = grouped["is_highlighted"].map(
                {True: "#2ECC71", False: "#FF4B4B"}
            )

            # ── Recentrage sur le(s) point(s) surligné(s), barycentre si plusieurs ──
            highlighted_points = grouped[grouped["is_highlighted"]]
            if not highlighted_points.empty:
                map_center = dict(
                    lat=highlighted_points["latitude"].mean(),
                    lon=highlighted_points["longitude"].mean(),
                )
                map_zoom = 8
            else:
                map_center = dict(lat=-25, lon=-60)  # vue par défaut Amérique du Sud
                map_zoom = 3

            fig_map = px.scatter_mapbox(
                grouped,
                lat="latitude", lon="longitude",
                custom_data=["job_ids", "count"],
                height=450,
            )
            fig_map.update_traces(
                marker=dict(size=10, color=grouped["marker_color"]),
                text=grouped["hover_text"],
                hovertemplate="<b>%{customdata[1]} offer(s)</b><br>%{text}<extra></extra>",
            )
            fig_map.update_layout(
                mapbox=dict(
                    style="carto-darkmatter",
                    pitch=0,
                    bearing=0,
                    center=map_center,
                    zoom=map_zoom,
                ),
                margin=dict(l=0, r=0, t=0, b=0),
                dragmode="select",   # glisser trace un rectangle de sélection
                selectdirection="any",
                # uirevision change avec highlighted_id pour forcer le recentrage
                # au changement de sélection, tout en préservant le zoom/pan manuel
                # de l'utilisateur tant que la sélection ne change pas.
                uirevision=f"offers_map_{highlighted_id}" if highlighted_id else "offers_map",
            )

            event = st.plotly_chart(
                fig_map, width="stretch",
                on_select="rerun", selection_mode="points",
                key="offers_map",
                config={
                    "scrollZoom": True,
                    "displayModeBar": True,
                },
            )

            if event.selection.points:
                all_selected_ids = []
                for pt in event.selection.points:
                    idx = pt["point_index"]
                    all_selected_ids.extend(grouped.iloc[idx]["job_ids"])
                selected_job_ids = all_selected_ids
            else:
                st.caption("💡 Click or box-select points on the map to filter the table below.")
        else:
            st.info("No geolocated offers to display on the map.")
    else:
        st.info("Columns 'latitude'/'longitude' not found — map skipped.")

    render_offers_table(d, selected_job_ids)


    # ── Country pie chart ────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        country_counts = d["country_full"].value_counts()
        country_counts = group_small_categories(country_counts, threshold_pct=0.01)
        country_counts = country_counts.reset_index()
        country_counts.columns = ["country", "count"]
        fig_country = px.pie(
            country_counts, names="country", values="count",
            title="Offers by country",
        )
        st.plotly_chart(fig_country, width="stretch")

    # ── Language bar chart ───────────────────────────────────────
    # Bar chart, not pie: an offer can have several languages, so
    # percentages of a pie wouldn't sum to 100% — a bar chart of
    # raw counts is more honest here.
    with col2:
        lang_counts = (
            d["offer_languages_full"]
            .dropna()
            .explode()
            .dropna()
        )
        # Filtre les valeurs vides/None résiduelles (string "None", "", espaces)
        lang_counts = lang_counts[
            lang_counts.astype(str).str.strip().str.lower().isin(["none", "nan", ""]) == False
        ]
        lang_counts = lang_counts.value_counts()
        lang_counts = group_small_categories(lang_counts, threshold_pct=0.01)
        lang_counts = lang_counts.reset_index()
        lang_counts.columns = ["language", "count"]
        fig_lang = px.bar(
            lang_counts, x="language", y="count",
            title="Offers by language (an offer can have several)",
        )
        st.plotly_chart(fig_lang, width="stretch")

    col3, col4 = st.columns(2)

    # ── Seniority pie chart ──────────────────────────────────────
    with col3:
        seniority_counts = d["seniority"].value_counts().reset_index()
        seniority_counts.columns = ["seniority", "count"]
        fig_seniority = px.pie(
            seniority_counts, names="seniority", values="count",
            title="Offers by seniority",
        )
        st.plotly_chart(fig_seniority, width="stretch")

    # ── Top skills/keywords bar chart ────────────────────────────
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
                exploded = d[col].dropna().explode().dropna()  # ← dropna() après explode aussi
                exploded = exploded[exploded.apply(lambda x: isinstance(x, str))]  # sécurité type
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
                color="category",
                title="Top 15 required skills/keywords",
            )
            fig_kw.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig_kw, width="stretch")
        else:
            st.info("No keywords found in the filtered offers.")

    # ── Company poster list — scrollable, clickable, filterable ──────────
    st.markdown("**🏆 Job posters companies**")

    # IMPORTANT : base sur les données filtrées par TOUT SAUF l'entreprise
    # (sinon cocher une boîte fait disparaître les autres de la liste)
    d_base = d_filtered_without_company  # ← le dataframe filtré par rôle/ville/etc, PAS par company
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
            "company_name": "Company",
            "city": "City",
            "country_full": "Countries",
            "website": "Website",
            "nb_offers": "Offers",
        })
    )

    if "selected_companies" not in st.session_state:
        st.session_state["selected_companies"] = []

    all_companies.insert(
            0, "Select",
            all_companies["Company"].isin(f["companies"])   # ← lit f, pas selected_companies
        )

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



# ══════════════════════════════════════════════════════════════════
# Apply filters and display
# ══════════════════════════════════════════════════════════════════
filtered_df = apply_filters(df, f, dict_reversed_index, city_country_map)

# Copie des filtres actifs, sans le filtre "companies"
filters_without_company = dict(f)
filters_without_company["companies"] = []
d_filtered_without_company = apply_filters(df, filters_without_company, dict_reversed_index, city_country_map)

st.subheader("📊 Dashboard")
build_dashboard(filtered_df, d_filtered_without_company)
st.caption(f"**{len(filtered_df)}** offers match the filters (out of {len(df)}).")





# ══════════════════════════════════════════════════════════════════
# 💬 Chatbot — Barre flottante fixée à droite
# ══════════════════════════════════════════════════════════════════

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []
if "chat_open" not in st.session_state:
    st.session_state["chat_open"] = False
if "filters" not in st.session_state:
    st.session_state["filters"] = {}


# ── 1. CSS Forcé avec !important ─────────────────────────────────
st.markdown("""
<style>
    /* 1. Bouton Toggle - Ciblage strict du parent immédiat */
    div[data-testid="stVerticalBlock"]:has(> div.element-container .btn-anchor) {
        position: fixed !important;
        bottom: 90px !important;
        right: 30px !important;
        width: auto !important;
        z-index: 99999 !important;
    }
    
    div[data-testid="stVerticalBlock"]:has(> div.element-container .btn-anchor) button {
        border-radius: 50% !important;
        width: 45px !important;
        height: 45px !important;
        background-color: #262730 !important;
        color: white !important;
        border: 2px solid #4a4b55 !important;
        font-size: 18px !important;
        box-shadow: 0 4px 8px rgba(0,0,0,0.4) !important;
        padding: 0 !important;
    }

    div[data-testid="stVerticalBlock"]:has(> div.element-container .btn-anchor) button:hover {
        background-color: #3a3b45 !important;
        border-color: #ff4b4b !important;
        color: #ff4b4b !important;
    }

    /* 2. Panneau de Chat - Ciblage strict du parent immédiat */
    div[data-testid="stVerticalBlock"]:has(> div.element-container .chat-anchor) {
        position: fixed !important;
        bottom: 145px !important; 
        right: 30px !important;
        width: 350px !important;
        max-height: 400px !important;
        overflow-y: auto !important;
        background-color: #0e1117 !important;
        border: 1px solid #4a4b55 !important;
        border-radius: 12px !important;
        padding: 15px !important;
        z-index: 99998 !important;
        box-shadow: 0px 10px 20px rgba(0,0,0,0.6) !important;
        display: flex !important;
        flex-direction: column !important;
    }
</style>
""", unsafe_allow_html=True)


# ── 2. Panneau d'historique (Flottant) ───────────────────────────
if st.session_state["chat_open"]:
    with st.container():
        # L'ancre doit être présente DANS ce conteneur pour le CSS
        st.markdown('<div class="chat-anchor"></div>', unsafe_allow_html=True)
        
        if not st.session_state["chat_history"]:
            st.caption("Ask me anything about the offers...")
            
        for role, content in st.session_state["chat_history"]:
            with st.chat_message(role):
                st.markdown(content)

# ── 3. Bouton Toggle (Flottant) ──────────────────────────────────
with st.container():
    st.markdown('<div class="btn-anchor"></div>', unsafe_allow_html=True)
    arrow_label = "✖" if st.session_state["chat_open"] else "💬"
    if st.button(arrow_label, key="chat_toggle"):
        st.session_state["chat_open"] = not st.session_state["chat_open"]
        st.rerun()

# ── 4. Barre de saisie (Native Streamlit) ────────────────────────
prompt = st.chat_input("Ask me anything...")

if prompt and prompt.strip():
    # Force l'ouverture du chat si l'utilisateur tape un message
    st.session_state["chat_open"] = True
    st.session_state["chat_history"].append(("user", prompt))

    with st.spinner("Thinking..."):
        time.sleep(1) # Simulation
        criteria = extract_filters(prompt, get_llm())
        new_filters = criteria_to_filter_dict(criteria, st.session_state["filters"])
        st.session_state["filters"] = new_filters
        st.session_state["_filters_dirty"] = True

    st.session_state["chat_history"].append(("assistant", summarize_criteria(criteria)))
    st.rerun()
