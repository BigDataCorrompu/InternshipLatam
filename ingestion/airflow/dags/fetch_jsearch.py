from airflow.decorators import dag, task, task_group
from airflow.models import Variable
from airflow.utils.trigger_rule import TriggerRule
from airflow.exceptions import AirflowSkipException

# Ingestion python scripts
from utils import write_json, load_json, save_to_landing 
from APIendpoint import JsearchAPI    
from database import Database

from datetime import datetime, timedelta
from pathlib import Path
import logging
import os
import json
logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________________________________________________
RAW_PATH = Path(os.getenv('RAW_DATA_PATH', '/opt/airflow/raw'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))

# Parameter of frequency
SCHEDULE_PERIOD = 3 # 3 days
SCHEDULE = "0 7 */3 * *"

JOB_OFFER_TABLE = 'raw.job_offer'
JSEARCH_CONFIG = "jsearch_search_config"
RAW_FILE_JSEARCH = "api_jsearch"
FILE_NAME = 'jsearch_search'

SOURCE = "jsearch"



@dag(
    dag_id='fetch_jsearch_pipeline',
    start_date=datetime(2026, 6, 7), 
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags = ["ingestion", "job_offer", "landing"],
    default_args={
        'owner': 'internship_latam',
    }
)
def fetch_jsearch_pipeline():


    @task(task_id="fetch_jsearch")
    def fetch_jsearch(ds=None) -> None:
        # Setup config
        raw = load_json(str(CONFIG_PATH), JSEARCH_CONFIG) # file
        api_key = Variable.get('JSEARCH_APP_KEY') # api key
        jsearch = JsearchAPI(api_key) # request object
        all_responses = list()

        # API call
        params = raw.get("default_params", {}) # get api call paremeter
        for q in raw.get('queries', []):
            q_copy = q.copy()
            query = q_copy.pop('query') # get mandatory jsearch parameter
            config = params | q_copy
            try:
                jobs = jsearch.search_jobs(query=query, paginate=True, **config)
            except Exception as e:
                logger.warning(f"[EXTRACT] source=jsearch query='{query}' status=error err={e}")
                jobs = []
            all_responses.append({
                "params": {'query': query} | config,
                "data" : jobs
            })
            logger.info(f"[EXTRACT] source=jsearch query='{query}' records={len(jobs)}")

            # Gestion quota api    
            if jsearch.quota_exceeded:
                logger.warning(f"[Extract] source=jsearch exhausted — stopped after query='{query}'")
                break

        # Load raw in local file
        directory = RAW_PATH / ds / RAW_FILE_JSEARCH
        directory.mkdir(parents=True, exist_ok=True) # Create file if doesn't exist
        write_json(str(directory), 'jsearch_search', all_responses)

        total = sum(len(r['data']) for r in all_responses)
        logger.info(f"[EXTRACT] source=jsearch date={ds} total={total} status=success")

        # Gestion quota api
        if jsearch.quota_exceeded and total == 0:               # quota ended and nothing collected -> skip
            raise AirflowSkipException("Jsearch quota exhausted, no offer collected")
            # CAN USE A SECOND API KEY HERE

        return str(directory)
    

    
    @task(task_id="save_to_landing")
    def save_to_landing_task(directory: str) -> None:
        count = save_to_landing(
                        source=SOURCE,
                        directory=directory,
                        filename=FILE_NAME,
                        db_config={
                            "db_host": Variable.get("LOCAL_DB_HOST"),
                            "db_name": Variable.get("LOCAL_DB_NAME"),
                            "db_user": Variable.get("LOCAL_DB_USER"),
                            "db_password": Variable.get("LOCAL_DB_PASSWORD"),
                            "db_sslmode": "disable",
                            "db_channelbinding": "disable",
                        }
                    )
        
        if count == 0:
            raise AirflowSkipException(f"source={SOURCE} status=no_data")

    save_to_landing_task(fetch_jsearch())

fetch_jsearch_pipeline()