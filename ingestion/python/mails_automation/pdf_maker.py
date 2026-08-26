"""
Génération d'une lettre de motivation en PDF avec xhtml2pdf.

Les paragraphes du corps ne sont plus limités à un nombre fixe : ils sont
lus comme une liste depuis un fichier YAML, avec une boucle Jinja2. Le
nombre de paragraphes peut donc varier librement d'une lettre à l'autre
sans toucher au code.

Prérequis :
    pip install jinja2 xhtml2pdf pyyaml

Utilisation :
    python pdf_maker.py
    -> lit candidate_profile.yaml + letter_content.yaml
    -> produit cover_letter.pdf dans le dossier courant
"""

import yaml
from jinja2 import Template
from xhtml2pdf import pisa
from pypdf import PdfReader
# ---------------------------------------------------------------------------
# Template HTML/CSS — mise en page fixe, un seul endroit à ajuster le style
# Note : xhtml2pdf supporte un sous-ensemble de CSS (moins complet que
# WeasyPrint) — flexbox/grid ne sont pas supportés, rester sur des blocs
# simples (margin, padding, font, text-align) comme ci-dessous.
# ---------------------------------------------------------------------------

html_template = Template("""
<html>
<head>
<style>
    body {
        font-family: 'Helvetica', sans-serif;
        font-size: {{ body_font_size }}pt;
        line-height: {{ body_line_height }};
        color: #1a1a1a;
    }
    /* Barre bleue tout en haut du document, pleine largeur */
    .top-bar {
        background-color: #5b8fc7;
        height: 2px;
        width: 100%;
        margin-bottom: 22px;
    }
    /* Bloc nom : Prenom au-dessus de NOM, police douce et arrondie, en bleu */
    .name-block {
        width: 40%;
        font-family: 'Trebuchet MS', 'Verdana', sans-serif;
    }
    .name-block .first-name {
        font-size: 24pt;
        font-weight: bold;
        line-height: 1.1;
        color: #1a4d8f;
    }
    .name-block .last-name {
        font-size: 24pt;
        font-weight: bold;
        letter-spacing: 1px;
        line-height: 1.1;
        color: #1a4d8f;
    }
    /* Bloc coordonnées compact, coin haut droit */
    .contact-block {
        width: 60%;
        text-align: right;
        font-size: 8pt;
        color: #555555;
        line-height: 1.4;
        white-space: nowrap;
    }
    .header-table {
        width: 100%;
        margin-bottom: 6px;
    }
    .header-table td {
        vertical-align: top;
    }
    /* Ligne "qui je suis" (statut) */
    .status-line {
        font-size: 13pt;
        font-style: italic;
        color: #1a1a1a;
        margin-top: 20px;
        margin-bottom: 4px;
    }
    /* Zone objectif, sous le header — en gras */
    .objective-zone {
        font-size: 13pt;
        font-weight: bold;
        color: #333333;
        margin-bottom: 14px;
    }
    /* Barre bleue sous la ligne "objective" */
    .objective-bar {
        background-color: #1a4d8f;
        height: 3px;
        width: 100%;
        margin-bottom: 4px;
    }
    .date-line {
        font-size: 9.5pt;
        color: #777777;
        margin-top: 6px;
        margin-bottom: 0px;
    }
    .greeting {
        margin-top: 22px;
        margin-bottom: 16px;
    }
    p {
        margin-bottom: 14px;
        text-align: justify;
    }
    .signature {
        margin-top: 24px;
    }
    @page {
        size: letter;
        margin: 1.2cm 2.5cm 2.2cm 2.5cm;
    }
</style>
</head>
<body>
    <div class="top-bar"></div>

    <table class="header-table">
        <tr>
            <td class="name-block">
                <div class="first-name">{{ candidate_first_name }}</div>
                <div class="last-name">{{ candidate_last_name }}</div>
            </td>
            <td class="contact-block">
                {% for address in candidate_addresses %}{{ address }}<br/>{% endfor %}
                {{ candidate_email }}<br/>
                {{ candidate_phone }}<br/>
                {% for link in candidate_links %}{{ link }}<br/>{% endfor %}
            </td>
        </tr>
    </table>

    <div class="date-line">{{ letter_date }}</div>

    <div class="status-line">{{ status_line }}</div>

    <div class="objective-zone">{{ objective_line }}</div>

    <div class="objective-bar"></div>

    <div class="greeting">{{ greeting_line }}</div>

    {% for paragraph in body_paragraphs %}
    <p>{{ paragraph }}</p>
    {% endfor %}

    <div class="signature">
        Sincerely,<br/>
        {{ candidate_first_name }} {{ candidate_last_name }}
    </div>
</body>
</html>
""")

# ---------------------------------------------------------------------------
# Chargement de la config depuis YAML
#   - candidate_profile.yaml : identité, coordonnées (change rarement)
#   - letter_content.yaml    : contenu de la lettre, paragraphes en liste
#     (peut varier par candidature, notamment une fois le LLM branché)
# ---------------------------------------------------------------------------

def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def count_pdf_pages(path: str) -> int:
    reader = PdfReader(path)
    return len(reader.pages)

def render_pdf_raw(context: dict, output_path: str) -> None:
    """
    Rendu PDF brut, sans logique de réduction de page. context doit déjà
    contenir body_font_size et body_line_height. Ne fait qu'un rendu, ne
    vérifie rien — c'est render_pdf() qui orchestre la boucle de réduction.
    """
    html_content = html_template.render(**context)
 
    with open(output_path, "wb") as pdf_file:
        result = pisa.CreatePDF(html_content, dest=pdf_file)
 
    if result.err:
        raise RuntimeError(f"Erreur lors de la génération du PDF ({result.err} erreur(s))")
 
 
def render_pdf(
    context: dict,
    output_path: str = "cover_letter.pdf",
    font_sizes: list[tuple[float, float]] = None,
) -> str:
    """
    Rend le PDF en essayant des tailles de police décroissantes jusqu'à
    tenir sur une page. font_sizes est une liste de (font_size, line_height)
    du plus grand au plus petit — s'arrête au premier qui tient, ou garde
    le dernier essai (le plus petit) si aucun ne suffit.
    """
    if font_sizes is None:
        font_sizes = [
            (11, 1.5),
            (10.5, 1.45),
            (10, 1.4),
            (9.5, 1.35),
        ]
 
    for font_size, line_height in font_sizes:
        render_context = {
            **context,
            "body_font_size": font_size,
            "body_line_height": line_height,
        }
        render_pdf_raw(render_context, output_path)
 
        page_count = count_pdf_pages(output_path)
        if page_count <= 1:
            print(f"✅ PDF généré : {output_path} ({font_size}pt, 1 page)")
            return output_path
 
    print(
        f"⚠️ PDF généré : {output_path} — ne tient toujours pas sur une page "
        f"même à {font_sizes[-1][0]}pt. Contenu probablement trop long, "
        f"raccourcir un paragraphe."
    )
    return output_path
 
if __name__ == "__main__":
    # Test rapide sans résolution LLM : les paragraphes {"llm": ...} restants
    # dans letter_content.yaml seraient affichés en brut (dict Python) si
    # présents — utiliser email_sender.py pour un rendu complet.
    profile = load_yaml("candidate_info.yaml")
    letter = load_yaml("letter_content.yaml")
 
    context = {**profile, **letter}
    render_pdf(context)