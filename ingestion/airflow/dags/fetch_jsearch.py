from airflow.decorators import dag, task, task_group
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

# Ingestion python scripts
from utils import write_json, load_json, save_to_landing_bucket
from APIendpoint import JsearchAPI    
from bucket import Bucket
from datasets import B2_RAW  

from datetime import datetime, timedelta
from pathlib import Path
import logging
import os
logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________________________________________________
RAW_PATH = Path(os.getenv('RAW_DATA_PATH', '/opt/airflow/raw'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))

# Parameter of frequency
SCHEDULE_PERIOD = 3 # 3 days
SCHEDULE = "0 20 */3 * *"

JOB_OFFER_TABLE = 'raw.job_offer'
CONFIG = "jsearch_search_config"
RAW_FILE = "api_jsearch"
FILE_NAME = 'jsearch_search'

SOURCE = "jsearch"
DATA_TYPE = "job_offer"



@dag(
    dag_id='fetch_jsearch_pipeline',
    start_date=datetime(2026, 6, 7), 
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags = ["ingestion", "job_offer", "landing"],
    default_args={
        'owner': 'internship_latam',
        'retries': 1,
        'retry_delay': timedelta(minutes=30)
    }
)
def fetch_jsearch_pipeline():


    @task(task_id="fetch_jsearch")
    def fetch_jsearch(ds=None) -> str:
        # Setup config
        raw = load_json(str(CONFIG_PATH), CONFIG) # file
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
                logger.warning(f"[EXTRACT] source={SOURCE} query='{query}' status=error err={e}")
                jobs = []
            all_responses.append({
                "params": {'query': query} | config,
                "data" : jobs
            })
            logger.info(f"[EXTRACT] source={SOURCE} query='{query}' records={len(jobs)}")

            # Gestion quota api    
            if jsearch.quota_exceeded:
                logger.warning(f"[Extract] source={SOURCE} exhausted — stopped after query='{query}'")
                break

        # Load raw in local file
        directory = RAW_PATH / ds / RAW_FILE
        directory.mkdir(parents=True, exist_ok=True) # Create file if doesn't exist
        file_path = directory / f"{FILE_NAME}.json"
        write_json(str(directory), FILE_NAME, all_responses)

        total = sum(len(r['data']) for r in all_responses)
        logger.info(f"[EXTRACT] source={SOURCE} date={ds} total={total} status=success")

        # Gestion quota api
        if jsearch.quota_exceeded and total == 0:               # quota ended and nothing collected -> skip
            raise AirflowSkipException("Jsearch quota exhausted, no offer collected")
            # CAN USE A SECOND API KEY HERE

        return str(file_path)
    

    
    @task(task_id="save_to_landing", outlets=[B2_RAW])
    def save_to_landing_task(file_path: str, ds=None, ts_nodash=None) -> None:
        from utils import save_to_landing_bucket
        from bucket import Bucket
        bucket = Bucket(
            key_id=Variable.get("KEY_ID"),
            app_key=Variable.get("APPLICATION_KEY"),
            bucket_name=Variable.get("BUCKET_NAME"),
        )
        file_data = save_to_landing_bucket(
            bucket=bucket,
            api_source=SOURCE,
            local_file=file_path,
            data_type=DATA_TYPE,
            ds=ds,
            ts_nodash=ts_nodash,
        )

        if file_data is None:
            raise AirflowSkipException(f"source={SOURCE} status=no_data")
        logger.info(f"[LOAD] source={SOURCE} date={ds} status=success")

    save_to_landing_task(fetch_jsearch())

fetch_jsearch_pipeline()