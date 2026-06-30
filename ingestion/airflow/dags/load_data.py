from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException


from mapper import JsearchMapper, CareerjetMapper
from database import Database

from datetime import datetime
import logging
import json

logger = logging.getLogger(__name__)

SCHEDULE = "0 8 * * *"
JOB_OFFER_TABLE = 'raw.job_offer'

MAPPERS = {
    "jsearch": JsearchMapper(),
    "careerjet": CareerjetMapper(),
}

@dag(
    dag_id='load_to_bronze',
    start_date=datetime(2026, 6, 7),
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["ingestion", "bronze", "load"],
    default_args={'owner': 'internship_latam'}
)
def load_to_bronze():

    @task(task_id="load_jsearch")
    def load_jsearch():
        _load_source("jsearch")

    @task(task_id="load_careerjet")
    def load_careerjet():
        _load_source("careerjet")

    [load_jsearch(), load_careerjet()]


def _load_source(source: str) -> None:
    # 1 — Récupère les lignes non pushées depuis landing
    db_local = Database(
        db_host           = Variable.get("LOCAL_DB_HOST"),
        db_name           = Variable.get("LOCAL_DB_NAME"),
        db_user           = Variable.get("LOCAL_DB_USER"),
        db_password       = Variable.get("LOCAL_DB_PASSWORD"),
        db_sslmode        = "disable",
        db_channelbinding = "disable",
    )

    rows_landing = db_local.execute(
        """
        SELECT id, params, data 
        FROM landing.raw_job_offers
        WHERE source = %s
        AND id NOT IN (
            SELECT raw_offer_id FROM landing.push_history WHERE status = 'success'
        )
        """,
        params=(source,)
    )

    if not rows_landing:
        raise AirflowSkipException(f"[LOAD] source={source} status=no_pending_data")

    # 2 — Normalise via mapper
    mapper = MAPPERS[source]
    all_data = []

    for row in rows_landing:
        raw_offer_id = row["id"]
        params = row["params"] or {}
        data   = row["data"]   or []

        for d in data:
            try:
                job = mapper.normalise(data=d, metaData=params)
                all_data.append(job)
            except Exception as e:
                logger.warning(f"[LOAD] source={source} raw_offer_id={raw_offer_id} skip err={e}")

        logger.info(f"[LOAD] source={source} raw_offer_id={raw_offer_id} records={len(data)}")

    if not all_data:
        raise AirflowSkipException(f"[LOAD] source={source} status=no_valid_records")

    # 3 — Push vers Bronze Neon
    db_neon = Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",        default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBINDING", default_var="disable"),
    )

    data_to_insert = mapper.structureToBulkInsert(all_data)
    db_neon.bulk_insert(
        table=JOB_OFFER_TABLE,
        columns=data_to_insert["columns"],
        data=data_to_insert["data"],
    )

    # 4 — Marque comme pushé dans push_history
    ids = [row["id"] for row in rows_landing]
    push_rows = [(rid, "success", None) for rid in ids]
    db_local.bulk_insert(
        table="landing.push_history",
        columns=["raw_offer_id", "status", "error_message"],
        data=push_rows,
    )

    logger.info(f"[LOAD] source={source} records={len(all_data)} status=success")


load_to_bronze()