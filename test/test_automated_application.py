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
import base64
import mimetypes
from datetime import datetime
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

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

# --- Envoi Gmail (test, vers toi-même) ---
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]
TOKEN_FILE = PROJECT_ROOT / "ingestion" / "config" / "token.json"  # ⚠️ ajuste si ailleurs
LABEL_NAME = "mail_automated"
CV_PATH = PROJECT_ROOT / "ingestion" / "config" / "cv.pdf"  # ⚠️ ajuste le nom réel du CV


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
TEST_RECIPIENT = os.environ["MAIL_TEST"]  # toi-même, pas contact_email de l'offre
MISTRAL_TEST_KEY = os.environ["MISTRAL_TEST_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]  # ⚠️ adapte le nom si différent

SIMPLE_QUERY = """
        SELECT
            jo.id_offer,
            jo.id_company,
            jo.id_location,
            jo.job_title,
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
BEST_QUERY = """
        SELECT
            jo.id_offer,
            jo.id_company,
            jo.id_location,
            jo.job_title,
            jo.offer_description,
            jo.contract_type,
            jo.is_remote,
            jo.published_at,
            jo.collected_at,

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
        JOIN analytics.job_relevancy jrel
            ON jrel.id_offer = jo.id_offer
        JOIN analytics.company_contact cc
            ON cc.id_company = c.id_company
           AND (cc.id_location = cl.id_location OR cc.id_location IS NULL)

        WHERE c.company_name IS NOT NULL
          AND cl.city IS NOT NULL
          AND cc.email IS NOT NULL
          AND cc.source = 'hunter'
          AND jrel.score_relevancy > 7
          AND jo.id_offer != 'cj_7f18aaf8cdf33585886b927e97dc7092'


        ORDER BY COALESCE(jo.published_at, jo.collected_at) DESC
        LIMIT 1;
    """

def load_yaml(filename: str) -> dict:
    path = CONFIG_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Envoi Gmail — repris de email_sender.py, adapté pour envoyer vers soi-même
# en test avec le PDF et le CV réellement générés dans ce script.
# ---------------------------------------------------------------------------

def load_gmail_credentials():
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), GMAIL_SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return creds


def get_or_create_label(service, label_name: str) -> str:
    existing = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in existing:
        if label["name"] == label_name:
            return label["id"]
    created = service.users().labels().create(
        userId="me",
        body={
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        },
    ).execute()
    return created["id"]


def attach_file(message: MIMEMultipart, file_path: str):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Pièce jointe introuvable : {file_path}")

    ctype, encoding = mimetypes.guess_type(file_path)
    if ctype is None or encoding is not None:
        ctype = "application/octet-stream"
    main_type, sub_type = ctype.split("/", 1)

    with open(file_path, "rb") as f:
        part = MIMEBase(main_type, sub_type)
        part.set_payload(f.read())

    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition",
        f'attachment; filename="{os.path.basename(file_path)}"',
    )
    message.attach(part)


def build_message_with_attachments(to_address, subject, body_text, attachment_paths):
    message = MIMEMultipart()
    message["to"] = to_address
    message["subject"] = subject
    message.attach(MIMEText(body_text, "plain"))
    for path in attachment_paths:
        attach_file(message, str(path))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {"raw": raw}


def send_and_label(service, message, label_id):
    sent = service.users().messages().send(userId="me", body=message).execute()
    service.users().messages().modify(
        userId="me",
        id=sent["id"],
        body={"addLabelIds": [label_id]},
    ).execute()
    return sent


# ---------------------------------------------------------------------------
# Récupération d'une offre complète depuis la base (analytics/Silver),
# avec toutes les jointures nécessaires pour donner un contexte riche au LLM.
# ---------------------------------------------------------------------------

def fetch_sample_job_posting(query) -> dict:
    """
    Récupère une offre au hasard, avec entreprise, localisation, exigences
    (job_requirement) et un contact email si disponible. Basé sur le schéma
    002_init_silver.sql (analytics.job_offer / company / company_location /
    job_requirement / company_contact).
    """
    

    with psycopg2.connect(DATABASE_URL) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query)
            row = cur.fetchone()

    if row is None:
        raise RuntimeError("Aucune offre trouvée en base pour le test.")

    return {
        "offer_id": row["id_offer"],
        "id_company": row["id_company"],
        "id_location": row["id_location"],
        "job_title": row["job_title"],
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
    job_context = fetch_sample_job_posting(BEST_QUERY)
    print(f"   id_offer    : {job_context['offer_id']}")
    print(f"   id_company  : {job_context['id_company']}")
    print(f"   id_location : {job_context['id_location']}")
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
    # Timestamp lisible pour l'homme, inclus dans le nom de fichier afin de
    # garder une trace de chaque test sans écraser les précédents.
    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%M")

    pdf_path = OUTPUT_DIR / f"cover_letter_{timestamp}.pdf"
    render_pdf(pdf_context, output_path=str(pdf_path))

    email_path = OUTPUT_DIR / f"email_{timestamp}.txt"
    with open(email_path, "w", encoding="utf-8") as f:
        f.write(f"Généré le : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Offre     : {job_context['company_name']} — {job_context['job_title']}\n")
        f.write(f"id_offer  : {job_context['offer_id']}\n")
        f.write(f"To: {job_context['contact_email'] or '(aucun contact trouvé)'}\n")
        f.write(f"Subject: {email_rendered['subject']}\n")
        f.write("\n" + "-" * 60 + "\n\n")
        f.write(email_rendered["body"])

    print(f"\n✅ PDF généré  : {pdf_path}")
    print(f"✅ Email écrit : {email_path}")

    # --- Envoi réel via Gmail, vers toi-même, avec CV + lettre en pièces jointes ---
    print(f"\n→ Envoi de l'email de test à {TEST_RECIPIENT}...")

    if not CV_PATH.exists():
        raise FileNotFoundError(
            f"CV introuvable à {CV_PATH} — ajuste CV_PATH en tête de fichier."
        )

    creds = load_gmail_credentials()
    service = build("gmail", "v1", credentials=creds)
    label_id = get_or_create_label(service, LABEL_NAME)

    message = build_message_with_attachments(
        to_address=TEST_RECIPIENT,
        subject=f"[TEST] {email_rendered['subject']}",
        body_text=(
            f"Offre testée : {job_context['company_name']} — {job_context['job_title']}\n"
            f"id_offer : {job_context['offer_id']}\n"
            f"Contact réel (non utilisé, envoi vers soi-même) : {job_context['contact_email']}\n\n"
            + "-" * 60 + "\n\n"
            + email_rendered["body"]
        ),
        attachment_paths=[CV_PATH, pdf_path],
    )

    sent = send_and_label(service, message, label_id)

    print(f"✅ Email envoyé et labellisé '{LABEL_NAME}'. Message ID : {sent['id']}")


if __name__ == "__main__":
    main()