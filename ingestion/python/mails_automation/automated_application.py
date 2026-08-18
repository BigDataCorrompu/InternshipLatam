"""
llm.py — génération de paragraphes personnalisés via un modèle LangChain,
et résolution du greeting (nom du contact ou formule générique).

Le modèle est passé en paramètre comme une INSTANCE LangChain déjà
configurée (ex: LLM().smart depuis ta classe LLM à rôles), pas un nom de
modèle en string. Appelable directement depuis un DAG avec le rôle de ton
choix (llm.smart, llm.fast, etc.), ou depuis un petit script de test à côté
sans rien modifier ici.

Seule responsabilité de ce module : transformer une liste de paragraphes
mixte (statique + placeholders LLM) en une liste de chaînes prêtes à
l'emploi, et résoudre le greeting. Ne fait AUCUN formatage (ni PDF, ni
email) — ça reste dans pdf_maker.py et email_maker.py.

Format attendu pour une liste de paragraphes (dans email_content.yaml ou
letter_content.yaml) — LISTE UNIQUE, chaque élément est SOIT :
    - une chaîne  -> paragraphe statique, utilisé tel quel
    - un dict {"llm": "<instruction>"} -> généré par le modèle fourni, avec
      en contexte le profil candidat (candidate_skills.yaml) et l'offre
      ciblée (job_context)

Dépendances (à ajouter dans requirements-airflow.txt) :
    pyyaml, + le/les packages langchain correspondant au modèle utilisé
    (ex: langchain-mistralai)
"""

import yaml
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage


SYSTEM_PROMPT = """You are helping draft a single paragraph for a job application
(email or cover letter). Respond ONLY with the paragraph text — no preamble, no
markdown, no quotation marks, no labels. Keep it professional, concise, and natural,
never generic or robotic. Write in English. Never invent facts about the candidate
or the company beyond what is given in the context below."""


def generate_llm_paragraph(
    instruction: str,
    skills: dict,
    job_context: dict,
    model: BaseChatModel,
) -> str:
    """
    Génère un paragraphe unique via le modèle LangChain fourni, ancré sur
    le contexte candidat + offre.

    Args:
        instruction: l'instruction spécifique à ce paragraphe (valeur de "llm" dans le YAML)
        skills: contenu de candidate_skills.yaml
        job_context: contexte de l'offre ciblée (depuis Silver ou un dict de test)
        model: instance LangChain déjà configurée, ex: LLM().smart
    """
    user_prompt = f"""
Candidate profile (structured facts, do not invent beyond this):
{yaml.dump(skills, allow_unicode=True, sort_keys=False)}

Job context (the position being applied to):
{yaml.dump(job_context, allow_unicode=True, sort_keys=False)}

Instruction for this specific paragraph:
{instruction}
"""

    response = model.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])

    return response.content.strip()


def resolve_paragraphs(
    body_paragraphs: list,
    skills: dict,
    job_context: dict,
    model: BaseChatModel,
) -> list[str]:
    """
    Parcourt une liste de paragraphes mixte et retourne des chaînes prêtes à
    l'emploi. Ne connaît jamais la structure à l'avance : ajouter/retirer/
    réordonner des paragraphes (statiques ou LLM) se fait uniquement dans le
    YAML source, sans toucher à ce fichier.
    """
    resolved = []

    for item in body_paragraphs:
        if isinstance(item, str):
            resolved.append(item)

        elif isinstance(item, dict) and "llm" in item:
            generated_text = generate_llm_paragraph(item["llm"], skills, job_context, model)
            resolved.append(generated_text)

        else:
            raise ValueError(
                f"Élément de body_paragraphs non reconnu (ni texte, ni dict 'llm'): {item!r}"
            )

    return resolved


def resolve_greeting(content: dict, job_context: dict) -> dict:
    """
    Remplace le greeting par défaut si un contact nommé est disponible dans
    job_context. Fonctionne aussi bien pour email_content que letter_content
    (les deux ont un champ "greeting_line") — même fonction pour les deux,
    pas de duplication.

    Si job_context["contact_name"] est renseigné -> "Dear {contact_name},"
    Sinon -> garde la valeur par défaut définie dans le YAML (ex:
    "To whom it may concern,"), sans y toucher.
    """
    contact_name = job_context.get("contact_name")

    if contact_name:
        content = {
            **content,
            "greeting_line": f"Dear {contact_name},",
        }

    return content


# ---------------------------------------------------------------------------
# Test rapide et indépendant.
# Change MODEL ci-dessous pour tester un autre rôle/provider sans toucher
# aux fonctions ci-dessus. Suppose que ta classe LLM (voir ton module
# existant, ex: from llm_provider import LLM) est disponible.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from llm_provider import LLM  # ta classe à rôles existante

    MODEL = LLM().smart  # change ici: LLM().fast, LLM().enrichement, etc.

    def load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    skills = load_yaml("candidate_skills.yaml")
    letter_content = load_yaml("letter_content.yaml")

    # --- Cas 1 : pas de contact nommé -> garde "To whom it may concern," ---
    example_job_context_no_contact = {
        "company_name": "Mercado Libre",
        "city": "Buenos Aires",
        "country": "Argentina",
        "sector": "E-commerce",
        "related_job_titles": ["Data Engineer Intern", "Junior Data Engineer"],
        "seniority": "Internship",
        "contact_name": None,
        "contact_title": None,
    }

    # --- Cas 2 : contact nommé -> "Dear Al Pratt," ---
    example_job_context_with_contact = {
        **example_job_context_no_contact,
        "contact_name": "Al Pratt",
        "contact_title": "Asst Vice President",
    }

    for label, job_context in [
        ("SANS contact", example_job_context_no_contact),
        ("AVEC contact", example_job_context_with_contact),
    ]:
        print(f"=== {label} ===")

        letter_resolved = resolve_greeting(letter_content, job_context)
        print("greeting_line:", letter_resolved["greeting_line"])

        resolved_paragraphs = resolve_paragraphs(
            letter_content["body_paragraphs"], skills, job_context, model=MODEL
        )
        print(f"({len(resolved_paragraphs)} paragraphes résolus)")
        print()