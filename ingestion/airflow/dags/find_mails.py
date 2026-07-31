from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

from database import Database
from datasets import SILVER_OFFERS, SILVER_CONTACTS

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


# 


@dag(
    dag_id='load_to_bronze',
    start_date=datetime(2026, 6, 7),
    schedule=[SILVER_OFFERS],
    catchup=False,
    max_active_runs=1,
    tags=["analytics", "silver", "load", "contacts"],
    default_args={'owner': 'internship_latam', 'retries': 1},
)