from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException
import traceback
from datasets import BRONZE_OFFERS, STAGING_ENRICHED
from database import Database


from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

SAVE_EVERY = 10        # flush vers staging tous les N enrichissements
MAX_PER_RUN = 3     # None = tout ; un int pour lisser le rattrapage




SELECT_PENDING = """
    SELECT b.*
    FROM raw.job_offer b
    LEFT JOIN staging.enriched_offers s ON s.id_offer = b.id_job
    WHERE s.id_offer IS NULL
"""

SELECT_PROFILE = """
    SELECT id_prompt, prompt
    FROM analytics.prompt_relevancy
    ORDER BY created_at DESC
    LIMIT 1
"""


def get_db() -> Database:
    return Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )


@dag(
    dag_id='silver_enrichment',
    start_date=datetime(2026, 6, 7),
    schedule=[BRONZE_OFFERS],
    catchup=False,
    max_active_runs=1,
    tags=["silver", "enrichment", "llm"],
    default_args={'owner': 'internship_latam'},
)
def silver_enrichment():

    @task(task_id="enrich", outlets=[STAGING_ENRICHED])
    def enrich():
        # Import local : le graph instancie LLM + PlacesAPI au niveau module.
        # Au parsing du DAG (toutes les 30s), ça recréerait les clients pour rien.
        from graph_silver_enrichment import graph
        from silver_enrichment import map_bronze_to_JobOfferState, map_prompt_to_JobOfferState
        from LLMprovider import LLM
        llm = LLM() 
        llm_model_name = llm.enrichement.model

        db = get_db()

        # 1 — Profil utilisateur
        prompt_rows = db.execute(SELECT_PROFILE)
        if not prompt_rows:
            raise ValueError("Aucun profil dans analytics.prompt_relevancy")
        profile_state = map_prompt_to_JobOfferState(prompt_rows[0])

        # 2 — Offres non enrichies (JOIN interbase, plus de filtre Python)
        pending = db.execute(SELECT_PENDING)
        if MAX_PER_RUN:
            pending = pending[:MAX_PER_RUN]

        if not pending:
            raise AirflowSkipException("[ENRICH] status=nothing_to_enrich")

        logger.info(f"[ENRICH] pending={len(pending)}")

        # 3 — Boucle séquentielle + flush incrémental
        buffer, ok, ko = [], 0, 0


        def flush():
            nonlocal buffer
            if not buffer:
                return
            db.bulk_insert(
                table="staging.enriched_offers",
                columns=["id_offer", "raw_result", "llm_model"],
                data=buffer,
            )
            buffer = []

        for i, row in enumerate(pending, 1):
            id_job = row["id_job"]
            try:
                state = map_bronze_to_JobOfferState(row) | profile_state
                result = graph.invoke(state)

                buffer.append((id_job, json.dumps(result, default=str), llm_model_name))
                ok += 1
                logger.info(f"[ENRICH] {i}/{len(pending)} id={id_job} score={result.get('score_relevancy')}")

            except Exception as e:
                ko += 1
                logger.warning(f"[ENRICH] {i}/{len(pending)} id={id_job} status=failed err={e}")
                logger.warning(traceback.format_exc())

            if len(buffer) >= SAVE_EVERY:
                flush()

        flush()
        logger.info(f"[ENRICH] done ok={ok} failed={ko} total={len(pending)}")

    enrich()


silver_enrichment()