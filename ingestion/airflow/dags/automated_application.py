from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

# Ingestion python scripts (mêmes conventions que fetch_jsearch_pipeline)
from utils import write_json, load_json, cleanup_stale_files
from bucket import Bucket
from datasets import B2_RAW  # ou un Dataset dédié aux candidatures, à créer si besoin

from datetime import datetime, timedelta
from pathlib import Path
import logging
import os

logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________________________________________________
APPLICATIONS_PATH = Path(os.getenv('APPLICATIONS_DATA_PATH', '/opt/airflow/applications'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))

SCHEDULE = "0 8 * * *"

SOURCE = "automated_application"
DATA_TYPE = "job_application"

LABEL_NAME = "automation_mail"

# Nombre max d'offres traitées par run
MAX_OFFERS_PER_RUN = 10

# Nombre max de contacts par offre à considérer (fallback séquentiel)
MAX_CONTACTS_PER_OFFER = 3

# Âge max (heures) avant nettoyage forcé des JSON locaux non archivés
STALE_FILE_MAX_AGE_HOURS = 48

# ⚠️ MODE TEST : si la Variable Airflow MAIL_TEST est définie (non vide),
# TOUS les emails partent vers cette adresse au lieu du vrai contact.
# Le contact réel est conservé dans le JSON et loggé, mais jamais utilisé
# comme destinataire. Laisser vide / non définie pour l'envoi réel.
MAIL_TEST = Variable.get("MAIL_TEST", default_var=None) or None


# ___ HELPERS _________________________________________________________________

def fetch_offers(limit: int = MAX_OFFERS_PER_RUN) -> list[dict]:
    """
    À REMPLIR : requête DB retournant les offres pertinentes non encore
    candidatées (filtres score_relevancy + contact disponible + pas déjà
    envoyé), limitée à `limit` résultats.
    Retourne une liste de dicts prêts à servir de job_context.
    """
    pass


def fetch_contacts_ranked(offer_id: str, limit: int = MAX_CONTACTS_PER_OFFER) -> list[dict]:
    """
    À REMPLIR : requête DB retournant les contacts d'une offre, triés du
    meilleur au moins bon (confidence Hunter, rôle RH prioritaire, etc.),
    limitée à `limit` résultats.
    Format attendu : [{"email": ..., "confidence": ..., "explanation": ...}, ...]
    """
    pass


def select_next_contact(contacts_ranked: list[dict], offer_id: str) -> dict | None:
    """
    À REMPLIR : sélectionne le prochain contact à qui envoyer pour cette
    offre, selon le fallback séquentiel (premier contact non encore tenté
    dans tracking_application, et absent de blacklist).
    Retourne un dict {"id_contact": ..., "email": ...}, ou None si tous les
    contacts ont déjà été tentés ou sont blacklistés.
    """
    pass


def is_blacklisted(id_contact: int) -> bool:
    """
    À REMPLIR : vérifie si id_contact est présent dans analytics.blacklist.
    """
    pass


def track_application_sent(
    id_offer: str,
    id_location: int | None,
    id_company: int,
    id_contact: int,
) -> None:
    """
    Écrit une ligne dans analytics.tracking_application. UNIQUE(id_offer,
    id_contact) empêche un doublon si le DAG est rejoué pour la même paire.
    """
    pass


# ___ DAG _____________________________________________________________________

@dag(
    dag_id='automated_application',
    start_date=datetime(2026, 6, 7),
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["silver", "application", "llm"],
    default_args={
        'owner': 'internship_latam',
        'retries': 1,
        'retry_delay': timedelta(minutes=30),
    },
)
def automated_application():

    @task(task_id="generate_content")
    def generate_content(ds=None) -> list[str]:
        """
        Fetch les offres pertinentes en base.
        Pour chaque offre, génère email + lettre via LLM (resolve_document),
        SANS injecter candidate_info (nom/coordonnées) — seulement le
        contenu généré (greeting + paragraphes) et le job_context.

        Idempotent : si le JSON de sortie existe déjà pour une offre, elle
        est sautée (pas de régénération, pas de nouvel appel LLM).

        Returns:
            Liste des chemins de fichiers JSON générés (ou déjà existants).
        """
        from llm_application import resolve_document
        from LLMProvider import LLM
        from pdf_maker import load_yaml

        APPLICATIONS_PATH.mkdir(parents=True, exist_ok=True)

        # Nettoyage préventif : purge les JSON orphelins d'un run précédent
        # qui aurait planté avant l'archivage (évite la saturation du VPS).
        cleanup_stale_files(str(APPLICATIONS_PATH), max_age_hours=STALE_FILE_MAX_AGE_HOURS)

        llm = LLM()
        model = llm.application

        offers = fetch_offers(limit=MAX_OFFERS_PER_RUN)
        if not offers:
            raise AirflowSkipException("Aucune offre pertinente à traiter ce run")

        # Config de candidature : YAML (pas JSON) — cohérent avec
        # pdf_maker.py / email_maker.py / llm_application.py
        skills = load_yaml(str(CONFIG_PATH / "candidate_skills.yaml"))
        email_content = load_yaml(str(CONFIG_PATH / "email_content.yaml"))
        letter_content = load_yaml(str(CONFIG_PATH / "letter_content.yaml"))

        output_paths = []

        for offer in offers:
            offer_id = offer["offer_id"]
            output_file = APPLICATIONS_PATH / f"{offer_id}.json"

            if output_file.exists():
                logger.info(f"[GENERATE] offer_id={offer_id} status=skip_existing")
                output_paths.append(str(output_file))
                continue

            contacts_ranked = fetch_contacts_ranked(offer_id, limit=MAX_CONTACTS_PER_OFFER)
            job_context = offer

            try:
                email_resolved = resolve_document(
                    body_paragraphs=email_content["body_paragraphs"],
                    default_greeting=email_content["greeting_line"],
                    skills=skills,
                    job_context=job_context,
                    model=model,
                    document_type="email",
                )
                letter_resolved = resolve_document(
                    body_paragraphs=letter_content["body_paragraphs"],
                    default_greeting=letter_content["greeting_line"],
                    skills=skills,
                    job_context=job_context,
                    model=model,
                    document_type="letter",
                )
            except Exception as e:
                logger.warning(f"[GENERATE] offer_id={offer_id} status=error err={e}")
                continue

            # Le JSON ne contient JAMAIS candidate_info (nom, adresses,
            # téléphone) — uniquement le contenu généré et le contexte offre.
            # candidate_info n'est injecté que dans build_and_send, en mémoire.
            application_data = {
                "offer_id": offer_id,
                "generated_at": datetime.now().isoformat(),
                "job_context": job_context,
                "contacts_ranked": contacts_ranked,
                "email": {
                    "subject_line": email_content["subject_line"],
                    "closing_line": email_content["closing_line"],
                    "greeting_line": email_resolved["greeting_line"],
                    "body_paragraphs": email_resolved["body_paragraphs"],
                },
                "letter": {
                    "status_line": letter_content.get("status_line"),
                    "objective_line": letter_content.get("objective_line"),
                    "letter_date": datetime.now().strftime("%B %d, %Y"),
                    "greeting_line": letter_resolved["greeting_line"],
                    "body_paragraphs": letter_resolved["body_paragraphs"],
                },
            }

            write_json(str(APPLICATIONS_PATH), offer_id, application_data)
            output_paths.append(str(output_file))
            logger.info(f"[GENERATE] offer_id={offer_id} status=success")

        if not output_paths:
            raise AirflowSkipException("Aucune candidature générée ce run")

        logger.info(f"[GENERATE] date={ds} total={len(output_paths)} status=success")
        return output_paths


    @task(task_id="build_and_send")
    def build_and_send(application_paths: list[str]) -> list[dict]:
        """
        Pour chaque JSON généré : charge candidate_info, formate email + PDF
        (aucun appel LLM ici), envoie via Gmail au contact sélectionné.

        Si MAIL_TEST est défini, tous les emails partent vers cette adresse
        au lieu du vrai contact (mode test).

        Returns:
            Liste de dicts {path, offer_id, contact_email, message_id}
            pour les envois réussis, passée à archive_application.
        """
        from pdf_maker import render_pdf, load_yaml
        from email_maker import build_context, render_email
        from email_sender import (
            load_credentials,
            get_or_create_label,
            send_and_label,
            build_message_with_attachments,
        )
        from googleapiclient.discovery import build as gmail_build

        profile = load_yaml(str(CONFIG_PATH / "candidate_info.yaml"))
        cv_path = CONFIG_PATH / "cv_static.pdf"

        if not cv_path.exists():
            raise FileNotFoundError(f"CV introuvable : {cv_path}")

        creds = load_credentials()
        service = gmail_build("gmail", "v1", credentials=creds)
        label_id = get_or_create_label(service, LABEL_NAME)

        if MAIL_TEST:
            logger.warning(f"[SEND] MODE TEST ACTIF — tous les emails partent vers {MAIL_TEST}")

        sent_records = []

        for path in application_paths:
            application_data = load_json(str(Path(path).parent), Path(path).stem)
            offer_id = application_data["offer_id"]

            next_contact = select_next_contact(application_data["contacts_ranked"], offer_id)

            if not next_contact:
                logger.info(f"[SEND] offer_id={offer_id} status=skip_no_contact")
                continue

            if is_blacklisted(next_contact["id_contact"]):
                logger.info(f"[SEND] offer_id={offer_id} id_contact={next_contact['id_contact']} status=skip_blacklisted")
                continue

            real_contact_email = next_contact["email"]
            id_contact = next_contact["id_contact"]

            # En mode test, on redirige le destinataire mais on garde une
            # trace du contact réel qui aurait été utilisé.
            recipient = MAIL_TEST if MAIL_TEST else real_contact_email

            # --- Formatage email (candidate_info injecté ici, en mémoire) ---
            email_context = build_context(profile, application_data["email"])
            email_rendered = render_email(email_context)

            # --- Formatage PDF (candidate_info injecté ici, en mémoire) ---
            pdf_context = {**profile, **application_data["letter"]}
            pdf_path = APPLICATIONS_PATH / f"{offer_id}_cover_letter.pdf"
            render_pdf(pdf_context, output_path=str(pdf_path))

            subject = email_rendered["subject"]
            body = email_rendered["body"]

            if MAIL_TEST:
                subject = f"[TEST] {subject}"
                body = (
                    f"--- MODE TEST ---\n"
                    f"Offre        : {application_data['job_context'].get('company_name')} — "
                    f"{application_data['job_context'].get('job_title')}\n"
                    f"id_offer     : {offer_id}\n"
                    f"Contact réel : {real_contact_email} (non utilisé, envoi redirigé)\n"
                    + "-" * 60 + "\n\n"
                    + body
                )

            message = build_message_with_attachments(
                to_address=recipient,
                subject=subject,
                body_text=body,
                attachment_paths=[str(cv_path), str(pdf_path)],
            )

            try:
                sent = send_and_label(service, message, label_id)
            except Exception as e:
                logger.warning(f"[SEND] offer_id={offer_id} to={recipient} status=error err={e}")
                continue

            sent_records.append({
                "path": path,
                "offer_id": offer_id,
                "id_location": application_data["job_context"].get("id_location"),
                "id_company": application_data["job_context"].get("id_company"),
                "id_contact": id_contact,
                "contact_email": real_contact_email,
                "message_id": sent["id"],
            })
            logger.info(
                f"[SEND] offer_id={offer_id} to={recipient} "
                f"real_contact={real_contact_email} status=success message_id={sent['id']}"
            )

        if not sent_records:
            raise AirflowSkipException("Aucun email envoyé ce run")

        logger.info(f"[SEND] total={len(sent_records)} status=success")
        return sent_records


    @task(task_id="archive_application", outlets=[B2_RAW])
    def archive_application(sent_records: list[dict], ds=None) -> None:
        """
        Pour chaque candidature envoyée : upload du JSON vers B2 sous
        application/{ds}/{id_offer}_{id_contact}.json, écrit une ligne dans
        analytics.tracking_application, puis supprime les fichiers locaux
        (JSON + PDF temporaire).
        """
        bucket = Bucket(
            key_id=Variable.get("KEY_ID"),
            app_key=Variable.get("APPLICATION_KEY"),
            bucket_name=Variable.get("BUCKET_NAME"),
        )

        for record in sent_records:
            path = record["path"]
            offer_id = record["offer_id"]
            id_contact = record["id_contact"]

            # Chemin bucket dédié aux candidatures, distinct du nesting
            # data_type/year/month/api_source utilisé pour la collecte brute.
            remote_key = f"application/{ds}/{offer_id}_{id_contact}.json"

            # ⚠️ save_to_landing_bucket impose le nesting standard
            # (data_type/year/month/api_source) — ici on veut un chemin
            # spécifique, donc upload direct via la méthode générique du
            # client Bucket plutôt que ce wrapper. Ajuste le nom de méthode
            # ci-dessous selon l'API réelle de ta classe Bucket (upload_file,
            # put_object, etc. — à confirmer).
            try:
                file_data = bucket.upload_file(local_path=path, remote_path=remote_key)
            except Exception as e:
                logger.warning(f"[ARCHIVE] offer_id={offer_id} id_contact={id_contact} status=upload_failed err={e}")
                continue

            if file_data is None:
                logger.warning(f"[ARCHIVE] offer_id={offer_id} id_contact={id_contact} status=upload_failed")
                continue

            track_application_sent(
                id_offer=offer_id,
                id_location=record.get("id_location"),
                id_company=record.get("id_company"),
                id_contact=id_contact,
            )

            # Nettoyage local uniquement après confirmation d'upload
            os.remove(path)

            pdf_path = APPLICATIONS_PATH / f"{offer_id}_cover_letter.pdf"
            if pdf_path.exists():
                os.remove(pdf_path)

            logger.info(f"[ARCHIVE] offer_id={offer_id} id_contact={id_contact} remote={remote_key} status=success")

        logger.info(f"[ARCHIVE] date={ds} total={len(sent_records)} status=success")


    application_paths = generate_content()
    sent_records = build_and_send(application_paths)
    archive_application(sent_records)


automated_application()