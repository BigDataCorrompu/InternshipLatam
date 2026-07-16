# start_task >> [fetch_task >> load_task] >> end_task
from airflow.decorators import dag, task, task_group
from airflow.models import Variable
from airflow.utils.trigger_rule import TriggerRule
from airflow.exceptions import AirflowSkipException

# Ingestion python scripts
from utils import write_json, load_json        
from APIendpoint import JsearchAPI, CareerJetAPI  
from mapper import JsearchMapper, CareerjetMapper, JobMapper   
from database import Database

from datetime import datetime, timedelta
from pathlib import Path
import logging
import os
logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________________________________________________
RAW_PATH = Path(os.getenv('RAW_DATA_PATH', '/opt/airflow/raw'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))

# PARAMETRE DE PEUPLEMENT
MAX_PAGE_CAREERJET = 50
MAX_DAYS_CAREERJET = 30

# Parameter of frequency
SCHEDULE_PERIOD = 3 # 3 days

JOB_OFFER_TABLE = 'raw.job_offer'
CONFLICT_COLUMNS = ['id_job']
CAREERJET_CONFIG = "careerjet_search_config"
JSEARCH_CONFIG = "jsearch_search_config"
RAW_FILE_JSEARCH = "api_jsearch"
RAW_FILE_CAREERJET = "api_careerjet"

# ___ FETCH _______________________________________________________________
@task(task_id="fetch_job_jsearch")
def fetch_job_jsearch(ds=None) -> None:
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


@task(task_id="fetch_job_careerjet")
def fetch_job_careerjet(ds=None) -> None:
    # Setup config
    raw  = load_json(str(CONFIG_PATH), CAREERJET_CONFIG)
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

    params = raw.get("default_params", {}) # get api call paremeter
    for q in raw.get('queries', []):
        config = params | q
        jobs = careerjet.search_jobs(paginate=True, max_pages=MAX_PAGE_CAREERJET, **config)
        all_responses.append({
            'params': config,
            'data': jobs
        })
        keywords_debug = q.get('keywords', {})
        logger.info(f"[EXTRACT] source=careerjet keyword={keywords_debug} records={len(jobs)}")
        
        # Gestion quota api    
        if careerjet.quota_exceeded:
            logger.warning(f"[Extract] source=jsearch exhausted — stopped after keyword={keywords_debug}")
            break

    # Load raw in local file
    directory = RAW_PATH / ds / RAW_FILE_CAREERJET
    directory.mkdir(parents=True, exist_ok=True) # Create file if doesn't exist
    write_json(str(directory), 'careerjet_search', all_responses)
    total = sum(len(r['data']) for r in all_responses)
    logger.info(f"[EXTRACT] source=careerjet date={ds} total={total} status=success")

    # Gestion quota api  
    if careerjet.quota_exceeded and total == 0:               # quota ended and nothing collected -> skip
        raise AirflowSkipException("CareerJet quota exhausted, no offer collected")
        # CAN USE A SECOND API KEY HERE



# ___ LOAD _______________________________________________________________
# Helper shared
def _load_source(api: str, ds=None) -> None:
    SOURCES = {
        RAW_FILE_JSEARCH: (JsearchMapper(), 'jsearch_search'),
        RAW_FILE_CAREERJET: (CareerjetMapper(), 'careerjet_search'),
    }
    mapper, filename = SOURCES[api]
    directory = RAW_PATH / ds / api
    all_data = list()

    for json_file in Path(directory).glob("*.json"):
        filename = json_file.stem

        blocks = load_json(str(directory), filename) or [] # Modif against skip if no data for a request
        
        for block in blocks:
            params = block.get("params") or {}
            data = block.get("data") or []
            logger.info(f"[DEBUG] block params={params} jobs={len(data)}")
            for d in data:
                try:
                    rows = mapper.normalise(
                        data=d, 
                        metaData=params
                    )
                    all_data.append(rows)
                except Exception as e:
                    logger.warning(f"[LOAD] skip record api={api} err={e}")
        file_records = len(all_data)
        logger.info(f"[LOAD] file={json_file.name} records={file_records}")
    
    if not all_data:
        raise AirflowSkipException(f'Aucune offre {api}')
    data_to_insert = mapper.structureToBulkInsert(all_data)


    
    db = Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",        default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBINDING", default_var="disable"),
    )
    db.bulk_insert(
        JOB_OFFER_TABLE, 
        data_to_insert["columns"],
        data_to_insert["data"]
    )

@task(task_id="load_job_jsearch")
def load_job_jsearch(ds=None) -> None:
    _load_source(RAW_FILE_JSEARCH, ds)


@task(task_id="load_job_careerjet")
def load_job_careerjet(ds=None) -> None:
    _load_source(RAW_FILE_CAREERJET, ds)



@task_group(group_id='jsearch_pipeline')
def jsearch_pipeline() -> None:
    fetch_job_jsearch() >> load_job_jsearch()


@task_group(group_id='careerjet_pipeline')
def careerjet_pipeline() -> None:
    fetch_job_careerjet() >> load_job_careerjet()



# ___ DAG __________________________
@dag(
    dag_id='pipeline_job_offer',
    start_date=datetime(2026, 6, 7), 
    schedule=timedelta(days=SCHEDULE_PERIOD), 
    catchup=False,
    max_active_runs=1,
    tags = ["ingestion", "job_offer", "prod"],
    default_args={
        'owner': 'internship_latam',
    }
)
def pipeline_job_offer() -> None:
    # fetch group
    jsearch_pipeline() 
    careerjet_pipeline()


pipeline_job_offer()