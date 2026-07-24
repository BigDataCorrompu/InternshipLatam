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

# ── Social links, fixed top-left, visible on every page ──
st.markdown("""
<style>
    .top-left-social {
        position: fixed;
        top: 15px;
        left: 15px;
        z-index: 999999;
        display: flex;
        flex-direction: column;
        gap: 10px;
    }
    .social-badge {
        display: flex;
        align-items: center;
        gap: 10px;
        background: linear-gradient(135deg, #ff4b4b22, #ff4b4b11);
        border: 1px solid #ff4b4b55;
        border-radius: 10px;
        padding: 8px 14px;
        text-decoration: none;
        transition: all 0.2s ease;
    }
    .social-badge:hover {
        background: #ff4b4b33;
        border-color: #ff4b4b;
        transform: translateX(3px);
    }
    .social-badge svg { flex-shrink: 0; color: #ffffff; }
    .social-badge .label {
        display: flex;
        flex-direction: column;
        line-height: 1.15;
    }
    .social-badge .label .main {
        font-size: 13px;
        font-weight: 600;
        color: #ffffff;
    }
    .social-badge .label .sub {
        font-size: 10px;
        color: #d0d0d0;
    }
</style>
<div class="top-left-social">
    <a href="https://www.linkedin.com/in/roland-oucherif/" target="_blank" class="social-badge">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
            <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433c-1.144 0-2.063-.926-2.063-2.065 0-1.138.92-2.063 2.063-2.063 1.14 0 2.064.925 2.064 2.063 0 1.139-.925 2.065-2.064 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
        </svg>
        <span class="label">
            <span class="main">Roland Oucherif</span>
            <span class="sub">My LinkedIn profile</span>
        </span>
    </a>
    <a href="https://github.com/BigDataCorrompu/InternshipLatam" target="_blank" class="social-badge">
        <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
        </svg>
        <span class="label">
            <span class="main">GitHub</span>
            <span class="sub">Project source code</span>
        </span>
    </a>
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