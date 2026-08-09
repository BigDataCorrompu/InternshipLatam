# ──────────────────────────────────────────
# DAG: find_mails
# ──────────────────────────────────────────
from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException
from datetime import datetime
import json

from database import Database
from APIendpoint import QuotaExceededError  
from LLMprovider import LLM
from datasets import SILVER_OFFERS, FETCH_CONTACTS
from mail_finder import build_find_mails_graph, CompanyState


# ___ Configuration via Airflow Variables __________________________________________
# Modifiable outside of a run: Admin > Variables in the Airflow UI.
DEFAULT_CONFIG = {
    "target_countries": ["CL", "AR", "UY"],
    "target_cities": [],
    "min_grade": 5,           # Minimum highest_grade for a company to be processed at all
    "high_relevance_grade": 8,  # Threshold used inside the graph's routing (grounder/hunter access)
    "batch_limit": 15,        # Max companies processed per run, to respect provider quotas
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
    dag_id='find_mails',
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
            SELECT 
                AVG(jr.score_relevancy) AS average_grades, 
                MAX(jr.score_relevancy) AS highest_grade,
                MAX(COALESCE(job_offer.published_at, job_offer.collected_at)) AS last_offer_date,
                c.id_company, c.company_name, c.website,
                cl.id_location, cl.city, cl.country
            FROM analytics.job_relevancy AS jr 
                INNER JOIN analytics.job_offer AS job_offer ON jr.id_offer = job_offer.id_offer
                INNER JOIN analytics.company AS c ON job_offer.id_company = c.id_company 
                INNER JOIN analytics.company_location AS cl ON c.id_company = cl.id_company
            WHERE cl.country = ANY(%(countries)s::text[])
            AND (cardinality(%(cities)s::text[]) = 0 OR cl.city = ANY(%(cities)s::text[]))
            AND COALESCE(job_offer.published_at, job_offer.collected_at) >= NOW() - INTERVAL '14 days'
            AND c.id_company NOT IN (
                SELECT se.id_company
                FROM staging.company_emails se,
                    LATERAL jsonb_array_elements(se.raw_result) AS contact
                GROUP BY se.id_company
                HAVING COUNT(DISTINCT se.collected_at) >= 2
                    OR MAX((contact->>'score')::NUMERIC(3,2)) >= 0.8
            )
            GROUP BY c.id_company, c.company_name, c.website,
                    cl.id_location, cl.city, cl.country
            HAVING MAX(jr.score_relevancy) >= %(min_grade)s
            ORDER BY last_offer_date DESC, highest_grade DESC
            LIMIT %(limit)s
        """
        
        params = {
            "countries": config["target_countries"],
            "cities": config["target_cities"],
            "min_grade": config["min_grade"],
            "limit": config["batch_limit"],
        }

        companies = db.execute(query, params)

        if not companies:
            raise AirflowSkipException("No target companies found matching current criteria — skipping run")

        print(f"🎯 find_mails: {len(companies)} target companies "
              f"(countries={config['target_countries']}, cities={config['target_cities']}, "
              f"min_grade={config['min_grade']})")
        return companies

    @task(task_id="Search", multiple_outputs=False)
    def run_email_search(company: dict) -> list:
        """
        Runs the LangGraph cascade (grounder → scrapping → hunter) for a single
        company. Dynamically mapped by Airflow over fetch_target_companies().
        """
        config = get_config()
        llm = LLM()
        graph = build_find_mails_graph(
            llm,
            hunter_api_key=Variable.get("HUNTER_APP_KEY"),
            high_relevance_grade=config["high_relevance_grade"],
        )

        initial_state: CompanyState = {
            "id_company": company["id_company"],
            "company_name": company["company_name"],
            "website": company["website"],
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

        return [company["id_company"], company["id_location"], result.get("contacts", [])]

    @task(task_id="transfer", outlets=[FETCH_CONTACTS])
    def push_to_db(results: list[list]) -> None:
        """
        Persists found emails as JSONB, one row per company.
        results: 2D array [n][3] — each row is [id_company, id_location, contacts].
        """
        db = Database()
        rows = [
            (row[0], row[1], json.dumps(row[2]))
            for row in results
        ]
        
        if not rows:
            print("⚠️  find_mails: no emails found across the whole batch, nothing to insert")
            return

        db.bulk_insert("staging.company_emails", ["id_company", "id_location", "raw_result"], rows)

        found_count = sum(1 for row in results if row[2])
        print(f"✅ find_mails: {len(rows)} attempt(s) recorded, {found_count} with email(s) found")

    companies = fetch_target_companies()
    results = run_email_search.expand(company=companies)
    push_to_db(results)


find_mails_dag()