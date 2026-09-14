"""
email_sender.py — utilitaires Gmail pour l'envoi de candidatures.

Seule responsabilité de ce module : authentification OAuth2, construction
du message MIME avec pièces jointes, envoi et labellisation.

Ne fait AUCUNE génération de contenu (LLM, templates, PDF) — c'est le rôle
de llm_application.py, email_maker.py et pdf_maker.py, orchestrés par le
DAG automated_application.py.

Prérequis :
    pip install google-auth-oauthlib google-api-python-client

Utilisation (depuis le DAG Airflow) :
    from email_sender import (
        load_credentials,
        get_or_create_label,
        send_and_label,
        build_message_with_attachments,
    )
"""

import base64
import mimetypes
import os
from pathlib import Path
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Chemin absolu, cohérent avec CONFIG_PATH du DAG — le token est lu ET
# réécrit ici (refresh automatique), donc il doit pointer vers un
# emplacement stable, pas le répertoire de travail courant.
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))
TOKEN_FILE = str(CONFIG_PATH / "token.json")


# ---------------------------------------------------------------------------
# Authentification Gmail
# ---------------------------------------------------------------------------

def load_credentials():
    """
    Charge les credentials OAuth2 depuis TOKEN_FILE. Si l'access_token a
    expiré, le rafraîchit automatiquement via le refresh_token et réécrit
    le fichier — aucune ré-authentification manuelle nécessaire.
    """
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def get_or_create_label(service, label_name):
    """Récupère l'ID du label s'il existe déjà, sinon le crée (idempotent)."""
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
# Construction du message avec pièces jointes
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


# ---------------------------------------------------------------------------
# Envoi
# ---------------------------------------------------------------------------

def send_and_label(service, message, label_id):
    """Envoie le message puis applique le label de suivi sur la conversation."""
    sent = service.users().messages().send(userId="me", body=message).execute()

    service.users().messages().modify(
        userId="me",
        id=sent["id"],
        body={"addLabelIds": [label_id]},
    ).execute()

    return sent