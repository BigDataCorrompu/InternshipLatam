import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px          # ⚠️ corrigé : était `import plotly as px` (cassait scatter_mapbox/pie/bar)
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
from database import Database
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
        ) AS all_keywords,
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
            
        mots_uniques = {kw.lower().strip() for kw in keywords}
        
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

    # __ FULL COUNTRY NAME __
    cc = coco.CountryConverter()

    # Only convert non NaN
    mask = df['country'].notna()
    mask_language = df['offer_languages'].notna()

    # Apply conversion
    df.loc[mask, 'country_full'] = cc.convert(
    df.loc[mask, 'country'].tolist(), 
    to='name_short'
    )
    #Fill NaN with Nan
    df['country_full'] = df['country_full'].replace('not found', np.nan)
    df.loc[mask_language, 'offer_languages_full'] = df.loc[mask_language, 'offer_languages'].apply(convert_language_list)

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

# ══════════════════════════════════════════════════════════════════
# Lists for widgets
# ══════════════════════════════════════════════════════════════════
SEARCH_COLUMNS = ["all_keywords"]



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
    st.markdown(
        "[💼 LinkedIn](https://www.linkedin.com/in/roland-oucherif/) · "
        "[🔗 GitHub](https://github.com/BigDataCorrompu/InternshipLatam)"
    )
    st.divider()
    st.caption("Ask the chatbot !")
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
    st.multiselect("🏢 Company", filters["companies"], key="w_companies")

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
def render_offers_table(d: pd.DataFrame) -> None:
    if d.empty:
        return
    show_cols = [c for c in ["job_title", "company_name", "city", "country",
                             "seniority", "score_relevancy"] if c in d.columns]
    st.subheader("📋 Offers")
    st.dataframe(d[show_cols], hide_index=True, width="stretch")




def build_dashboard(d: pd.DataFrame) -> None:

    # ── Metric ───────────────────────────────────────────────────
    st.metric("📦 Offers currently displayed", len(d))

    # ── Map ───────────────────────────────────────────────────
    if {"latitude", "longitude"}.issubset(d.columns):
        map_df = d.dropna(subset=["latitude", "longitude"]).copy()

        if not map_df.empty:
            # Normalise le score sur une échelle 0-1 pour le gradient de couleur
            score_min, score_max = map_df["score_relevancy"].min(), map_df["score_relevancy"].max()
            map_df["score_norm"] = (map_df["score_relevancy"] - score_min) / (score_max - score_min + 1e-9)

            # Gradient rouge (faible) → jaune → vert (élevé), façon "Viridis-like" simple
            def score_to_color(norm_score):
                if norm_score < 0.5:
                    # rouge → jaune
                    r = 255
                    g = int(255 * (norm_score * 2))
                    b = 0
                else:
                    # jaune → vert
                    r = int(255 * (1 - (norm_score - 0.5) * 2))
                    g = 255
                    b = 0
                return [r, g, b]

            colors = map_df["score_norm"].apply(score_to_color)
            map_df["color_r"] = colors.apply(lambda c: c[0])
            map_df["color_g"] = colors.apply(lambda c: c[1])
            map_df["color_b"] = colors.apply(lambda c: c[2])

            layer = pdk.Layer(
                "ScatterplotLayer",
                data=map_df,
                get_position=["longitude", "latitude"],
                get_radius=3000,                    # points plus petits/précis
                radius_min_pixels=4,                 # toujours visible même très dézoomé
                radius_max_pixels=20,                # ne devient pas énorme en zoomant
                get_fill_color="[color_r, color_g, color_b, 200]",
                pickable=True,
                auto_highlight=True,
                stroked=True,
                get_line_color=[255, 255, 255],
                line_width_min_pixels=1,
            )

            view_state = pdk.ViewState(
                latitude=map_df["latitude"].mean(),
                longitude=map_df["longitude"].mean(),
                zoom=3,
                pitch=0,
            )

            deck = pdk.Deck(
                layers=[layer],
                initial_view_state=view_state,
                tooltip={
                    "html": "<b>{company_name}</b><br/>{job_title}<br/>Score: {score_relevancy}",
                    "style": {"backgroundColor": "steelblue", "color": "white"}
                },
            )

            st.pydeck_chart(deck, width="stretch")

            # ── Légende du score ────────────────────────────────────
            legend_col1, legend_col2, legend_col3 = st.columns(3)
            with legend_col1:
                st.markdown(f"🔴 **Faible** (~{score_min:.1f})")
            with legend_col2:
                st.markdown(f"🟡 **Moyen** (~{(score_min+score_max)/2:.1f})")
            with legend_col3:
                st.markdown(f"🟢 **Élevé** (~{score_max:.1f})")

        else:
            st.info("No geolocated offers")
            view_state = pdk.ViewState(latitude=-25.0, longitude=-60.0, zoom=2.5, pitch=0)
            deck = pdk.Deck(layers=[], initial_view_state=view_state)
            st.pydeck_chart(deck)
    else:
        st.info("Columns 'latitude'/'longitude' not found - Empty map")
        view_state = pdk.ViewState(latitude=-25.0, longitude=-60.0, zoom=2.5, pitch=0)
        deck = pdk.Deck(layers=[], initial_view_state=view_state)
        st.pydeck_chart(deck)

    render_offers_table(d)

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
        lang_counts = d["offer_languages_full"].dropna().explode().dropna().value_counts()
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

    # ── Top 5 company poster table ───────────────────────────────────────
    with col4:
        st.markdown("**🏆 Top 5 job posters companies**")
        d_with_site = d[d["website"].notna() & (d["website"] != "")]
        company_count = d_with_site["company_name"].value_counts().reset_index()
        company_count.columns = ["company_name", "nb_offers"]
        company_info = (
            d_with_site.groupby("company_name")
            .agg({
                "website": "first",
                "country_full": lambda x: ", ".join(sorted(set(x.dropna()))),
            })
            .reset_index()
        )
        top5 = (
            company_count.merge(company_info, on="company_name", how="left")
            .sort_values("nb_offers", ascending=False)
            .head(5)
            .rename(columns={
                "company_name": "Company",
                "country_full": "Countries",
                "website": "Website",
                "nb_offers": "Offers",
            })
        )
        st.dataframe(
            top5, 
            hide_index=True, 
            width="stretch",
            column_config={
                "Website": st.column_config.LinkColumn("Website")
            })

    # ── Offers collected over time ────────────────────────────────
    # Built from `d` (already filtered by max_days), so it updates automatically.
    if "collected_at" in d.columns:
        ts = (
            d.assign(date=d["collected_at"].dt.date)
             .groupby("date").size().reset_index(name="count")
        )
        fig_ts = px.line(
            ts, x="date", y="count", markers=True,
            title="Exploitable offers collected over time",
        )
        st.plotly_chart(fig_ts, width="stretch")


# ══════════════════════════════════════════════════════════════════
# Apply filters and display
# ══════════════════════════════════════════════════════════════════
filtered_df = apply_filters(df, f, dict_reversed_index, city_country_map)
st.subheader("📊 Dashboard")
build_dashboard(filtered_df)
st.caption(f"**{len(filtered_df)}** offers match the filters (out of {len(df)}).")





# ══════════════════════════════════════════════════════════════════
# 💬 Chatbot — extrait des filtres, Streamlit les applique
# ══════════════════════════════════════════════════════════════════

st.markdown("""
<style>
    div[data-testid="stPopover"] button {
        position: fixed;
        bottom: 20px;
        right: 20px;
        z-index: 9999;
        border-radius: 50%;
        width: 60px;
        height: 60px;
        background-color: #800020;
        transition: background-color 0.3s ease;  
    }
    div[data-testid="stPopover"] button:hover {
        background-color: #A61C3E;
    }
            
</style>
""", unsafe_allow_html=True)

with st.popover("💬"):
    st.markdown("**Ask me anything**")
    
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    for role, content in st.session_state["chat_history"]:
        with st.chat_message(role):
            st.markdown(content)


    prompt = st.text_area(
        "Ask me anything…", 
        key="popover_text_input",
        placeholder="Give me your profile",
        label_visibility='collapsed',
        height=80,
        )
    
    if st.button("Envoyer", key="popover_send_btn") and prompt:
        st.session_state["chat_history"].append(("user", prompt))

        with st.spinner("Thinking…"):
            # 1) Le LLM extrait uniquement des critères (aucune action sur l'UI)
            criteria = extract_filters(prompt, get_llm())

            # 2) Conversion -> dict de filtres, en partant des filtres actuels
            new_filters = criteria_to_filter_dict(criteria, st.session_state["filters"])

            # 3) Streamlit (thread principal) applique : écrit l'état + déclenche la resync
            st.session_state["filters"] = new_filters
            st.session_state["_filters_dirty"] = True

            # 4) Confirmation dans le chat
        st.session_state["chat_history"].append(("assistant", summarize_criteria(criteria)))
        del st.session_state["popover_text_input"]
        st.rerun()

        st.rerun()


