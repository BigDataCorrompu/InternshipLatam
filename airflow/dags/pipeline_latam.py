from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
 
default_args = {
    "owner": "latam",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}
 
with DAG(
    dag_id="pipeline_latam",
    description="Collecte hebdomadaire des offres data en Amérique latine",
    schedule="@weekly",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["latam", "ingestion"],
) as dag:
 
    def extract():
        print("[EXTRACT] Appels API — Adzuna, Google Places...")
        # TODO : importer et appeler les modules python/
 
    def transform():
        print("[TRANSFORM] Nettoyage et normalisation des données...")
        # TODO
 
    def load():
        print("[LOAD] Insertion dans PostgreSQL...")
        # TODO
 
    t_extract   = PythonOperator(task_id="extract",   python_callable=extract)
    t_transform = PythonOperator(task_id="transform", python_callable=transform)
    t_load      = PythonOperator(task_id="load",      python_callable=load)
 
    t_extract >> t_transform >> t_load
 