FROM apache/airflow:2.9.1
COPY requirements.txt /
RUN pip install -r /requirements.txt \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.9.1/constraints-3.12.txt"