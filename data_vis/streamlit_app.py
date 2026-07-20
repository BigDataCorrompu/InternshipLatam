import sys
from pathlib import Path
import streamlit as st

CURRENT_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJECT_ROOT / "ingestion" / "python" / "src"
DOC_DIR = PROJECT_ROOT / "docs"

sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(DOC_DIR))

dashboard_path = CURRENT_DIR / "views" / "dashboard.py"
doc_path = CURRENT_DIR / "views" / "doc.py"

st.set_page_config(
    page_title="InternshipLatam Dashboard",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def render_insights():
    st.title("💡 Insights")
    st.info("Cette section est en cours de développement et n'est pas encore implémentée.")

# --- DÉFINITION DES PAGES ---
dashboard_page = st.Page(page=str(dashboard_path), title="Dashboard", icon="📊", default=True)
insights_page = st.Page(page=render_insights, title="Insights", icon="💡")
doc_page = st.Page(page=str(doc_path), title="Documentation (README)", icon="📝")

pg = st.navigation([dashboard_page, insights_page, doc_page], position="hidden")

# --- LOGIQUE D'OPACITÉ DYNAMIQUE ---
op_dash = "1.0" if pg.title == "Dashboard" else "0.4"
op_ins  = "1.0" if pg.title == "Insights" else "0.4"
op_doc  = "1.0" if pg.title == "Documentation (README)" else "0.4"

hov_dash = "1.0" if pg.title == "Dashboard" else "0.8"
hov_ins  = "1.0" if pg.title == "Insights" else "0.8"
hov_doc  = "1.0" if pg.title == "Documentation (README)" else "0.8"


# --- INJECTION CSS (couleurs sombres/transparentes + boutons plus fins) ---
st.markdown(f"""
    <style>
    /* Supprimer l'espace vide en haut et cacher le header natif */
    .block-container {{
        padding-top: 0rem !important;
        margin-top: 0rem !important;
        padding-bottom: 0rem !important;
    }}
    header[data-testid="stHeader"] {{
        display: none !important; 
    }}
    div[data-testid="stHorizontalBlock"] {{
        gap: 0rem !important;
    }}

    /* Style global : boutons plus fins, ombre douce */
    .st-key-nav_dashboard button,
    .st-key-nav_insights button,
    .st-key-nav_doc button {{
        border-radius: 0px 0px 10px 10px !important;
        padding: 8px 0px !important;
        box-shadow: 0px 1px 3px rgba(0,0,0,0.25) !important;
        transition: opacity 0.3s ease, background 0.3s ease !important;
    }}

    /* Texte en gras et blanc pour les 3 boutons */
    .st-key-nav_dashboard button p,
    .st-key-nav_insights button p,
    .st-key-nav_doc button p {{
        font-weight: bold !important;
        font-size: 16px !important;
        margin: 0 !important;
        color: white !important;
    }}

    /* Bouton 1 : Vert sombre/transparent (Dashboard) */
    .st-key-nav_dashboard button {{
        background: rgba(40, 167, 69, 0.16) !important;
        border: 1px solid rgba(40, 167, 69, 0.45) !important;
        opacity: {op_dash} !important;
    }}
    .st-key-nav_dashboard button:hover {{
        background: rgba(40, 167, 69, 0.26) !important;
        opacity: {hov_dash} !important;
    }}

    /* Bouton 2 : Bleu sombre/transparent (Insights) */
    .st-key-nav_insights button {{
        background: rgba(0, 123, 255, 0.16) !important;
        border: 1px solid rgba(0, 123, 255, 0.45) !important;
        opacity: {op_ins} !important;
    }}
    .st-key-nav_insights button:hover {{
        background: rgba(0, 123, 255, 0.26) !important;
        opacity: {hov_ins} !important;
    }}

    /* Bouton 3 : Rouge sombre/transparent (Documentation) */
    .st-key-nav_doc button {{
        background: rgba(220, 53, 69, 0.16) !important;
        border: 1px solid rgba(220, 53, 69, 0.45) !important;
        opacity: {op_doc} !important;
    }}
    .st-key-nav_doc button:hover {{
        background: rgba(220, 53, 69, 0.26) !important;
        opacity: {hov_doc} !important;
    }}
    </style>
""", unsafe_allow_html=True)

# --- BARRE DE NAVIGATION EN HAUT ---
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("📊 Dashboard", use_container_width=True, key="nav_dashboard"):
        st.switch_page(dashboard_page)

with col2:
    if st.button("💡 Insights", use_container_width=True, key="nav_insights"):
        st.switch_page(insights_page)

with col3:
    if st.button("📝 Documentation", use_container_width=True, key="nav_doc"):
        st.switch_page(doc_page)

st.markdown("<br>", unsafe_allow_html=True) 

# --- EXÉCUTION DE LA PAGE ACTUELLE ---
pg.run()