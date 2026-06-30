from airflow.decorators import dag, task, task_group
from airflow.models import Variable
from airflow.utils.trigger_rule import TriggerRule
from airflow.exceptions import AirflowSkipException

from database import Database

from datetime import datetime
import logging
logger = logging.getLogger(__name__)

SCHEDULE = "0 0 * * *"

# SQL Requests
GOLD_JOB_OFFER = 'SELECT serving.refresh_job_offer_if_stale();'

@dag(
    dag_id='update_views',
    start_date=datetime(2026, 6, 7), 
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags = ["ingestion", "job_offer", "landing"],
    default_args={
        'owner': 'internship_latam',
    }
)
def update_views():

    @task
    def gold_job_offer_task():
        db = Database(
            db_host           = Variable.get("DB_HOST"),
            db_name           = Variable.get("DB_NAME"),
            db_user           = Variable.get("DB_USER"),
            db_password       = Variable.get("DB_PASSWORD"),
            db_sslmode        = Variable.get("DB_SSLMODE",        default_var="require"),
            db_channelbinding = Variable.get("DB_CHANNELBINDING", default_var="disable"),
        )
        db.execute(GOLD_JOB_OFFER)

    gold_job_offer_task()


update_views()