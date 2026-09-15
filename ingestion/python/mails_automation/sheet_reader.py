"""
sheet_reader.py — lecture des réponses d'un Google Form via l'API Sheets.

Réutilise le même token.json que Gmail (scope spreadsheets.readonly ajouté
aux scopes Gmail existants) — un seul token, un seul compte, pas de
service account nécessaire.

Fonctions paramétrées (spreadsheet_id, range_name, token_file) pour être
réutilisables telles quelles depuis un DAG Airflow (blacklist_sync.py) ET
testables en local sans dupliquer la logique dans les deux fichiers.

Prérequis :
    pip install google-auth-oauthlib google-api-python-client

Utilisation (test local) :
    python sheet_reader.py
    -> lit la Sheet (valeurs codées en dur dans le bloc __main__ ci-dessous)
       et affiche les lignes trouvées en console

Utilisation (depuis un DAG) :
    from sheet_reader import fetch_form_responses

    rows = fetch_form_responses(
        spreadsheet_id=SPREADSHEET_ID,
        range_name=SHEET_RANGE_NAME,
    )
"""

import os
from pathlib import Path

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]

# Même pattern que le reste du projet (email_sender.py) : CONFIG_PATH par
# défaut pointe vers le conteneur Airflow. En local, place token.json dans
# le même dossier que ce script et lance simplement `python sheet_reader.py`
# — le CONFIG_PATH par défaut ne s'applique alors qu'au DAG, pas au test
# local (voir DEFAULT_TOKEN_FILE ci-dessous).
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))
DEFAULT_TOKEN_FILE = str(CONFIG_PATH / "token.json")


# ---------------------------------------------------------------------------
# Authentification (identique à email_sender.load_credentials)
# ---------------------------------------------------------------------------

def load_credentials(token_file: str = DEFAULT_TOKEN_FILE):
    creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return creds


# ---------------------------------------------------------------------------
# Lecture de la Sheet
# ---------------------------------------------------------------------------

def fetch_form_responses(
    spreadsheet_id: str,
    range_name: str,
    token_file: str = DEFAULT_TOKEN_FILE,
) -> list[dict]:
    """
    Lit toutes les lignes de la Sheet et les retourne comme une liste de
    dicts, en utilisant la première ligne comme en-têtes de colonnes.

    Args:
        spreadsheet_id: ID de la Sheet (dans son URL).
        range_name: onglet + plage, ex "Réponses au formulaire 1!A:Z".
        token_file: chemin vers token.json (par défaut CONFIG_PATH/token.json).

    Returns:
        [{"Horodateur": "...", "Email": "...", ...}, ...]
    """
    creds = load_credentials(token_file)
    service = build("sheets", "v4", credentials=creds)

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=range_name)
        .execute()
    )

    values = result.get("values", [])

    if not values:
        return []

    headers = values[0]
    rows = values[1:]

    responses = []
    for row in rows:
        # Une ligne peut être plus courte que headers si des cellules de fin
        # sont vides (Sheets ne les renvoie pas) — on complète avec "".
        padded_row = row + [""] * (len(headers) - len(row))
        responses.append(dict(zip(headers, padded_row)))

    return responses


# ---------------------------------------------------------------------------
# Test local
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # ⚠️ Valeurs de test local — remplace SPREADSHEET_ID par le tien.
    # TOKEN_FILE local : token.json dans le même dossier que ce script.
    TEST_SPREADSHEET_ID = "COLLE_TON_SPREADSHEET_ID_ICI"
    TEST_RANGE_NAME = "Réponses au formulaire 1!A:Z"
    TEST_TOKEN_FILE = "token.json"

    if TEST_SPREADSHEET_ID == "COLLE_TON_SPREADSHEET_ID_ICI":
        raise ValueError(
            "Renseigne TEST_SPREADSHEET_ID en haut du bloc __main__ avant de lancer."
        )

    print("→ Lecture de la Sheet...")
    responses = fetch_form_responses(
        spreadsheet_id=TEST_SPREADSHEET_ID,
        range_name=TEST_RANGE_NAME,
        token_file=TEST_TOKEN_FILE,
    )

    print(f"\n{len(responses)} réponse(s) trouvée(s) :\n")
    for i, row in enumerate(responses, 1):
        print(f"--- Ligne {i} ---")
        for key, value in row.items():
            print(f"  {key}: {value}")
        print()