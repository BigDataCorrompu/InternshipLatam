# ──────────────────────────────────────────
# DAG: find_mails
# ──────────────────────────────────────────
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException
from datetime import datetime
import json

from database import Database
from LLMprovider import LLM
from datasets import SILVER_OFFERS, SILVER_CONTACTS
from find_mails_graph import build_find_mails_graph, CompanyState


# ___ Configuration via Airflow Variables __________________________________________
# Modifiable outside of a run: Admin > Variables in the Airflow UI.
DEFAULT_CONFIG = {
    "target_countries": ["CL", "AR", "UY"],
    "target_cities": [],
    "min_grade": 5,           # Minimum highest_grade for a company to be processed at all
    "high_relevance_grade": 8,  # Threshold used inside the graph's routing (grounder/hunter access)
    "batch_limit": 10,        # Max companies processed per run, to respect provider quotas
}


def get_config() -> dict:
    """
    Reads each setting from an Airflow Variable if present, falling back to
    DEFAULT_CONFIG otherwise. Stored as JSON strings in the Airflow UI.
    """
    config = dict(DEFAULT_CONFIG)
    for key in DEFAULT_CONFIG:
        try:
            raw = Variable.get(f"find_mails_{key}")
            config[key] = json.loads(raw)
        except KeyError:
            pass  # Variable not set, use default
    return config


@dag(
    dag_id='load_to_bronze',
    start_date=datetime(2026, 6, 7),
    schedule=[SILVER_OFFERS],
    catchup=False,
    max_active_runs=1,
    tags=["analytics", "silver", "load", "contacts"],
    default_args={'owner': 'internship_latam', 'retries': 1},
)
def find_mails_dag():

    @task(task_id="fetch")
    def fetch_target_companies() -> list[dict]:
        """
        Pulls Gold companies matching country/city/grade criteria, with no
        email found yet. Config comes from Airflow Variables, not DAG params.
        """
        config = get_config()
        db = Database(
            db_host           = Variable.get("DB_HOST"),
            db_name           = Variable.get("DB_NAME"),
            db_user           = Variable.get("DB_USER"),
            db_password       = Variable.get("DB_PASSWORD"),
            db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
            db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
        )

        query = """
            SELECT id_company, company_name, website, primary_type,
                   id_location, city, country, highest_grade, average_grades
            FROM serving.company_scores
                WHERE country = ANY(%(countries)s)
                AND (cardinality(%(cities)s) = 0 OR city = ANY(%(cities)s))
                AND highest_grade >= %(min_grade)s
                AND id_company NOT IN (SELECT id_company FROM staging.company_emails)
                ORDER BY highest_grade DESC
                LIMIT %(limit)s
        """
        params = {
            "countries": config["target_countries"],
            "cities": config["target_cities"],
            "min_grade": config["min_grade"],
            "limit": config["batch_limit"],
        }

        companies = db.fetch_all(query, params)

        if not companies:
            raise AirflowSkipException("No target companies found matching current criteria — skipping run")

        print(f"🎯 find_mails: {len(companies)} target companies "
              f"(countries={config['target_countries']}, cities={config['target_cities']}, "
              f"min_grade={config['min_grade']})")
        return companies

    @task(task_id="Search")
    def run_email_search(company: dict) -> dict:
        """
        Runs the LangGraph cascade (grounder → scrapping → hunter) for a single
        company. Dynamically mapped by Airflow over fetch_target_companies().
        """
        config = get_config()
        llm = LLM()
        graph = build_find_mails_graph(
            llm,
            hunter_api_key=None,
            high_relevance_grade=config["high_relevance_grade"],
        )

        initial_state: CompanyState = {
            "id_company": company["id_company"],
            "company_name": company["company_name"],
            "website": company["website"],
            "primary_type": company["primary_type"],
            "id_location": company["id_location"],
            "city": company["city"],
            "country": company["country"],
            "highest_grade": company["highest_grade"],
            "average_grades": company["average_grades"],
            "contacts": [],
        }

        try:
            result = graph.invoke(initial_state)
        except QuotaExceededError as e:
            print(f"⚠️  find_mails: quota exceeded on {company['company_name']}, contacts kept as-is: {e}")
            result = initial_state  # Whatever was accumulated before the quota hit

        return {
            "id_company": company["id_company"],
            "contacts": result.get("contacts", []),
        }

    @task(task_id="trnasfer", outlets=[SILVER_CONTACTS])
    def push_to_db(results: list[dict]) -> None:
        """
        Persists all found emails. One row per email (not just the best),
        to keep full traceability across providers.
        """
        db = Database()
        rows = []
        for r in results:
            for contact in r["contacts"]:
                rows.append((
                    r["id_company"],
                    contact["email"],
                    contact["score"],
                    contact["reason"],
                    contact["source"],
                ))

        if not rows:
            print("⚠️  find_mails: no emails found across the whole batch, nothing to insert")
            return

        db.execute_many(
            """
            INSERT INTO staging.company_emails (id_company, email, score, reason, source, found_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id_company, email) DO NOTHING
            """,
            rows,
        )
        print(f"✅ find_mails: {len(rows)} email(s) inserted across {len(results)} compan(y/ies)")

    companies = fetch_target_companies()
    results = run_email_search.expand(company=companies)
    push_to_db(results)


find_mails_dag()