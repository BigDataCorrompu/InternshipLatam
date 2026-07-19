import re
import streamlit as st
import streamlit.components.v1 as components
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOCS_ORDER = {
    "👋 Exemple Prompt to use": "StreamlitPrompt.md",
    "🏠 Project Overview": "ProjectOverview.md",
    "⚙️ Pipeline": "Pipeline.md",
    "🥉 Bronze Layer": "BronzeTable.md",
    "🥈 Silver Layer": "SilverTables.md",
    "🥇 Gold Layer": "GoldTable.md",
    "🦜 Data enrichment AI powered with LangGraph": "LangGraph_architecture.md",
    "📊 Streamlit Cloud Interface AI powered by Groq": "StreamLit.md",
    "💰 Cost & LLM Strategy": "CostLLM.md",
    "🔌 API Explanation": "ApiExplanation.md"
}

def load_markdown(filename):
    file_path = PROJECT_ROOT / "docs" / filename
    if file_path.exists():
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    return f"⚠️ **Error:** The file `{filename}` was not found."

def render_markdown_with_mermaid(markdown_content):
    """Découpe le Markdown pour afficher le texte normalement et compiler Mermaid."""
    # Regex pour isoler les blocs ```mermaid ... ```
    parts = re.split(r'(```mermaid\n[\s\S]*?\n```)', markdown_content)
    
    for part in parts:
        if part.strip().startswith('```mermaid'):
            # On nettoie pour ne garder que le code du schéma
            mermaid_code = part.replace('```mermaid\n', '').replace('\n```', '').strip()
            
            # Injection HTML avec le CDN officiel de Mermaid.js
            html_code = f"""
            <div class="mermaid" style="display: flex; justify-content: center; background-color: transparent;">
                {mermaid_code}
            </div>
            <script type="module">
                import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
                mermaid.initialize({{ 
                    startOnLoad: true, 
                    theme: 'dark',
                    securityLevel: 'loose'
                }});
            </script>
            """
            # Rendu du composant graphique (ajuste height selon la taille de tes schémas)
            components.html(html_code, height=500, scrolling=True)
        else:
            # Rendu du Markdown textuel classique
            if part.strip():
                st.markdown(part, unsafe_allow_html=True)

# --- Interface Streamlit ---
st.sidebar.title("📚 Documentation")
selected_doc_name = st.sidebar.radio("Select a section:", list(DOCS_ORDER.keys()))

# Chargement du contenu brut
target_file = DOCS_ORDER[selected_doc_name]
raw_content = load_markdown(target_file)

# Affichage intelligent (Texte + Graphiques compilés)
render_markdown_with_mermaid(raw_content)

