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

# On remet l'état étendu (expanded) pour que la barre latérale s'affiche
st.set_page_config(
    page_title="InternshipLatam Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

def render_insights():
    st.title("💡 Insights")
    st.info("Cette section est en cours de développement et n'est pas encore implémentée.")

st.markdown("""
<style>
    .top-left-social {
        position: fixed;
        top: 50px;
        left: 15px;
        z-index: 999999;
        display: flex;
        flex-direction: column;
        gap: 8px;
    }

    /* Sur mobile : ancré à la page (scrolle avec le contenu), pas au viewport */
    @media (max-width: 768px) {
        .top-left-social {
            position: absolute;
            top: 60px;
            left: 10px;
        }
    }

    .social-badge {
        display: flex;
        align-items: center;
        gap: 8px;
        background: linear-gradient(135deg, #ff4b4b22, #ff4b4b11);
        border: 1px solid #ff4b4b55;
        border-radius: 10px;
        padding: 6px 12px;
        text-decoration: none;
        transition: all 0.2s ease;
    }
    .social-badge:hover {
        background: #ff4b4b33;
        border-color: #ff4b4b;
        transform: translateX(3px);
    }
    .social-badge svg { flex-shrink: 0; color: #ffffff; width: 18px; height: 18px; }
    .social-badge .label {
        display: flex;
        flex-direction: column;
        line-height: 1.1;
    }
    .social-badge .label .main {
        font-size: 12px;
        font-weight: 600;
        color: #ffffff;
    }
    .social-badge .label .sub {
        font-size: 9px;
        color: #d0d0d0;
    }

    section[data-testid="stSidebar"] > div:first-child {
        padding-top: 140px !important;
    }
</style>
<div class="top-left-social">
    ...  <!-- garde tes deux <a> inchangés -->
</div>
""", unsafe_allow_html=True)

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
    /* On réduit l'espace en haut, mais on ne cache PLUS le header pour garder le bouton de la barre latérale */
    .block-container {{
        padding-top: 4rem !important; 
        margin-top: 0rem !important;
        padding-bottom: 0rem !important;
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