from airflow.decorators import dag, task, task_group
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException

# Ingestion python scripts
from utils import write_json, load_json, save_to_landing_bucket
from APIendpoint import CareerJetAPI  
from bucket import Bucket
from datasets import B2_CAREERJET  

from datetime import datetime
from pathlib import Path
import logging
import os
logger = logging.getLogger(__name__)



# *   *   *   *   *   /path/to/command
# │   │   │   │   │
# │   │   │   │   └─── Day of the week (0 - 6) (0 is Sunday, 1 is Monday, etc.)
# │   │   │   └──────── Month of the year (1 - 12)
# │   │   └───────────── Day of the month (1 - 31)
# │   └────────────────── Hour of the day (0 - 23, in 24-hour format)
# └────────────────────── Minute of the hour (0 - 59)

# ___ CONSTANTS _______________________________________________________________
RAW_PATH = Path(os.getenv('RAW_DATA_PATH', '/opt/airflow/raw'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))

# PARAMETRE DE PEUPLEMENT
MAX_PAGE_CAREERJET = 10
MAX_DAYS_CAREERJET = 2

# Parameter of frequency
SCHEDULE_PERIOD = 1 # 3 days
SCHEDULE = "0 19 * * *"

JOB_OFFER_TABLE = 'raw.job_offer'
CONFIG = "careerjet_search_config"
RAW_FILE = "api_careerjet"
FILE_NAME = 'careerjet_search'

SOURCE = "careerjet"
DATA_TYPE = "job_offer"



@dag(
    dag_id='fetch_careerjet_pipeline',
    start_date=datetime(2026, 6, 7), 
    schedule=SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags = ["ingestion", "job_offer", "landing"],
    default_args={
        'owner': 'internship_latam',
    }
)
def fetch_careerjet_pipeline():

    @task(task_id="fetch_careerjet")
    def fetch_careerjet(ds=None) -> str:
        # Setup config
        raw  = load_json(str(CONFIG_PATH), CONFIG)
        api_key = Variable.get('CAREERJET_APP_KEY')
        user_ip = Variable.get('SERVER_IP')
        user_agent = Variable.get('CAREERJET_USER_AGENT')
        careerjet = CareerJetAPI(
            api_key=api_key, 
            user_ip=user_ip, 
            user_agent=user_agent, 
            days_max_offer=MAX_DAYS_CAREERJET,
        )
        all_responses = list()

        # Call API
        params = raw.get("default_params", {}) # get api call paremeter
        for q in raw.get('queries', []):
            config = params | q
            jobs = careerjet.search_jobs(paginate=True, max_pages=MAX_PAGE_CAREERJET, **config)
            all_responses.append({
                'params': config,
                'data': jobs
            })
            keywords_debug = q.get('keywords', {})
            logger.info(f"[EXTRACT] source={SOURCE} keyword={keywords_debug} records={len(jobs)}")
            
            # Gestion quota api    
            if careerjet.quota_exceeded:
                logger.warning(f"[Extract] source={SOURCE} exhausted — stopped after keyword={keywords_debug}")
                break

        # Load raw in local file
        directory = RAW_PATH / ds / RAW_FILE
        directory.mkdir(parents=True, exist_ok=True) # Create file if doesn't exist
        file_path = directory / f"{FILE_NAME}.json"
        write_json(str(directory), FILE_NAME, all_responses)
        total = sum(len(r['data']) for r in all_responses)
        logger.info(f"[EXTRACT] source={SOURCE} date={ds} total={total} status=success")

        # Gestion quota api  
        if careerjet.quota_exceeded and total == 0:               # quota ended and nothing collected -> skip
            raise AirflowSkipException("CareerJet quota exhausted, no offer collected")
            # CAN USE A SECOND API KEY HERE

        return str(file_path)
    

    @task(task_id="save_to_landing", outlets=[B2_CAREERJET])
    def save_to_landing_task(file_path: str, ds=None) -> None:
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
        )

        if file_data is None:
            raise AirflowSkipException(f"source={SOURCE} status=no_data")
        logger.info(f"[LOAD] source={SOURCE} date={ds} status=success")
        

    save_to_landing_task(fetch_careerjet())

fetch_careerjet_pipeline()