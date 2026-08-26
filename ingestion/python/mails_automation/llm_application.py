"""
llm.py — génération de contenu personnalisé via un modèle LangChain, en un
SEUL appel par document (email ou lettre), plutôt qu'un appel par paragraphe.

Pourquoi un seul appel plutôt qu'un par paragraphe :
    - Le LLM voit toutes les instructions en même temps -> il peut répartir
      le contenu sans se répéter, au lieu d'écrire chaque paragraphe "à
      l'aveugle" sur ce qui suit.
    - Un seul appel = un seul prompt = cache de préfixe plus simple et plus
      efficace (skills + toutes les instructions restent un bloc stable
      entre offres, seul job_context change).
    - Moins d'appels API = moins de latence et de coût.

Le modèle est passé en paramètre comme une INSTANCE LangChain déjà
configurée (ex: LLM().smart), pas un nom de modèle en string.

Format attendu pour une liste de paragraphes (dans email_content.yaml ou
letter_content.yaml) — LISTE UNIQUE, chaque élément est SOIT :
    - une chaîne  -> paragraphe statique, utilisé tel quel, jamais touché par le LLM
    - un dict {"llm": "<instruction>"} -> à générer

Le schéma de sortie (GeneratedContent) utilise une LISTE de paragraphes
(pas des champs nommés fixes) : le nombre d'instructions LLM peut varier
librement dans le YAML sans jamais devoir modifier ce fichier.

Dépendances (à ajouter dans requirements-airflow.txt) :
    pyyaml, pydantic, + le package langchain du provider utilisé
    (ex: langchain-mistralai)
"""

import yaml
from pydantic import BaseModel, Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import SystemMessage, HumanMessage
import re
from tenacity import retry, stop_after_attempt
# ---------------------------------------------------------------------------
# Schéma de sortie structuré
# ---------------------------------------------------------------------------

class GeneratedParagraph(BaseModel):
    instruction_index: int = Field(
        ...,
        description=(
            "The number (1-based) of the instruction this paragraph answers, "
            "matching the numbered list of instructions given in the prompt."
        ),
    )
    text: str = Field(
        ...,
        description="The generated paragraph text for this instruction.",
    )


class GeneratedContent(BaseModel):
    greeting_line: str = Field(
        ...,
        description=(
            "The salutation line. Look at job_context['contact_explanation'] and "
            "job_context['contact_email'] — if either contains an identifiable "
            "person's name, use it in the greeting as full name (e.g. 'Dear Anna "
            "Langenus,'). Only use a title like 'Mr.' or 'Ms.' if the gender is "
            "explicitly stated in the given context (e.g. a title already present "
            "in contact_explanation) — never infer gender from a first name alone, "
            "as this risks being wrong. If no name can be reliably identified, use "
            "the given default greeting unchanged — do not guess or invent a name."
        ),
    )
    paragraphs: list[GeneratedParagraph] = Field(
        ...,
        description=(
            "The generated paragraphs, one per numbered instruction. Must "
            "contain exactly one entry per instruction, each tagged with "
            "its instruction_index — order in this list does not matter, "
            "the index is what determines placement."
        ),
    )


SYSTEM_PROMPT = """You are helping draft the personalized content of a job
application (email or cover letter), written on behalf of a candidate seeking
a Data Engineering internship.

Rules:
- Write like a human would: natural, warm but professional, varied sentence
  structure. Avoid generic, robotic, or overly formal corporate phrasing.
- Never invent facts about the candidate or the company beyond what is given
  in the context below.
- You are given the FULL set of paragraphs to write for this document at
  once, plus the static paragraphs already fixed in the document. Use this
  to avoid repeating the same ideas, facts, or phrasing across paragraphs —
  each paragraph must add something new and distinct.
- Write in English.
- Keep each paragraph concise: 3 to 5 sentences maximum. The full letter
  must fit on a single page — favor precision over exhaustiveness.
- CRITICAL: output PLAIN TEXT ONLY. Never use markdown formatting of any
  kind — no asterisks for bold or italics (**word** or *word*), no
  underscores, no bullet points, no headers, no backticks. Company names,
  job titles, cities, and skills must appear as normal plain text, never
  emphasized or highlighted. This text will be inserted directly into an
  email or a PDF document — any markdown syntax will appear as literal
  stray characters to the reader.
- Never use em dashes (—) or en dashes with spaces as punctuation. Use
  commas, periods, or parentheses instead.
- Follow the JSON output schema exactly: one greeting line, and one
  paragraph per numbered instruction, in the same order.
- Write like a human would: natural, varied sentence rhythm, no robotic or
  overly polished corporate tone.
  """


# ---------------------------------------------------------------------------
# Appel unique : génère le greeting + tous les paragraphes LLM d'un document
# ---------------------------------------------------------------------------

def clean_llm_text(text: str) -> str:
    """Nettoie les artefacts stylistiques typiques des LLM (filet de sécurité,
    en complément des consignes du SYSTEM_PROMPT)."""
    # Em dash (—) et en dash (–) avec espaces -> virgule
    text = re.sub(r'\s*[—–]\s*', ', ', text)
    # Markdown gras/italique -> texte brut
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    return text

@retry(stop=stop_after_attempt(3))
def generate_document_content(
    static_paragraphs: list[str],
    llm_instructions: list[str],
    default_greeting: str,
    skills: dict,
    job_context: dict,
    model: BaseChatModel,
) -> GeneratedContent:
    """
    Un seul appel LLM pour tout le document (email ou lettre).

    Args:
        static_paragraphs: les paragraphes déjà fixes du document (pour contexte,
            afin d'éviter les répétitions — ne sont jamais réécrits).
        llm_instructions: la liste des instructions "llm:" du YAML, dans l'ordre
            d'apparition dans body_paragraphs.
        default_greeting: la valeur greeting_line par défaut du YAML.
        skills: contenu de candidate_skills.yaml.
        job_context: contexte de l'offre ciblée (contact_name, company_name, city, etc.).
        model: instance LangChain déjà configurée, ex: LLM().smart.

    Returns:
        GeneratedContent(greeting_line=..., paragraphs=[...])
    """
    structured_model = model.with_structured_output(GeneratedContent)

    static_context = ""
    if static_paragraphs:
        joined = "\n---\n".join(static_paragraphs)
        static_context = f"""
Static paragraphs already fixed in this document (for context only — do not
repeat their ideas, facts, or phrasing; never rewrite them):
{joined}
"""

    numbered_instructions = "\n".join(
        f"{i + 1}. {instr}" for i, instr in enumerate(llm_instructions)
    )

    user_prompt = f"""
Candidate profile (structured facts, do not invent beyond this):
{yaml.dump(skills, allow_unicode=True, sort_keys=False)}

Job context (the position being applied to):
{yaml.dump(job_context, allow_unicode=True, sort_keys=False)}

Default greeting line (use as-is if no named contact is available):
{default_greeting}
{static_context}
Paragraphs to write ({len(llm_instructions)} total, in this exact order):
{numbered_instructions}
"""

    result = structured_model.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ])

    result.greeting_line = clean_llm_text(result.greeting_line)
    for p in result.paragraphs:
        p.text = clean_llm_text(p.text)

    if len(result.paragraphs) != len(llm_instructions):
        raise ValueError(
            f"Le LLM a retourné {len(result.paragraphs)} paragraphe(s), "
            f"{len(llm_instructions)} attendu(s)."
        )

    return result


# ---------------------------------------------------------------------------
# Résolution complète d'un document : sépare statique/LLM, appelle le LLM
# une fois, réinjecte les paragraphes générés à leur position d'origine.
# ---------------------------------------------------------------------------
def resolve_document(
    body_paragraphs: list,
    default_greeting: str,
    skills: dict,
    job_context: dict,
    model: BaseChatModel,
) -> dict:
    """
    Résout un document entier (email_content ou letter_content) en un seul
    appel LLM.

    Args:
        body_paragraphs: liste brute du YAML (str ou {"llm": "..."})
        default_greeting: valeur de greeting_line dans le YAML

    Returns:
        {
            "greeting_line": "...",
            "body_paragraphs": [...]  # liste de str, prête pour le formatage
        }
    """
    static_paragraphs = [p for p in body_paragraphs if isinstance(p, str)]
    llm_instructions = [p["llm"] for p in body_paragraphs if isinstance(p, dict) and "llm" in p]

    if not llm_instructions:
        # Rien à générer : document 100% statique, pas d'appel LLM nécessaire
        return {
            "greeting_line": default_greeting,
            "body_paragraphs": static_paragraphs,
        }

    generated = generate_document_content(
        static_paragraphs=static_paragraphs,
        llm_instructions=llm_instructions,
        default_greeting=default_greeting,
        skills=skills,
        job_context=job_context,
        model=model,
    )

    # Vérifie qu'on a bien exactement un paragraphe par instruction, sans
    # doublon ni trou dans les instruction_index reçus.
    expected_indices = set(range(1, len(llm_instructions) + 1))
    received_indices = {p.instruction_index for p in generated.paragraphs}

    if received_indices != expected_indices:
        raise ValueError(
            f"Indices de paragraphes incohérents. Attendus: {sorted(expected_indices)}, "
            f"reçus: {sorted(received_indices)}"
        )

    # Mappe par instruction_index plutôt que de faire confiance à l'ordre
    # brut retourné par le LLM.
    paragraphs_by_index = {p.instruction_index: p.text for p in generated.paragraphs}

    # Réinjecte les paragraphes générés à leur position d'origine dans la liste
    resolved = []
    llm_position = 0
    for item in body_paragraphs:
        if isinstance(item, str):
            resolved.append(item)
        elif isinstance(item, dict) and "llm" in item:
            llm_position += 1
            resolved.append(paragraphs_by_index[llm_position])
        else:
            raise ValueError(
                f"Élément de body_paragraphs non reconnu (ni texte, ni dict 'llm'): {item!r}"
            )

    return {
        "greeting_line": generated.greeting_line,
        "body_paragraphs": resolved,
    }

# ---------------------------------------------------------------------------
# Test rapide et indépendant.
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from llm_provider import LLM  # ta classe à rôles existante

    MODEL = LLM().smart  # change ici: LLM().fast, LLM().enrichement, etc.

    def load_yaml(path):
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    skills = load_yaml("candidate_skills.yaml")
    letter_content = load_yaml("letter_content.yaml")

    for label, job_context in [
        ("SANS contact", {
            "company_name": "Mercado Libre",
            "city": "Buenos Aires",
            "country": "Argentina",
            "sector": "E-commerce",
            "related_job_titles": ["Data Engineer Intern", "Junior Data Engineer"],
            "seniority": "Internship",
            "contact_name": None,
            "contact_title": None,
        }),
        ("AVEC contact", {
            "company_name": "Mercado Libre",
            "city": "Buenos Aires",
            "country": "Argentina",
            "sector": "E-commerce",
            "related_job_titles": ["Data Engineer Intern", "Junior Data Engineer"],
            "seniority": "Internship",
            "contact_name": "Al Pratt",
            "contact_title": "Asst Vice President",
        }),
    ]:
        print(f"=== {label} ===")

        result = resolve_document(
            body_paragraphs=letter_content["body_paragraphs"],
            default_greeting=letter_content["greeting_line"],
            skills=skills,
            job_context=job_context,
            model=MODEL,
        )

        print("greeting_line:", result["greeting_line"])
        for i, paragraph in enumerate(result["body_paragraphs"], 1):
            print(f"--- Paragraphe {i} ---")
            print(paragraph)
        print()