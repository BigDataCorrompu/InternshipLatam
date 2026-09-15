from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

from datetime import datetime, timedelta
import logging

from datasets import BLACKLIST
from sheet_reader import fetch_form_responses

logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________________________________________________
SPREADSHEET_ID = Variable.get("SPREADSHEET_ID")

# Nom de l'onglet dans la Sheet — ajuste via la Variable Airflow
# SHEET_RANGE_NAME si le nom réel diffère de ce défaut.
SHEET_RANGE_NAME = Variable.get(
    "SHEET_RANGE_NAME",
    default_var="Réponses au formulaire 1!A:Z",
)

# Colonne exacte du formulaire contenant l'email à exclure — seule donnée
# retenue. Le reste (raison, entreprise, poste, etc.) reste uniquement
# dans la Google Sheet, jamais dupliqué en DB.
EMAIL_COLUMN = "Exact Email Address to be excluded"

SCHEDULE = "0 6 * * *"  # une fois par jour


# ___ HELPERS _________________________________________________________________

def get_db():
    from database import Database

    return Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )


def add_to_blacklist(rows: list[dict]) -> int:
    """
    Pour chaque réponse du formulaire, ajoute l'email à analytics.blacklist
    en un seul bulk_insert. Idempotent (ON CONFLICT DO NOTHING).

    Returns:
        Nombre de nouveaux emails effectivement ajoutés (hors doublons et
        emails déjà blacklistés).
    """
    db = get_db()

    emails = {
        row.get(EMAIL_COLUMN, "").strip().lower()
        for row in rows
        if row.get(EMAIL_COLUMN, "").strip()
    }

    if not emails:
        return 0

    data = [(email,) for email in emails]  # liste de tuples à 1 colonne

    result = db.bulk_insert(
        table="analytics.blacklist",
        columns=["email"],
        data=data,
        onConflict="nothing",
        conflict_columns=["email"],
        returning=["email"],
    )

    added = len(result) if result else 0

    logger.info(
        f"[BLACKLIST] submitted={len(emails)} added={added} "
        f"already_present={len(emails) - added} status=success"
    )

    return added


# ___ DAG _____________________________________________________________________

@dag(
    dag_id='blacklist_sync',
    start_date=datetime(2026, 6, 7),
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["application", "blacklist"],
    default_args={
        'owner': 'internship_latam',
        'retries': 1,
        'retry_delay': timedelta(minutes=15),
    },
)
def blacklist_sync():

    @task(task_id="sync_blacklist_from_form", outlets=[BLACKLIST])
    def sync_blacklist_from_form():
        """
        Lit les réponses du Google Form (demandes d'exclusion), extrait
        uniquement l'email de chaque ligne, et l'ajoute à
        analytics.blacklist (par email direct, sans FK).
        """
        logger.info("→ Lecture de la Google Sheet...")
        rows = fetch_form_responses(
            spreadsheet_id=SPREADSHEET_ID,
            range_name=SHEET_RANGE_NAME,
        )

        if not rows:
            raise AirflowSkipException("Aucune réponse dans la Sheet")

        logger.info(f"→ {len(rows)} ligne(s) trouvée(s), traitement...")
        added = add_to_blacklist(rows)

        logger.info(f"[BLACKLIST] total_rows={len(rows)} added={added} status=success")

    sync_blacklist_from_form()


blacklist_sync()