import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px          # ⚠️ corrigé : était `import plotly as px` (cassait scatter_mapbox/pie/bar)
# from fake_offer import fake_job_offers

import time
import os
import sys

# 1. Récupère le chemin absolu du dossier 'python' (parent commun)
# __file__ est dans user_interface/, son parent ('..') est python/
dossier_parent = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

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
from database import Database
from silver_enrichment import *
from dashboard_agent import (
    SETTINGS,
    extract_profile_keywords,
    resolve_id_column,
    run_agent,
)



# ══════════════════════════════════════════════════════════════════
# Ressources & cache (LLM, profil, README)
# ══════════════════════════════════════════════════════════════════
# # 1. Connexion persistante (Resource)
@st.cache_resource
def get_db_connection():
    # Retourne ton objet Database
    return Database(**st.secrets["database"])

@st.cache_resource
def get_llm():
    # LLM vient de silver_enrichment ; clé depuis les secrets Streamlit
    return LLM(groq_key=st.secrets["groq"]["api_key"])


@st.cache_data(show_spinner=False)
def get_profile_keywords(profile_text: str):
    """Extraction des mots-clés du profil — mise en cache car le profil change rarement."""
    if not (profile_text or "").strip():
        return None
    llm = get_llm()
    # llama4_smart : plus conservateur (préfère null à l'hallucination)
    return extract_profile_keywords(llm.llama4_smart, profile_text)


@st.cache_data(show_spinner=False)
def load_readme() -> str:
    """Charge la doc projet (README) comme contexte pour la fonctionnalité INFO."""
    candidates = [
        os.path.join(dossier_parent, "README.md"),
        os.path.join(dossier_parent, "..", "README.md"),
        os.path.join(os.path.dirname(__file__), "README.md"),
        os.path.join(dossier_parent, "Documentation.md"),
        os.path.join(dossier_parent, "ProjetLatam.md"),
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
        except Exception:
            continue
    # Fallback minimal si aucun fichier trouvé
    return (
        "InternshipLatam — automated data pipeline that collects, enriches and scores "
        "Data-Engineering internship/job offers in Latin America (Chile, Argentina, Uruguay). "
        "Architecture Bronze/Silver/Gold: Airflow ingestion (JSearch, CareerJet) -> LangGraph "
        "enrichment with Groq (company, geolocation, contacts, relevancy scoring) -> PostgreSQL "
        "on Neon -> Streamlit dashboard. The chat supports FILTER (apply filters), MATCH (rank "
        "offers against your profile) and INFO (answer questions about the project)."
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
        (
            SELECT jsonb_agg(DISTINCT val)
            FROM (
                SELECT jsonb_array_elements_text(
                    COALESCE(array_to_json(skills_languages)::jsonb, '[]'::jsonb) || 
                    COALESCE(array_to_json(skills_frameworks)::jsonb, '[]'::jsonb) || 
                    COALESCE(array_to_json(skills_aptitudes)::jsonb, '[]'::jsonb) || 
                    COALESCE(array_to_json(skills_soft)::jsonb, '[]'::jsonb) ||
                    COALESCE(array_to_json(alternative_job_titles)::jsonb, '[]'::jsonb)
                ) AS val
            ) sub
        ) AS all_skills,
        score_relevancy,
        explanation,
        company_name,
        website,
        primary_type,
        city,
        country,
        lat as latitude,   -- Aliased for Plotly map compatibility
        lon as longitude,  -- Aliased for Plotly map compatibility
        offer_url,
        published_at,
        collected_at
    FROM serving.job_offer;
    """
    db.execute('SELECT serving.refresh_job_offer_if_stale();')
    return db.execute(query)



# ══════════════════════════════════════════════════════════════════
# Données (fake data en dev)
# ══════════════════════════════════════════════════════════════════
# Load the real dataframe
df = pd.DataFrame(load_real_offers())

st.set_page_config(page_title="AI Job Offer Dashboard Latam", page_icon="🏙️", layout="wide")
st.title("🏙️ AI Job Offer Dashboard Latam")

# ══════════════════════════════════════════════════════════════════
# Cleaning
# ══════════════════════════════════════════════════════════════════
df["is_remote"] = df["is_remote"].fillna(False)
df["country"] = df["country"].fillna("Not specified")
df["company_name"] = df["company_name"].fillna("unknown")

if "collected_at" in df.columns:
    df["collected_at"] = pd.to_datetime(df["collected_at"])


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
    if f.get("companies"):                       # ➕ décision #5 : on lit enfin le filtre companies
        out = out[out["company_name"].isin(f["companies"])]
    if f["remote"] is not None:
        out = out[out["is_remote"] == f["remote"]]

    # "All time" = no date filter
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
        "companies":   [],                        # pas de widget, piloté par le chat (décision #5)
        # `top_n` retiré : config morte, déplacé en interne du MATCH (SETTINGS.fuzzy_pool_size — décision #6)
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
        st.session_state.pop("match_results", None)
        st.session_state.pop("match_offer_ids", None)
        st.rerun()

    st.checkbox("🤖 Try AI agent", value=False, key="w_use_agent")

    # ── Profil utilisateur (utilisé par la fonctionnalité MATCH) ──
    with st.expander("🧑 Your profile (for matching)"):
        st.text_area(
            "Describe your skills, target role, languages…",
            key="user_profile",
            placeholder="e.g. Junior Data Engineer. Python, SQL, Airflow, Docker, LangGraph. "
                        "Looking for a data engineering internship in Latin America. English C1, French native.",
            height=160,
        )

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
    if {"latitude", "longitude"}.issubset(d.columns):
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


# ══════════════════════════════════════════════════════════════════
# Offers table — surligne les offres matchées par le chat (décision #4)
# ══════════════════════════════════════════════════════════════════
def render_offers_table(d: pd.DataFrame) -> None:
    if d.empty:
        return
    matched = set(st.session_state.get("match_offer_ids", []))

    disp = d.copy()
    id_col = resolve_id_column(disp)
    disp["_offer_id"] = disp[id_col].astype(str) if id_col else disp.index.astype(str)

    show_cols = [c for c in ["job_title", "company_name", "city", "country",
                             "seniority", "is_remote", "score_relevancy"] if c in disp.columns]
    view = disp[show_cols + ["_offer_id"]]

    def _row_style(r):
        on = r["_offer_id"] in matched
        css = "background-color:#264653; color:white" if on else ""
        return [css for _ in r.index]

    st.subheader("📋 Offers")
    if matched:
        st.caption("Rows highlighted in green were matched to your profile by the assistant.")
    styler = view.style.apply(_row_style, axis=1)
    st.dataframe(styler, hide_index=True, use_container_width=True, column_order=show_cols)


render_offers_table(filtered_df)


# ══════════════════════════════════════════════════════════════════
# Match results — tableau détaillé renvoyé par la fonctionnalité MATCH
# ══════════════════════════════════════════════════════════════════
if st.session_state.get("match_results") is not None:
    mt = st.session_state["match_results"]
    if not mt.empty:
        st.subheader("🎯 Offers matching your profile")
        nice = mt.copy()
        nice["matched"] = nice["matched"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) else ""
        )
        nice = nice.rename(columns={
            "job_title": "Title",
            "company_name": "Company",
            "matched": "Matched keywords",
            "coverage": "Keywords matched",
        })[["Title", "Company", "Matched keywords", "Keywords matched"]]
        st.dataframe(nice, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════════
# 💬 Assistant (FILTER / MATCH / INFO) — visible si la case est cochée
# ══════════════════════════════════════════════════════════════════
def handle_user_message(prompt: str) -> None:
    """Appelle l'agent (pur) et applique ici les effets de bord (filtres, match, message)."""
    llm = get_llm()
    pk = get_profile_keywords(st.session_state.get("user_profile", ""))

    result = run_agent(
        llm=llm,
        message=prompt,
        df=df,
        user_profile=st.session_state.get("user_profile", ""),
        current_filters=st.session_state["filters"],
        readme_text=load_readme(),
        apply_filters_fn=apply_filters,
        default_filters_fn=default_filters,
        profile_keywords=pk,
        settings=SETTINGS,
    )

    # FILTER -> merge dans la source de vérité + resync sidebar au prochain run
    if result.new_filters:
        st.session_state["filters"].update(result.new_filters)
        st.session_state["_filters_dirty"] = True

    # MATCH -> stocke résultats + ids pour le surlignage
    if result.match_table is not None:
        st.session_state["match_results"] = result.match_table
        st.session_state["match_offer_ids"] = result.response.offer_ids

    st.session_state["chat_history"].append(("assistant", result.response.message))


if st.session_state.get("w_use_agent"):
    st.divider()
    st.subheader("💬 Assistant")

    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    for role, content in st.session_state["chat_history"]:
        with st.chat_message(role):
            st.markdown(content)

    prompt = st.chat_input("Filter offers, match your profile, or ask about the project…")
    if prompt:
        st.session_state["chat_history"].append(("user", prompt))
        with st.spinner("Thinking…"):
            handle_user_message(prompt)
        st.rerun()