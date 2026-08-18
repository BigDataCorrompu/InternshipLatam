"""
email_sender.py — orchestration complète d'une candidature :

    1. Charge le contexte (profil + contenu email + contenu lettre) depuis YAML
    2. Génère les champs de personnalisation via LLM (Mistral Small),
       validés par Pydantic — jamais de texte libre non contrôlé
    3. Assemble l'email (texte) et la lettre de motivation (PDF)
    4. Envoie via l'API Gmail avec CV (statique) + lettre (PDF généré) en pièces jointes
    5. Labellise la conversation avec 'automation_mail'

Respecte le pattern du projet : le LLM ne rédige jamais le document final,
il retourne des champs contraints que Python injecte dans les templates.

Prérequis :
    pip install google-auth-oauthlib google-api-python-client jinja2 pyyaml xhtml2pdf mistralai pydantic

Utilisation :
    python email_sender.py
"""

import base64
import mimetypes
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from email_maker import load_yaml, render_email
from pdf_maker import html_template as cover_letter_html_template, render_pdf
from generate_personalization_example import JobContext, generate_personalization


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]
TOKEN_FILE = "token.json"
LABEL_NAME = "automation_mail"

CV_PATH = "cv_static.pdf"  # ton CV statique, à placer à côté de ce script
COVER_LETTER_OUTPUT = "cover_letter.pdf"

# ⚠️ Destinataire de test — à remplacer par l'adresse réelle de l'entreprise ciblée
TO_ADDRESS = "oucherif.roland@gmail.com"


# ---------------------------------------------------------------------------
# 1. Auth Gmail (inchangé)
# ---------------------------------------------------------------------------

def load_credentials():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def get_or_create_label(service, label_name):
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


# ---------------------------------------------------------------------------
# 2. Construction du contexte : profil + offre ciblée
#    (job_context serait normalement lu depuis ta table Silver via psycopg2 —
#    ici en dur pour l'exemple/test)
# ---------------------------------------------------------------------------

def build_job_context() -> JobContext:
    return JobContext(
        company_name="Mercado Libre",
        city="Buenos Aires",
        country="Argentina",
        sector="E-commerce",
        related_job_titles=["Data Engineer Intern", "Junior Data Engineer"],
        seniority="Internship",
    )


def build_full_context(job_context: JobContext) -> dict:
    """Fusionne profil, contenu email/lettre statiques, et personnalisation LLM."""
    profile = load_yaml("candidate_profile.yaml")
    email_content = load_yaml("email_content.yaml")
    letter_content = load_yaml("letter_content.yaml")

    personalization = generate_personalization(job_context)

    # Injecte l'accroche générée par le LLM en tête des paragraphes existants,
    # sans jamais remplacer le contenu statique validé.
    email_content = {
        **email_content,
        "body_paragraphs": [personalization.opening_hook] + email_content["body_paragraphs"],
    }
    letter_content = {
        **letter_content,
        "greeting_line": f"Dear {job_context.company_name} Hiring Team,",
        "body_paragraphs": [personalization.cover_letter_intro] + letter_content["body_paragraphs"],
    }

    return {
        "profile": profile,
        "email_content": email_content,
        "letter_content": letter_content,
    }


# ---------------------------------------------------------------------------
# 3. Génération de la lettre PDF (réutilise pdf_maker.py)
# ---------------------------------------------------------------------------

def generate_cover_letter_pdf(profile: dict, letter_content: dict, output_path: str) -> str:
    context = {**profile, **letter_content}
    render_pdf(context, output_path=output_path)
    return output_path


# ---------------------------------------------------------------------------
# 4. Construction du message email avec pièces jointes
# ---------------------------------------------------------------------------

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
    # Pas de "from" explicite : Gmail utilise le compte authentifié via OAuth.

    message.attach(MIMEText(body_text, "plain"))

    for path in attachment_paths:
        attach_file(message, path)

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
# 5. Orchestration
# ---------------------------------------------------------------------------

def main():
    # --- Contexte : profil + offre ciblée + personnalisation LLM ---
    job_context = build_job_context()
    full_context = build_full_context(job_context)

    profile = full_context["profile"]
    email_content = full_context["email_content"]
    letter_content = full_context["letter_content"]

    # --- Email (texte) ---
    email_render_context = {**profile, **email_content}
    email = render_email(email_render_context)

    # --- Lettre de motivation (PDF) ---
    generate_cover_letter_pdf(profile, letter_content, COVER_LETTER_OUTPUT)

    # --- Auth Gmail ---
    creds = load_credentials()
    service = build("gmail", "v1", credentials=creds)
    label_id = get_or_create_label(service, LABEL_NAME)

    # --- Assemblage + envoi ---
    message = build_message_with_attachments(
        to_address=TO_ADDRESS,
        subject=email["subject"],
        body_text=email["body"],
        attachment_paths=[CV_PATH, COVER_LETTER_OUTPUT],
    )

    sent = send_and_label(service, message, label_id)

    print(f"✅ Email envoyé et labellisé '{LABEL_NAME}'. Message ID : {sent['id']}")
    print(f"   Sujet : {email['subject']}")


if __name__ == "__main__":
    main()