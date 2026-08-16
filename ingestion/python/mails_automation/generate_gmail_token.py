"""
Script local pour générer le token OAuth2 Gmail (usage unique, en local).

Prérequis :
    pip install google-auth-oauthlib google-api-python-client

Utilisation :
    1. Place ce script dans le même dossier que ton client_secret.json
       (téléchargé depuis Google Cloud Console).
    2. Lance : python generate_gmail_token.py
    3. Ton navigateur va s'ouvrir automatiquement.
    4. Connecte-toi avec le compte Gmail que tu veux utiliser pour l'ENVOI
       (celui ajouté comme "test user" dans l'écran de consentement OAuth).
    5. Clique "Autoriser" sur l'écran de consentement.
    6. Un fichier token.json sera créé dans ce dossier.

Ce token.json est ensuite à transférer sur ton VPS (via scp, jamais via Git)
pour que le pipeline Airflow puisse envoyer des emails sans navigateur.
"""

import os
from google_auth_oauthlib.flow import InstalledAppFlow

# Scope restreint : envoi d'emails uniquement (principe du moindre privilège)
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify"
    ]

CLIENT_SECRET_FILE = ".client_secret.json"
TOKEN_FILE = "token.json"


def main():
    if not os.path.exists(CLIENT_SECRET_FILE):
        raise FileNotFoundError(
            f"'{CLIENT_SECRET_FILE}' introuvable dans le dossier courant. "
            "Télécharge-le depuis Google Cloud Console > Credentials, "
            "et place-le à côté de ce script."
        )

    print("Ouverture du navigateur pour l'autorisation OAuth2...")
    print("Connecte-toi avec le compte Gmail EXPÉDITEUR (pas forcément le compte du projet GCP).\n")

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "w") as token_file:
        token_file.write(creds.to_json())

    print(f"\n✅ Token sauvegardé dans '{TOKEN_FILE}'.")
    print("⚠️  Ne commit JAMAIS ce fichier sur GitHub (ajoute-le à .gitignore).")
    print("Prochaine étape : transfère-le sur ton VPS via scp, ex :")
    print(f"    scp {TOKEN_FILE} user@ton-vps:/chemin/vers/email_sender/")


if __name__ == "__main__":
    main()
