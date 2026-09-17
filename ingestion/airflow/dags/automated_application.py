from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

# Ingestion python scripts (mêmes conventions que fetch_jsearch_pipeline)
from utils import write_json, load_json, cleanup_stale_files
from bucket import Bucket
from database import Database
from datasets import BLACKLIST  # ou un Dataset dédié aux candidatures, à créer si besoin

from datetime import datetime, timedelta
from pathlib import Path
import logging
import os

logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________________________________________________
APPLICATIONS_PATH = Path(os.getenv('APPLICATIONS_DATA_PATH', '/opt/airflow/applications'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))
TOKEN_FILE = str(CONFIG_PATH / "token.json")

SCHEDULE = "0 8 * * *"

SOURCE = "automated_application"
DATA_TYPE = "job_application"

LABEL_NAME = "automation_mail"

# Nombre max d'offres traitées par run
MAX_OFFERS_PER_RUN = 10

# Nombre max de contacts par offre à considérer (fallback séquentiel)
MAX_CONTACTS_PER_OFFER = 4

# Âge max (heures) avant nettoyage forcé des JSON locaux non archivés
STALE_FILE_MAX_AGE_HOURS = 48

# ⚠️ MODE TEST : deux Variables Airflow séparées, pour ne jamais perdre
# l'adresse de test en la togglant :
#   - MAIL_TEST : l'adresse email de test (reste enregistrée en permanence)
#   - FORCE_MAIL_TEST : booléen ("true"/"false") qui active ou non la
#     redirection. Si "true" ET MAIL_TEST définie -> tous les emails
#     partent vers MAIL_TEST. Si "false" (ou absente) -> envoi réel, même
#     si MAIL_TEST reste enregistrée.
# Le contact réel est conservé dans le JSON et loggé, mais jamais utilisé
# comme destinataire quand le mode test est actif.
MAIL_TEST = Variable.get("MAIL_TEST", default_var=None) or None

MAIL_TEST_ACTIVE = True


# Requête SQL de fetch_next_candidates.sql, chargée en constante pour éviter
# une lecture disque à chaque appel. Paramètres positionnels (%s, ...),
# cohérents avec la convention utilisée par Database.execute().
QUERY_FETCH_NEXT_CANDIDATES = """
WITH eligible_contacts AS (
    SELECT
        jo.id_offer,
        jo.job_title,
        jo.published_at,

        c.id_company,
        c.company_name,

        cl.id_location,
        cl.city,
        cl.country,

        jrel.score_relevancy,

        cc.id_contact,
        cc.email AS contact_email,
        cc.confidence AS contact_confidence,
        cc.explanation AS contact_explanation,

        ROW_NUMBER() OVER (
            PARTITION BY jo.id_offer
            ORDER BY cc.confidence DESC
        ) AS contact_rank

    FROM analytics.job_offer jo
    JOIN analytics.company c
        ON jo.id_company = c.id_company
    LEFT JOIN analytics.company_location cl
        ON jo.id_location = cl.id_location
    JOIN analytics.job_relevancy jrel
        ON jrel.id_offer = jo.id_offer
    JOIN analytics.company_contact cc
        ON cc.id_company = c.id_company

    WHERE jo.published_at >= NOW() - INTERVAL '7 days'
      AND jrel.score_relevancy > 7

      AND NOT EXISTS (
          SELECT 1 FROM analytics.tracking_application ta
          WHERE ta.id_offer = jo.id_offer
            AND ta.id_contact = cc.id_contact
      )

      AND NOT EXISTS (
          SELECT 1 FROM analytics.blacklist bl
          WHERE LOWER(bl.email) = LOWER(cc.email)
      )
)

SELECT *
FROM eligible_contacts
WHERE contact_rank <= %s
ORDER BY score_relevancy DESC, id_offer, contact_rank
LIMIT %s;
"""

# Relances : offres déjà contactées, prochain contact dans l'ordre de
# confiance, délai de 72h respecté, abandon après 14 jours. Priorité plus
# basse que QUERY_FETCH_NEXT_CANDIDATES — ne comble que le budget restant.
QUERY_FETCH_REMINDER = """
WITH history AS (
    SELECT
        id_offer,
        COUNT(*) AS times_sent,
        MAX(date) AS last_sent
    FROM analytics.tracking_application
    GROUP BY id_offer
),

eligible_contacts AS (
    SELECT
        jo.id_offer,
        jo.job_title,
        jo.offer_description,
        jo.published_at,

        c.id_company,
        c.company_name,

        cl.id_location,
        cl.city,
        cl.country,

        jr.alternative_job_titles,
        jr.skills_languages,
        jr.skills_frameworks,
        jr.skills_aptitudes,
        jr.skills_soft,

        jrel.score_relevancy,

        cc.id_contact,
        cc.email AS contact_email,
        cc.confidence AS contact_confidence,
        cc.explanation AS contact_explanation,

        ROW_NUMBER() OVER (
            PARTITION BY jo.id_offer
            ORDER BY cc.confidence DESC
        ) AS contact_rank,

        h.times_sent,
        h.last_sent

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
    JOIN history h
        ON h.id_offer = jo.id_offer

    WHERE jo.published_at >= NOW() - INTERVAL '14 days'
      AND jrel.score_relevancy > 7
      AND cc.confidence > 0.5
      AND h.last_sent <= NOW() - INTERVAL '72 hours'

      AND NOT EXISTS (
          SELECT 1 FROM analytics.tracking_application ta
          WHERE ta.id_offer = jo.id_offer
            AND ta.id_contact = cc.id_contact
      )

      AND NOT EXISTS (
          SELECT 1 FROM analytics.blacklist bl
          WHERE LOWER(bl.email) = LOWER(cc.email)
      )
)

SELECT *
FROM eligible_contacts
WHERE contact_rank = times_sent + 1
ORDER BY score_relevancy DESC, id_offer
LIMIT %s;
"""

# ___ HELPERS _________________________________________________________________

def get_db() -> Database:
    return Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )

def _group_candidates_by_offer(rows: list[dict], max_offers: int) -> dict[str, dict]:
    """
    Regroupe un résultat plat (une ligne par contact) en dict par offre.
    Utilisée pour les deux requêtes (fraîches et relances), même format
    de sortie attendu par generate_content.
    """
    candidates: dict[str, dict] = {}

    for row in rows:
        offer_id = row["id_offer"]

        if offer_id not in candidates:
            if len(candidates) >= max_offers:
                continue

            candidates[offer_id] = {
                "job_context": {
                    "id_offer": row["id_offer"],
                    "job_title": row["job_title"],
                    "offer_description": row.get("offer_description"),
                    "id_company": row["id_company"],
                    "company_name": row["company_name"],
                    "id_location": row.get("id_location"),
                    "city": row.get("city"),
                    "country": row.get("country"),
                    "alternative_job_titles": row.get("alternative_job_titles"),
                    "skills_languages": row.get("skills_languages"),
                    "skills_frameworks": row.get("skills_frameworks"),
                    "skills_aptitudes": row.get("skills_aptitudes"),
                    "skills_soft": row.get("skills_soft"),
                },
                "contacts": [],
            }

        if offer_id in candidates:
            candidates[offer_id]["contacts"].append({
                "id_contact": row["id_contact"],
                "email": row["contact_email"],
                "confidence": row.get("contact_confidence"),
                "explanation": row.get("contact_explanation"),
            })

    return candidates


def fetch_next_candidates(max_offers: int = MAX_OFFERS_PER_RUN) -> dict[str, dict]:
    """
    Combine deux sources, dans cet ordre de priorité :
        1. Offres jamais contactées (QUERY_FETCH_NEXT_CANDIDATES)
        2. Relances sur offres déjà contactées, si le budget max_offers
           n'est pas atteint par les offres fraîches (QUERY_FETCH_REMINDER)

    Les offres fraîches ont toujours priorité — les relances ne comblent
    que le budget restant, jamais au détriment d'une offre jamais tentée.

    Returns:
        Même format que précédemment : {"<id_offer>": {"job_context": {...}, "contacts": [...]}, ...}
    """
    db = get_db()

    fresh_rows = db.execute(
        QUERY_FETCH_NEXT_CANDIDATES,
        [MAX_CONTACTS_PER_OFFER, max_offers * MAX_CONTACTS_PER_OFFER],
    )
    candidates = _group_candidates_by_offer(fresh_rows, max_offers)
    fresh_count = len(candidates)

    remaining_budget = max_offers - fresh_count

    if remaining_budget > 0:
        reminder_rows = db.execute(QUERY_FETCH_REMINDER, [remaining_budget])
        reminder_candidates = _group_candidates_by_offer(reminder_rows, remaining_budget)
        candidates.update(reminder_candidates)

    logger.info(
        f"[GENERATE] fresh_offers={fresh_count} "
        f"reminder_offers={len(candidates) - fresh_count} "
        f"total={len(candidates)}"
    )

    return candidates


def track_application_sent(records: list[tuple]) -> None:
    """
    Écrit toutes les lignes de ce run dans analytics.tracking_application
    en un seul aller-retour DB (bulk_insert), plutôt qu'un execute() par
    candidature dans la boucle d'archivage.

    Args:
        records: liste de tuples (id_offer, id_location, id_company,
            id_contact, b2_key), dans cet ordre exact — doit correspondre
            à `columns` ci-dessous.

    Pas de ON CONFLICT : la table n'a plus de contrainte UNIQUE (voir
    migration 005) — un même contact peut légitimement recevoir plusieurs
    emails pour la même offre au fil de relances successives, chaque envoi
    réussi devient sa propre ligne, sans déduplication.
    """
    if not records:
        return

    db = get_db()
    db.bulk_insert(
        table="analytics.tracking_application",
        columns=["id_offer", "id_location", "id_company", "id_contact", "b2_key"],
        data=records,
    )


def _safe_filename_part(text: str, fallback: str = "Unknown") -> str:
    """Remplace tout caractère non alphanumérique par '_', pour un nom de
    fichier propre en pièce jointe (évite espaces, accents, ponctuation)."""
    text = text or fallback
    return "".join(c if c.isalnum() else "_" for c in text).strip("_") or fallback


# ___ DAG _____________________________________________________________________

@dag(
    dag_id='automated_application',
    start_date=datetime(2026, 6, 7),
    schedule=[BLACKLIST],
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
        Fetch les offres actives avec leurs contacts éligibles (une requête,
        voir fetch_next_candidates). Pour chaque offre :
            - génère la LETTRE une seule fois (contenu neutre, jamais
              personnalisé par contact)
            - génère un EMAIL par contact retenu (jusqu'à MAX_CONTACTS_PER_OFFER),
              avec contact_explanation injecté dans job_context pour que le
              LLM adapte le ton/greeting à ce contact précis

        Écrit un JSON par PAIRE (offre, contact) — c'est cette granularité
        qui est ensuite envoyée et trackée individuellement. La lettre
        (identique pour tous les contacts d'une offre) est dupliquée dans
        chaque JSON par simplicité de traitement en aval (coût négligeable,
        c'est juste du texte).

        SANS injecter candidate_info (nom/coordonnées) — seulement le
        contenu généré et le job_context/contact.

        Idempotent : si le JSON de sortie existe déjà pour une paire
        (offre, contact), elle est sautée.

        Returns:
            Liste des chemins de fichiers JSON générés (ou déjà existants).
        """
        from llm_application import resolve_document
        from LLMprovider import LLM
        from pdf_maker import load_yaml

        APPLICATIONS_PATH.mkdir(parents=True, exist_ok=True)
        cleanup_stale_files(str(APPLICATIONS_PATH), max_age_hours=STALE_FILE_MAX_AGE_HOURS)

        llm = LLM()
        model = llm.application

        candidates = fetch_next_candidates(
            max_offers=MAX_OFFERS_PER_RUN,
        )
        if not candidates:
            raise AirflowSkipException("Aucune offre/contact éligible à traiter ce run")

        skills = load_yaml(str(CONFIG_PATH / "candidate_skills.yaml"))
        email_content = load_yaml(str(CONFIG_PATH / "email_content.yaml"))
        letter_content = load_yaml(str(CONFIG_PATH / "letter_content.yaml"))

        output_paths = []

        for offer_id, offer_data in candidates.items():
            job_context = offer_data["job_context"]
            contacts = offer_data["contacts"]

            if not contacts:
                continue

            # --- Lettre : générée UNE FOIS par offre, contenu neutre ---
            try:
                letter_resolved = resolve_document(
                    body_paragraphs=letter_content["body_paragraphs"],
                    default_greeting=letter_content["greeting_line"],
                    skills=skills,
                    job_context=job_context,  # sans contact_explanation
                    model=model,
                    document_type="letter",
                )
            except Exception as e:
                logger.warning(f"[GENERATE] offer_id={offer_id} step=letter status=error err={e}")
                continue

            # --- Email : une génération par contact retenu ---
            for contact in contacts:
                id_contact = contact["id_contact"]
                output_file = APPLICATIONS_PATH / f"{offer_id}_{id_contact}.json"

                if output_file.exists():
                    logger.info(f"[GENERATE] offer_id={offer_id} id_contact={id_contact} status=skip_existing")
                    output_paths.append(str(output_file))
                    continue

                contact_job_context = {
                    **job_context,
                    "contact_email": contact["email"],
                    "contact_explanation": contact.get("explanation"),
                }

                try:
                    email_resolved = resolve_document(
                        body_paragraphs=email_content["body_paragraphs"],
                        default_greeting=email_content["greeting_line"],
                        skills=skills,
                        job_context=contact_job_context,
                        model=model,
                        document_type="email",
                    )
                except Exception as e:
                    logger.warning(f"[GENERATE] offer_id={offer_id} id_contact={id_contact} step=email status=error err={e}")
                    continue

                application_data = {
                    "offer_id": offer_id,
                    "id_location": job_context.get("id_location"),
                    "id_company": job_context.get("id_company"),
                    "id_contact": id_contact,
                    "contact_email": contact["email"],
                    "generated_at": datetime.now().isoformat(),
                    "job_context": job_context,
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

                write_json(str(APPLICATIONS_PATH), f"{offer_id}_{id_contact}", application_data)
                output_paths.append(str(output_file))
                logger.info(f"[GENERATE] offer_id={offer_id} id_contact={id_contact} status=success")

        if not output_paths:
            raise AirflowSkipException("Aucune candidature générée ce run")

        logger.info(f"[GENERATE] date={ds} total={len(output_paths)} status=success")
        return output_paths


    @task(task_id="build_and_send")
    def build_and_send(application_paths: list[str]) -> list[dict]:
        """
        Pour chaque JSON généré : charge candidate_info, formate email + PDF
        (aucun appel LLM ici), envoie via Gmail au contact sélectionné.

        Si FORCE_MAIL_TEST est activé (et MAIL_TEST définie), tous les
        emails partent vers cette adresse au lieu du vrai contact (mode test).

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
        cv_path = CONFIG_PATH / "cv.pdf"

        if not cv_path.exists():
            raise FileNotFoundError(f"CV introuvable : {cv_path}")

        # Nom d'affichage du CV (identique pour tous les envois, ne dépend
        # pas de l'offre) : "CV_Prenom_Nom.pdf" plutôt que le nom du
        # fichier local "cv.pdf".
        cv_display_name = (
            f"CV_{_safe_filename_part(profile.get('candidate_first_name'))}_"
            f"{_safe_filename_part(profile.get('candidate_last_name'))}.pdf"
        )

        creds = load_credentials()
        service = gmail_build("gmail", "v1", credentials=creds)
        label_id = get_or_create_label(service, LABEL_NAME)

        if MAIL_TEST_ACTIVE:
            logger.warning(f"[SEND] MODE TEST ACTIF — tous les emails partent vers {MAIL_TEST}")

        sent_records = []

        for path in application_paths:
            application_data = load_json(str(Path(path).parent), Path(path).stem)
            offer_id = application_data["offer_id"]
            id_contact = application_data["id_contact"]
            real_contact_email = application_data["contact_email"]

            # En mode test, on redirige le destinataire mais on garde une
            # trace du contact réel qui aurait été utilisé.
            recipient = MAIL_TEST if MAIL_TEST_ACTIVE else real_contact_email

            # --- Formatage email (candidate_info injecté ici, en mémoire) ---
            email_rendered_greeting = application_data["email"]["greeting_line"]
            email_context = build_context(profile, application_data["email"])
            email_rendered = render_email(email_context)

            # --- Formatage PDF (candidate_info injecté ici, en mémoire) ---
            # Le greeting de la lettre reprend celui de l'email généré pour
            # CE contact précis (email.greeting_line), pas le greeting neutre
            # stocké dans letter (généré sans contact au moment de la
            # rédaction de la lettre, une seule fois par offre) — la lettre
            # et l'email doivent s'adresser à la même personne.
            letter_for_this_contact = {
                **application_data["letter"],
                "greeting_line": email_rendered_greeting,
            }
            pdf_context = {**profile, **letter_for_this_contact}

            # Nom local (chemin disque) : reste technique, sert au tracking
            # local et au nettoyage — jamais vu par le destinataire.
            pdf_path = APPLICATIONS_PATH / f"{offer_id}_{id_contact}_cover_letter.pdf"
            render_pdf(pdf_context, output_path=str(pdf_path))

            # Nom d'affichage (pièce jointe telle que le destinataire la
            # voit) : lisible, basé sur le candidat et l'entreprise ciblée.
            company_name = application_data["job_context"].get("company_name")
            cover_letter_display_name = (
                f"Cover_Letter_{_safe_filename_part(profile.get('candidate_first_name'))}_"
                f"{_safe_filename_part(profile.get('candidate_last_name'))}_"
                f"{_safe_filename_part(company_name, fallback='Company')}.pdf"
            )

            subject = email_rendered["subject"]
            body = email_rendered["body"]

            if MAIL_TEST_ACTIVE:
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
                attachments=[
                    (str(cv_path), cv_display_name),
                    (str(pdf_path), cover_letter_display_name),
                ],
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


    @task(task_id="archive_application")
    def archive_application(sent_records: list[dict], ds=None) -> None:
        """
        Pour chaque candidature envoyée : upload du JSON vers B2 sous
        application/{ds}/{id_offer}_{id_contact}.json, puis supprime les
        fichiers locaux (JSON + PDF temporaire).

        Le tracking en base (analytics.tracking_application) est fait en
        UN SEUL bulk_insert après la boucle, pas un execute() par ligne.
        Le chemin B2 (remote_key) est stocké dans la colonne b2_key, pour
        pouvoir retrouver le JSON archivé depuis une ligne de tracking.
        """
        bucket = Bucket(
            key_id=Variable.get("KEY_ID"),
            app_key=Variable.get("APPLICATION_KEY"),
            bucket_name=Variable.get("BUCKET_NAME"),
        )

        tracking_rows = []  # accumulé pour le bulk_insert final

        for record in sent_records:
            path = record["path"]
            offer_id = record["offer_id"]
            id_contact = record["id_contact"]

            remote_key = f"application/{ds}/{offer_id}_{id_contact}.json"

            try:
                file_data = bucket.upload_file(bucket_path=remote_key, local_path=path)
            except Exception as e:
                logger.warning(f"[ARCHIVE] offer_id={offer_id} id_contact={id_contact} status=upload_failed err={e}")
                continue

            if file_data is None:
                logger.warning(f"[ARCHIVE] offer_id={offer_id} id_contact={id_contact} status=upload_failed")
                continue

            tracking_rows.append((
                offer_id,
                record.get("id_location"),
                record.get("id_company"),
                id_contact,
                remote_key,
            ))

            # Nettoyage local uniquement après confirmation d'upload
            os.remove(path)

            pdf_path = APPLICATIONS_PATH / f"{offer_id}_{id_contact}_cover_letter.pdf"
            if pdf_path.exists():
                os.remove(pdf_path)

            logger.info(f"[ARCHIVE] offer_id={offer_id} id_contact={id_contact} remote={remote_key} status=success")

        track_application_sent(tracking_rows)

        logger.info(f"[ARCHIVE] date={ds} total={len(tracking_rows)} status=success")


    application_paths = generate_content()
    sent_records = build_and_send(application_paths)
    archive_application(sent_records)


automated_application()