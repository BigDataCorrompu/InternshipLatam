from airflow.decorators import dag, task
from airflow.models import Variable
from datetime import datetime

from staging_to_silver import transfer_staging_to_silver
from database import Database

