# ──────────────────────────────────────────
# DAG: staging_to_silver_contacts
# ──────────────────────────────────────────
from airflow.decorators import dag, task
from datetime import datetime
from airflow.models import Variable
from pathlib import Path
from database import Database
from datasets import FETCH_CONTACTS, SILVER_CONTACTS 
import logging
logger = logging.getLogger(__name__)

SQL_DIR = "/opt/airflow/pipeline/sql/staging_to_silver_contact/"


@dag(
    dag_id="staging_to_silver_contacts",
    start_date=datetime(2026, 6, 7),
    schedule=[FETCH_CONTACTS],
    catchup=False,
    max_active_runs=1,
    tags=["silver", "contacts"],
    default_args={"owner": "internship_latam", "retries": 1},
)
def staging_to_silver_contacts_dag():

    @task(task_id="transform", outlets=[SILVER_CONTACTS])
    def flatten_and_dedupe_contacts() -> None:
        db = Database(
            db_host           = Variable.get("DB_HOST"),
            db_name           = Variable.get("DB_NAME"),
            db_user           = Variable.get("DB_USER"),
            db_password       = Variable.get("DB_PASSWORD"),
            db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
            db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
        )
        sql_path = Path(SQL_DIR)
        sql_files = sorted(list(sql_path.glob("*.sql")))
        
        for sql_file in sql_files:
            logger.info(f"[SILVER] Executing {sql_file.name}...")
            
            # On lit le fichier entier (sans split, sans filtre de commentaires)
            statement = sql_file.read_text()
            
            # Exécution directe
            db.execute(statement)
            logger.info(f"[SILVER] {sql_file.name} completed successfully")

        print("✅ staging_to_silver_contacts: transform completed")

    flatten_and_dedupe_contacts()


staging_to_silver_contacts_dag()