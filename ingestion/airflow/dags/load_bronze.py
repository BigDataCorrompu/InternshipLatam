from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

from mapper import JsearchMapper, CareerjetMapper
from database import Database
from bucket import Bucket
from datasets import B2_JSEARCH, B2_CAREERJET, BRONZE_OFFERS

from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import logging
import json

logger = logging.getLogger(__name__)

SCHEDULE = "0 21 * * *"
JOB_OFFER_TABLE = 'raw.job_offer'
TRACKING_TABLE = 'landing.ingestion_tracking'
DATA_TYPE = "job_offer"

SOURCES = ["jsearch", "careerjet"]
MAPPERS = {
    "jsearch": JsearchMapper(),
    "careerjet": CareerjetMapper(),
}


@dag(
    dag_id='load_to_bronze',
    start_date=datetime(2026, 6, 7),
    schedule=[B2_JSEARCH, B2_CAREERJET],
    catchup=False,
    max_active_runs=1,
    tags=["ingestion", "bronze", "load"],
    default_args={
        'owner': 'internship_latam',
        'retries': 2,
        'retry_delay': timedelta(seconds=20)
        
        }
)
def load_to_bronze():

    for source in SOURCES:
        @task(task_id=f"load_{source}")
        def load(source=source):
            _load_source(source)
        load()


def _dedupe_by_id_job(rows: list[tuple], id_index: int = 0) -> list[tuple]:
    """Supprime les doublons intra-batch par id_job (ON CONFLICT ne gère pas les doublons du même INSERT)."""
    seen = {}
    for row in rows:
        seen[row[id_index]] = row   # dernière occurrence gagne
    return list(seen.values())


def _load_source(source: str) -> None:
    bucket = Bucket(
        key_id=Variable.get("KEY_ID"),
        app_key=Variable.get("APPLICATION_KEY"),
        bucket_name=Variable.get("BUCKET_NAME"),
    )
    db_neon = Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",        default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )

    # 1 — Liste les fichiers B2 de cette source
    prefix = f"{DATA_TYPE}/"
    all_files = bucket.list_all_files()
    source_files = {
        name: meta for name, meta in all_files.items()
        if f"/{source}/" in name and name.startswith(prefix)
    }

    if not source_files:
        raise AirflowSkipException(f"[LOAD] source={source} status=no_files_in_bucket")

    # 2 — Récupère les file_id déjà chargés (détecte les réécritures : nouveau contenu = nouveau file_id)
    already_loaded = db_neon.execute(
        f"SELECT b2_file_id FROM {TRACKING_TABLE} WHERE status = 'success'"
    )
    loaded_ids = {r["b2_file_id"] for r in already_loaded}

    to_load = {
        name: meta for name, meta in source_files.items()
        if meta["id"] not in loaded_ids
    }

    if not to_load:
        raise AirflowSkipException(f"[LOAD] source={source} status=nothing_new")

    logger.info(f"[LOAD] source={source} files_to_load={len(to_load)}")

    mapper = MAPPERS[source]

    # 3 — Pour chaque fichier B2 : download → parse → normalise → insert
    for b2_key, meta in to_load.items():
        b2_file_id = meta["id"]

        try:
            # Download dans un fichier temporaire
            with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
                tmp_path = tmp.name
            bucket.download_file_by_name(b2_key, tmp_path)

            blocks = json.loads(Path(tmp_path).read_text(encoding="utf-8"))
            Path(tmp_path).unlink(missing_ok=True)

            # Normalise
            all_data = []
            for block in blocks:
                params = block.get("params") or {}
                data   = block.get("data")   or []
                for d in data:
                    try:
                        all_data.append(mapper.normalise(data=d, metaData=params))
                    except Exception as e:
                        logger.warning(f"[LOAD] source={source} b2_key={b2_key} skip_record err={e}")

            if not all_data:
                logger.warning(f"[LOAD] source={source} b2_key={b2_key} status=no_valid_records")
                db_neon.bulk_insert(
                    table=TRACKING_TABLE,
                    columns=["b2_file_id", "b2_key", "source", "data_type", "record_count", "status"],
                    data=[(b2_file_id, b2_key, source, DATA_TYPE, 0, "success")],
                )
                continue

            # Structure + dédup intra-batch par id_job
            data_to_insert = mapper.structureToBulkInsert(all_data)
            deduped = _dedupe_by_id_job(data_to_insert["data"], id_index=0)  # 0 = id_job dans JobOffer

            logger.info(
                f"[LOAD] source={source} b2_key={b2_key} "
                f"records={len(data_to_insert['data'])} after_dedupe={len(deduped)}"
            )

            # Insert Bronze (idempotent)
            db_neon.bulk_insert(
                table=JOB_OFFER_TABLE,
                columns=data_to_insert["columns"],
                data=deduped,
                onConflict="nothing",
                conflict_columns=["id_job"],
            )

            # Tracking success
            db_neon.bulk_insert(
                table=TRACKING_TABLE,
                columns=["b2_file_id", "b2_key", "source", "data_type", "record_count", "status"],
                data=[(b2_file_id, b2_key, source, DATA_TYPE, len(deduped), "success")],
            )
            logger.info(f"[LOAD] source={source} b2_key={b2_key} inserted={len(deduped)} status=success")

        except Exception as e:
            logger.error(f"[LOAD] source={source} b2_key={b2_key} status=failed err={e}")
            db_neon.bulk_insert(
                table=TRACKING_TABLE,
                columns=["b2_file_id", "b2_key", "source", "data_type", "record_count", "status", "error_message"],
                data=[(b2_file_id, b2_key, source, DATA_TYPE, 0, "failed", str(e)[:500])],
            )
            raise


load_to_bronze()