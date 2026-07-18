import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).parent
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # au lieu de parents[4]
SRC_DIR = PROJECT_ROOT / "ingestion" / "python" / "src"
DOC_DIR = PROJECT_ROOT / "docs"

sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(DOC_DIR))
import streamlit as st

dashboard_path = CURRENT_DIR / "views" / "dashboard.py"
doc_path = CURRENT_DIR / "views" / "doc.py"

st.set_page_config(
    page_title="InternshipLatam Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

dashboard_page = st.Page(page=str(dashboard_path), title="Dashboard", icon="📊", default=True)
doc_page = st.Page(page=str(doc_path), title="Documentation (README)", icon="📝")

pg = st.navigation([dashboard_page, doc_page])
pg.run()