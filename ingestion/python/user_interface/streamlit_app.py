import streamlit as st
from pathlib import Path

# 1. On récupère le dossier exact où se trouve streamlit_app.py
CURRENT_DIR = Path(__file__).parent

# 2. On construit les chemins absolus vers tes pages
dashboard_path = CURRENT_DIR / "views" / "dashboard.py"
doc_path = CURRENT_DIR / "views" / "doc.py"
# Doit être la TOUTE PREMIÈRE ligne de code Streamlit
st.set_page_config(
    page_title="InternshipLatam Dashboard",
    layout="wide", # C'est ça qui va étirer l'affichage
    initial_sidebar_state="expanded"
)
# 3. Définition des pages (on convertit en chaîne de caractères avec str())
dashboard_page = st.Page(
    page=str(dashboard_path), 
    title="Tableau de bord", 
    icon="📊", 
    default=True
)

doc_page = st.Page(
    page=str(doc_path), 
    title="Documentation (README)", 
    icon="📝"
)

# Le reste de ton code de navigation reste identique
pg = st.navigation([dashboard_page, doc_page])
pg.run()