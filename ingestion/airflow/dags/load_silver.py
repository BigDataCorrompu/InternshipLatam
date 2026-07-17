from airflow.decorators import task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException
from pathlib import Path
import logging

from database import Database
from datasets import SILVER_ANALYTICS

logger = logging.getLogger(__name__)

# Dossier contenant tes 6 fichiers SQL nettoyés
SQL_DIR = "/opt/airflow/pipeline/sql/staging_to_silver/"

@task(task_id="transfer", outlets=[SILVER_ANALYTICS])
def transfer():
    db = Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )

    # 0 — Vérification s'il y a du travail
    pending = db.execute("""
        SELECT COUNT(*) AS n
        FROM staging.enriched_offers s
        LEFT JOIN analytics.job_offer o ON o.id_offer = s.id_offer
        WHERE o.id_offer IS NULL;
    """)
    
    if pending[0]["n"] == 0:
        raise AirflowSkipException("[SILVER] nothing to transfer")

    # 1 — Chargement et exécution des 6 fichiers SQL
    # Le sorted() garantit l'ordre 01, 02, ..., 06
    sql_path = Path(SQL_DIR)
    sql_files = sorted(list(sql_path.glob("*.sql")))

    for sql_file in sql_files:
        logger.info(f"[SILVER] Executing {sql_file.name}...")
        
        # On lit le fichier entier (sans split, sans filtre de commentaires)
        statement = sql_file.read_text()
        
        # Exécution directe
        db.execute(statement)
        logger.info(f"[SILVER] {sql_file.name} completed successfully")

    logger.info(f"[SILVER] Transferred {pending[0]['n']} records successfully.")