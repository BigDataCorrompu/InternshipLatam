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
from itertools import product
from pathlib import Path
import logging
import os
logger = logging.getLogger(__name__)

# ___ CONSTANTS _______________________
RAW_PATH = Path(os.getenv('RAW_DATA_PATH', '/opt/airflow/raw'))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "/opt/airflow/config"))

SCHEDULE_PERIOD = 3 # 3 days
JOB_OFFER_TABLE = 'raw.job_offer'

# ___ FETCH GROUP _____________________
@task_group(group_id='fetch_job')
def fetch_job_group() -> None:

    @task(task_id="fetch_job_jsearch")
    def fetch_job_jsearch(ds=None) -> None:
        params  = load_json(str(CONFIG_PATH), 'jsearch_search_config')

        api_key = Variable.get('JSEARCH_APP_KEY')
        jsearch = JsearchAPI(api_key)
        all_responses = []

        list_params = {k: v for k, v in params.items() if isinstance(v, list)}
        fixed_params = {k: v for k, v in params.items() if not isinstance(v, list)}
        keys = list(list_params.keys())
        values = list(list_params.values())

        for combination in product(*values):
            config = dict(zip(keys, combination)) | fixed_params
            query = config.pop('query')
            jobs = jsearch.search_jobs(query=query, paginate=True, **config)
            all_responses.append({
                "params": {**config, "query": query},   # garde country/language/query pour le mapper
                "raw": {"data": {"jobs": jobs}},
            })
            logger.info(f"[EXTRACT] source=jsearch query='{query}' records={len(jobs)}")

        directory = RAW_PATH / ds
        directory.mkdir(parents=True, exist_ok=True)  # Create file if doesn't exist
        write_json(directory, 'jsearch_search', all_responses)
        logger.info(f"[EXTRACT] source=jsearch query='{query}' records={len(jobs)}")
        



    @task(task_id="fetch_job_careerjet")
    def fetch_job_careerjet(ds=None) -> None:
        params  = load_json(str(CONFIG_PATH), 'careerjet_search_config')


        api_key = Variable.get('CAREERJET_APP_KEY')
        user_ip = Variable.get('SERVER_IP')
        user_agent = Variable.get('CAREERJET_USER_AGENT')
        careerJet = CareerJetAPI(
            api_key=api_key, 
            user_ip=user_ip, 
            user_agent=user_agent, 
            days_max_offer=SCHEDULE_PERIOD,
        )
        all_responses = []

        list_params = {k: v for k, v in params.items() if isinstance(v, list)}
        fixed_params = {k: v for k, v in params.items() if not isinstance(v, list)}
        keys = list(list_params.keys())
        values = list(list_params.values())

        for combination in product(*values):
            config = dict(zip(keys, combination)) | fixed_params
            jobs = careerJet.search_jobs(paginate=True, **config)
            all_responses.append({
                "params": config,        # contient locale_code -> pays/langue côté mapper
                "raw": {"jobs": jobs},
            })
            logger.info(f"[EXTRACT] source=careerjet records={len(jobs)}")

        directory = RAW_PATH / ds
        directory.mkdir(parents=True, exist_ok=True)  # Create file if doesn't exist
        write_json(directory, 'careerjet_search', all_responses)
        logger.info(f"[EXTRACT] source=careerjet  records={len(all_jobs)}")
        
    

    fetch_job_jsearch()
    fetch_job_careerjet()


# ___ LOAD GROUP _____________________
@task_group(group_id='load_job')
def load_job_group()-> None:

    @task(task_id="load_job_all", trigger_rule=TriggerRule.ALL_DONE)
    def load_job_all(ds=None) -> None:
        directory = RAW_PATH / ds

        jsearch_mapper = JsearchMapper()
        careerjet_mapper = CareerjetMapper()

        all_columns = JobMapper.getColumns()
        all_data = []

        for json_file in Path(directory).glob("*.json"):
            filename = json_file.stem
            blocks = load_json(directory, filename)

            match filename:
                case 'jsearch_search':
                    mapper = jsearch_mapper
                case 'careerjet_search':
                    mapper = careerjet_mapper
                case _:
                    logger.warning(f"[LOAD] file={json_file.name} status=unknown_source")
                    continue

            
            file_records = 0
            for block in blocks:
                data = mapper.getData(block)
                all_data.extend(data['data'])
                file_records += len(data['data'])
            logger.info(f"[LOAD] file={json_file.name} records={len(file_records)}")

        if not all_data:
            logger.warning("[LOAD] aucune donnée collectée — chargement ignoré")
            raise AirflowSkipException("Aucune donnée à charger")
        
        db = Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",        default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBINDING", default_var="disable"),
        )
        
        db.bulk_insert(
            table=JOB_OFFER_TABLE,
            columns=all_columns,
            data=all_data,
        )


    load_job_all()



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
    fetch_job_group() >> load_job_group()


pipeline_job_offer()