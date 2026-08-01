FROM apache/airflow:2.9.1
COPY requirements-common.txt /requirements-common.txt
COPY requirements-airflow.txt /requirements.txt
RUN pip install -r /requirements.txt