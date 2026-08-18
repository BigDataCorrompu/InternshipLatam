"""
email_maker.py — formatage du contenu texte d'un email de candidature.

Seule responsabilité de ce module : prendre un contexte déjà résolu
(paragraphes déjà en chaînes, aucun dict "llm" restant) et assembler
subject + body prêts à envoyer. La résolution des paragraphes LLM se fait
en amont, dans llm.py.

Prérequis :
    pip install jinja2 pyyaml

Utilisation directe (test avec des paragraphes statiques uniquement) :
    python email_maker.py
    -> lit candidate_info.yaml + email_content.yaml
    -> si email_content.yaml contient des dicts "llm", ils sont affichés
       en brut — utiliser email_sender.py pour un rendu complet avec
       résolution LLM

Utilisation en import (depuis email_sender.py ou un DAG Airflow) :
    from email_maker import build_context, render_email

    context = build_context(profile, email_content)
    context["body_paragraphs"] = resolved_paragraphs  # déjà résolus via llm.py
    email = render_email(context)
    # email == {"subject": "...", "body": "..."}
"""

import yaml
from jinja2 import Template

# ---------------------------------------------------------------------------
# Template texte brut — email professionnel simple, pas de HTML.
# Les emails de candidature restent en texte brut pour une meilleure
# délivrabilité (moins de risque de filtre spam qu'un email HTML riche).
# ---------------------------------------------------------------------------

email_template = Template("""{{ greeting_line }}

{{ body_text }}

{{ closing_line }}

{{ candidate_first_name }} {{ candidate_last_name }}
{{ candidate_phone }}
{{ candidate_email }}
{{ links_text }}""")


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_context(profile: dict, email_content: dict) -> dict:
    return {
        **profile,
        **email_content,
    }


def render_email(context: dict) -> dict:
    """
    Retourne {"subject": ..., "body": ...} prêt à être passé à gmail_client.py.
    context['body_paragraphs'] doit être une liste de chaînes (str) —
    aucun dict "llm" ne doit subsister à ce stade.
    """
    subject = Template(context["subject_line"]).render(**context).strip()

    render_context = {
        **context,
        "body_text": "\n\n".join(context["body_paragraphs"]),
        "links_text": "\n".join(context["candidate_links"]),
    }
    body = email_template.render(**render_context).strip()

    return {"subject": subject, "body": body}


if __name__ == "__main__":
    # Test rapide sans résolution LLM — utiliser email_sender.py pour un
    # rendu complet avec les paragraphes LLM résolus.
    profile = load_yaml("candidate_info.yaml")
    email_content = load_yaml("email_content.yaml")

    context = build_context(profile, email_content)
    email = render_email(context)

    print("=== SUBJECT ===")
    print(email["subject"])
    print("\n=== BODY ===")
    print(email["body"])