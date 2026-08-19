"""
test/test_automated_application.py

Test de bout en bout de la génération de contenu de candidature :
    1. Requête directe en base (schéma analytics/Silver, jointures complètes)
       pour récupérer une vraie offre avec entreprise, localisation, exigences
       et contact
    2. Charge les YAML de config (profil, compétences, contenu email/lettre)
    3. Appelle le LLM (rôle `application`) pour résoudre email + lettre en un
       seul appel chacun
    4. Formate et écrit les résultats dans test_application/ :
         - cover_letter.pdf
         - email.txt (objet + corps)
       Aucun envoi réel — juste une inspection visuelle des sorties.

Utilise MISTRAL_TEST_KEY (pas MISTRAL_API_KEY) pour ne jamais consommer le
quota/clé de production pendant les tests.

⚠️ Chemins à vérifier avant de lancer :
   CONFIG_DIR suppose que les YAML sont dans
   ingestion/python/mails_automation/config/ — ajuste si ce n'est pas le cas.

Utilisation :
    python test/test_automated_application.py
"""

import os
import sys
from pathlib import Path

import yaml
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Résolution des chemins (relatifs à ce fichier, pas au cwd)
# ---------------------------------------------------------------------------

TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent

MAILS_DIR = PROJECT_ROOT / "ingestion" / "python" / "mails_automation"
SRC_DIR = PROJECT_ROOT / "ingestion" / "python" / "src"  # là où vit LLMprovider
CONFIG_DIR = PROJECT_ROOT / "ingestion" / "config"  # ⚠️ ajuste si les YAML sont ailleurs

OUTPUT_DIR = TEST_DIR / "test_application"
OUTPUT_DIR.mkdir(exist_ok=True)

# Permet d'importer les modules depuis les deux dossiers
sys.path.insert(0, str(MAILS_DIR))
sys.path.insert(0, str(SRC_DIR))

from llm_application import resolve_document  # noqa: E402
from LLMprovider import LLM  # noqa: E402  (nom du fichier avec cette casse exacte)
from pdf_maker import render_pdf  # noqa: E402
from email_maker import build_context, render_email  # noqa: E402


# ---------------------------------------------------------------------------
# Chargement config / secrets
# ---------------------------------------------------------------------------

load_dotenv()

MISTRAL_TEST_KEY = os.environ["MISTRAL_TEST_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]  # ⚠️ adapte le nom si différent


def load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Récupération d'une offre complète depuis la base (analytics/Silver),
# avec toutes les jointures nécessaires pour donner un contexte riche au LLM.
# ---------------------------------------------------------------------------

def fetch_sample_job_posting() -> dict:
    """
    Récupère une offre au hasard, avec entreprise, localisation, exigences
    (job_requirement) et un contact email si disponible. Basé sur le schéma
    002_init_silver.sql (analytics.job_offer / company / company_location /
    job_requirement / company_contact).
    """
    query = """
        SELECT
            jo.id_offer,
            jo.job_title,
            jo.offer_description,
            jo.contract_type,
            jo.is_remote,

            c.company_name,

            cl.city,
            cl.country,

            jr.alternative_job_titles,
            jr.offer_languages,
            jr.seniority,
            jr.skills_languages,
            jr.skills_frameworks,
            jr.skills_aptitudes,
            jr.skills_soft,

            jrel.score_relevancy,
            jrel.explanation AS relevancy_explanation,

            cc.email AS contact_email,
            cc.explanation AS contact_explanation

        FROM analytics.job_offer jo
        JOIN analytics.company c
            ON jo.id_company = c.id_company
        LEFT JOIN analytics.company_location cl
            ON jo.id_location = cl.id_location
        LEFT JOIN analytics.job_requirement jr
            ON jr.id_offer = jo.id_offer
        LEFT JOIN analytics.job_relevancy jrel
            ON jrel.id_offer = jo.id_offer
        LEFT JOIN analytics.company_contact cc
            ON cc.id_company = c.id_company
           AND (cc.id_location = cl.id_location OR cc.id_location IS NULL)

        WHERE c.company_name IS NOT NULL
          AND cl.city IS NOT NULL

        ORDER BY random()
        LIMIT 1;
    """

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            row = cur.fetchone()

    if row is None:
        raise RuntimeError("Aucune offre trouvée en base pour le test.")

    return {
        "offer_id": row["id_offer"],
        "job_title": row["job_title"],
        "offer_description": row.get("offer_description") or "",
        "contract_type": row.get("contract_type") or "unspecified",
        "is_remote": bool(row.get("is_remote")),

        "company_name": row["company_name"],


        "city": row["city"],
        "country": row.get("country") or "unknown",

        "related_job_titles": row.get("alternative_job_titles") or [],
        "offer_languages": row.get("offer_languages") or [],
        "seniority": row.get("seniority") or "unspecified",
        "skills_languages": row.get("skills_languages") or [],
        "skills_frameworks": row.get("skills_frameworks") or [],
        "skills_aptitudes": row.get("skills_aptitudes") or [],
        "skills_soft": row.get("skills_soft") or [],

        # Pas de nom de contact en base (seulement email) -> greeting générique
        "relevancy_score": row.get("score_relevancy"),
        "relevancy_explanation": row.get("relevancy_explanation") or None,



        "contact_email": row.get("contact_email") or None,
        "contact_explanation": row.get("contact_explanation") or None,
    }


# ---------------------------------------------------------------------------
# Exécution du test
# ---------------------------------------------------------------------------

def main():
    print("→ Récupération d'une offre depuis la base...")
    job_context = fetch_sample_job_posting()
    print(f"   Offre : {job_context['company_name']} — {job_context['job_title']}")
    print(f"   Lieu  : {job_context['city']}, {job_context['country']}")
    print(f"   Contact email : {job_context['contact_email'] or '(aucun)'}")

    print("\n→ Chargement des fichiers de config...")
    profile = load_yaml("candidate_info.yaml")
    skills = load_yaml("candidate_skills.yaml")
    email_content = load_yaml("email_content.yaml")
    letter_content = load_yaml("letter_content.yaml")

    print("→ Initialisation du modèle (clé de test)...")
    llm = LLM(mistral_key=MISTRAL_TEST_KEY)
    model = llm.application

    print("→ Résolution de l'EMAIL...")
    email_resolved = resolve_document(
        body_paragraphs=email_content["body_paragraphs"],
        default_greeting=email_content["greeting_line"],
        skills=skills,
        job_context=job_context,
        model=model,
    )

    print("→ Résolution de la LETTRE...")
    letter_resolved = resolve_document(
        body_paragraphs=letter_content["body_paragraphs"],
        default_greeting=letter_content["greeting_line"],
        skills=skills,
        job_context=job_context,
        model=model,
    )

    # --- Formatage email (pur, aucun appel LLM) ---
    email_content_final = {
        **email_content,
        "greeting_line": email_resolved["greeting_line"],
        "body_paragraphs": email_resolved["body_paragraphs"],
    }
    email_context = build_context(profile, email_content_final)
    email_rendered = render_email(email_context)

    # --- Formatage PDF (pur, aucun appel LLM) ---
    letter_content_final = {
        **letter_content,
        "greeting_line": letter_resolved["greeting_line"],
        "body_paragraphs": letter_resolved["body_paragraphs"],
    }
    pdf_context = {**profile, **letter_content_final}

    # --- Écriture des sorties ---
    pdf_path = OUTPUT_DIR / "cover_letter.pdf"
    render_pdf(pdf_context, output_path=str(pdf_path))

    email_path = OUTPUT_DIR / "email.txt"
    with open(email_path, "w", encoding="utf-8") as f:
        f.write(f"To: {job_context['contact_email'] or '(aucun contact trouvé)'}\n")
        f.write(f"Subject: {email_rendered['subject']}\n")
        f.write("\n" + "-" * 60 + "\n\n")
        f.write(email_rendered["body"])

    print(f"\n✅ PDF généré  : {pdf_path}")
    print(f"✅ Email écrit : {email_path}")


if __name__ == "__main__":
    main()