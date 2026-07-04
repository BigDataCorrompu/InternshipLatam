from airflow.decorators import dag, task
from airflow.models import Variable
from datetime import datetime

from staging_to_silver import transfer_staging_to_silver
from database import Database


@dag(
    dag_id='staging_to_silver',
    start_date=datetime(2026, 6, 7),
    schedule="0 20 * * *",
    catchup=False,
    max_active_runs=1,
    tags=["silver", "load", "analytics"],
    default_args={'owner': 'internship_latam'}
)
def staging_to_silver():

    @task(task_id="transfer")
    def transfer():
        db_staging = Database(
            db_host=Variable.get("LOCAL_DB_HOST"),
            db_name=Variable.get("LOCAL_DB_NAME"),
            db_user=Variable.get("LOCAL_DB_USER"),
            db_password=Variable.get("LOCAL_DB_PASSWORD"),
            db_sslmode="disable",
            db_channelbinding="disable",
            mode="psycopg2",
        )
        db_silver = Database(
            db_host=Variable.get("DB_HOST"),
            db_name=Variable.get("DB_NAME"),
            db_user=Variable.get("DB_USER"),
            db_password=Variable.get("DB_PASSWORD"),
            db_sslmode=Variable.get("DB_SSLMODE", default_var="require"),
            db_channelbinding=Variable.get("DB_CHANNELBIDING", default_var="disable"),
            mode="http",
        )
        transfer_staging_to_silver(db_staging, db_silver)

    transfer()


staging_to_silver()