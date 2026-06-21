import streamlit as st
import pandas as pd
import numpy as np
import plotly as px
from fake_offer import fake_job_offers 

import time
import sys
import os


# 1. Récupère le chemin du dossier parent commun
dossier_parent = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 2. Construit le chemin pour le premier dossier voisin
voisin_1 = os.path.join(dossier_parent, 'src')

# 3. Construit le chemin pour le deuxième dossier voisin
voisin_2 = os.path.join(dossier_parent, 'LangGraph_Agent')

# 4. Ajoute les deux dossiers au système de recherche de Python
for dossier in [voisin_1, voisin_2]:
    if dossier not in sys.path:
        sys.path.append(dossier)

# 5. Importe vos fichiers respectifs 
from database import Database
from silver_enrichment import *


# agent.py
import streamlit as st
from groq import Groq

@st.cache_resource
def get_groq_client():
    return Groq(api_key=st.secrets["groq"]["api_key"])

def extraire_filtres(question: str) -> dict:
    pass

def appliquer_filtres(nouveaux: dict, default_filters_fn) -> None:
    pass

# # 1. Connexion persistante (Resource)
# @st.cache_resource
# def get_db_connection():
#     # Retourne ton objet Database
#     return Database(**st.secrets["database"])

# # 2. Chargement des données (Data)
# @st.cache_data(ttl=3600) # ttl=3600 recharge les données toutes les heures
# def load_data(query: str):
#     db = get_db_connection() # On appelle la connexion ici
#     data = db.execute(query)
#     return pd.DataFrame(data)
     

# def refresh_data_if_needed():
#     # On utilise le session_state pour que ça ne tourne qu'une fois par visiteur
#     if 'data_refreshed' not in st.session_state:
#         with st.spinner("Réveil de la base de données... un instant."):
#             try:
#                 db = get_db_connection()
#                 db.execute("SELECT serving.refresh_job_offer_if_stale();")
#                 st.session_state['data_refreshed'] = True
#             except Exception as e:
#                 st.error(f"Erreur de connexion : {e}")

# # Appel de la fonction dès le lancement
# refresh_data_if_needed()


# # Utilisation
# query = "SELECT * FROM raw.job_offer LIMIT 5;"
# df = load_data(query)

# st.dataframe(df)
df = pd.DataFrame(fake_job_offers)

st.set_page_config(page_title="AI Job Offer Dashboard Latam", page_icon="🏙️", layout="wide")
st.title("🏙️ AI Job Offer Dashboard Latam")

# ══════════════════════════════════════════════════════════════════
# Cleaning
# ══════════════════════════════════════════════════════════════════
df["is_remote"] = df["is_remote"].fillna(False)
df["country"] = df["country"].fillna("Not specified")
df["company_name"] = df["company_name"].fillna("unknown")

# ══════════════════════════════════════════════════════════════════
# Lists for widgets
# ══════════════════════════════════════════════════════════════════
if not df["score_relevancy"].empty:
    MIN_SCORE, MAX_SCORE = int(df["score_relevancy"].min()), int(df["score_relevancy"].max())
else:
    MIN_SCORE, MAX_SCORE = 0, 10

ALL_CONTRACTS   = sorted(df["contract_type"].dropna().unique().tolist())
ALL_CITIES      = sorted(df["city"].dropna().unique().tolist())
ALL_SENIORITIES = sorted(df["seniority"].dropna().unique().tolist())
ALL_COMPANIES   = sorted(df["company_name"].unique().tolist())
ALL_COUNTRIES   = sorted(df["country"].unique().tolist())
ALL_LANGUAGES   = sorted(set(lang for sub in df["offer_languages"].dropna() for lang in sub))


SEARCH_COLUMNS = ["alternative_job_titles", "skills_frameworks", "skills_languages"]


if "collected_at" in df.columns:
    df["collected_at"] = pd.to_datetime(df["collected_at"])

# Mapping for the "Remote" radio (None = no filter)
REMOTE_LABELS = {None: "All", True: "Remote", False: "On-site"}
REMOTE_VALUES = {v: k for k, v in REMOTE_LABELS.items()}

DAY_OPTIONS = [7, 14, 30, 60, 90, "All time"]


# ══════════════════════════════════════════════════════════════════
# Search blob — combines job title + frameworks + languages
# ══════════════════════════════════════════════════════════════════
def _build_search_blob(row) -> str:
    """Concatenates all keywords of an offer into one searchable text."""
    parts = [str(row.get("job_title", ""))]
    for col in SEARCH_COLUMNS:
        val = row.get(col)
        if isinstance(val, list):
            parts.extend(val)
        elif isinstance(val, str):
            parts.append(val)
    return " ".join(p.lower() for p in parts if p)

df["_search_blob"] = df.apply(_build_search_blob, axis=1)


# ══════════════════════════════════════════════════════════════════
# Filtering logic
# ══════════════════════════════════════════════════════════════════
def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    out = df

    # Keywords (title, frameworks, languages) — all words must match
    if f["search"]:
        keywords = f["search"].lower().split()
        mask = out["_search_blob"].apply(lambda blob: all(k in blob for k in keywords))
        out = out[mask]

    lo, hi = f["score_range"]
    out = out[(out["score_relevancy"] >= lo) & (out["score_relevancy"] <= hi)]

    if f["contracts"]:
        out = out[out["contract_type"].isin(f["contracts"])]
    if f["cities"]:
        out = out[out["city"].isin(f["cities"])]
    if f["countries"]:
        out = out[out["country"].isin(f["countries"])]
    if f["languages"]:
        out = out[out["offer_languages"].apply(lambda langs: any(l in langs for l in f["languages"]))]
    if f["seniorities"]:
        out = out[out["seniority"].isin(f["seniorities"])]
    if f["remote"] is not None:
        out = out[out["is_remote"] == f["remote"]]

    # "All time" = no date filter
    if f["max_days"] != "All time" and "collected_at" in out.columns:
        cutoff = pd.Timestamp.now() - pd.Timedelta(days=f["max_days"])
        out = out[out["collected_at"] >= cutoff]

    return out


# ══════════════════════════════════════════════════════════════════
# Default filters — source of truth: st.session_state["filters"]
# ══════════════════════════════════════════════════════════════════
def default_filters() -> dict:
    return {
        "search":      "",
        "score_range": (max(0, MIN_SCORE), min(10, MAX_SCORE)),
        "contracts":   [],
        "cities":      [],
        "countries":   [],
        "languages":   [],
        "seniorities": list(ALL_SENIORITIES),   # all checked by default (intentional)
        "remote":      None,                     # None = "All" (no filter)
        "max_days":    30,
        "companies":   [],                        # no widget tonight, kept for later
        "top_n":       10,                         # no widget tonight
    }

if "filters" not in st.session_state:
    st.session_state["filters"] = default_filters()

f = st.session_state["filters"]

# ══════════════════════════════════════════════════════════════════
# Sync dict -> widgets, BEFORE creating the widgets.
# First run OR the reset button / chat just modified f.
# ══════════════════════════════════════════════════════════════════
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


# ══════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("🔎 Filters")
    st.caption("Editable manually or by the chatbot")

    st.text_input(
        "🔍 Keywords (title, skills...)",
        key="w_search",
        placeholder="e.g. data engineering, airflow, python",
    )

    st.slider(
        "⭐ Relevancy score",
        MIN_SCORE, max(MAX_SCORE, MIN_SCORE + 1),
        key="w_score",
    )

    st.multiselect("📄 Contract type", ALL_CONTRACTS, key="w_contracts")
    st.multiselect("🌎 Country", ALL_COUNTRIES, key="w_countries")
    st.multiselect("🏙️ City", ALL_CITIES, key="w_cities")
    st.multiselect("🗣️ Offer language", ALL_LANGUAGES, key="w_languages")
    st.multiselect("📈 Seniority", ALL_SENIORITIES, key="w_seniorities")

    st.select_slider(
        "📅 Date range",
        options=DAY_OPTIONS,
        key="w_maxdays",
    )

    st.radio(
        "🏠 Remote work",
        list(REMOTE_LABELS.values()),
        key="w_remote",
        horizontal=True,
    )

    if st.button("♻️ Reset filters"):
        st.session_state["filters"] = default_filters()
        st.session_state["_filters_dirty"] = True
        st.rerun()

    st.checkbox("🤖 Try AI agent", value=False, key="w_use_agent")

    st.divider()
    st.write("Dashboard developed by X")
    st.write("[LinkedIn](https://linkedin.com/in/X)")
    st.write("[GitHub project](Github link)")


# ══════════════════════════════════════════════════════════════════
# Copy widgets -> dict (after rendering, captures manual input)
# ══════════════════════════════════════════════════════════════════
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
def build_dashboard(d: pd.DataFrame) -> None:
    if d.empty:
        st.warning("No offers match the current filters.")
        return

    # ── Metric ───────────────────────────────────────────────────
    st.metric("📦 Offers currently displayed", len(d))

    # ── Map ──────────────────────────────────────────────────────
    if {"lat", "lon"}.issubset(d.columns):
        map_df = d.dropna(subset=["latitude", "longitude"])
        if not map_df.empty:
            fig_map = px.scatter_mapbox(
                map_df, lat="latitude", lon="longitude",
                hover_name="company_name",
                hover_data={"job_title": True, "score_relevancy": True,
                            "latitude": False, "longitude": False},
                color="score_relevancy", color_continuous_scale="Viridis",
                zoom=3, height=450,
            )
            fig_map.update_layout(mapbox_style="open-street-map",
                                   margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig_map, use_container_width=True)
        else:
            st.info("No geolocated offers to display on the map.")
    else:
        st.info("Columns 'latitude'/'longitude' not found — map skipped.")

    col1, col2 = st.columns(2)

    # ── Country pie chart ────────────────────────────────────────
    with col1:
        country_counts = d["country"].value_counts().reset_index()
        country_counts.columns = ["country", "count"]
        fig_country = px.pie(
            country_counts, names="country", values="count",
            title="Offers by country",
        )
        st.plotly_chart(fig_country, use_container_width=True)

    # ── Language bar chart ───────────────────────────────────────
    # Bar chart, not pie: an offer can have several languages, so
    # percentages of a pie wouldn't sum to 100% — a bar chart of
    # raw counts is more honest here.
    with col2:
        lang_counts = d["offer_languages"].dropna().explode().value_counts().reset_index()
        lang_counts.columns = ["language", "count"]
        fig_lang = px.bar(
            lang_counts, x="language", y="count",
            title="Offers by language (an offer can have several)",
        )
        st.plotly_chart(fig_lang, use_container_width=True)

    col3, col4 = st.columns(2)

    # ── Seniority pie chart ──────────────────────────────────────
    with col3:
        seniority_counts = d["seniority"].value_counts().reset_index()
        seniority_counts.columns = ["seniority", "count"]
        fig_seniority = px.pie(
            seniority_counts, names="seniority", values="count",
            title="Offers by seniority",
        )
        st.plotly_chart(fig_seniority, use_container_width=True)

    # ── Top 5 offers table ───────────────────────────────────────
    with col4:
        st.markdown("**🏆 Top 5 offers by score**")
        top5 = (
            d.sort_values("score_relevancy", ascending=False)
             .head(5)[["job_title", "company_name", "website", "score_relevancy"]]
             .rename(columns={
                 "job_title": "Title",
                 "company_name": "Company",
                 "company_website": "Website",
                 "score_relevancy": "Score",
             })
        )
        st.dataframe(top5, hide_index=True, use_container_width=True)

    # ── Offers collected over time ────────────────────────────────
    # Built from `d` (already filtered by max_days), so it updates automatically.
    if "collected_at" in d.columns:
        ts = (
            d.assign(date=d["collected_at"].dt.date)
             .groupby("date").size().reset_index(name="count")
        )
        fig_ts = px.line(
            ts, x="date", y="count", markers=True,
            title="Offers collected over time",
        )
        st.plotly_chart(fig_ts, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# Apply filters and display
# ══════════════════════════════════════════════════════════════════
filtered_df = apply_filters(df, f)
st.subheader("📊 Dashboard")
build_dashboard(filtered_df)
st.caption(f"**{len(filtered_df)}** offers match the filters (out of {len(df)}).")