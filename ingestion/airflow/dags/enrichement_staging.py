from airflow.decorators import dag, task
from airflow.models import Variable
from airflow.exceptions import AirflowSkipException
import traceback
from datasets import BRONZE_OFFERS, STAGING_ENRICHED
from database import Database


from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)

SAVE_EVERY = 10        # flush vers staging tous les N enrichissements
MAX_PER_RUN = 3     # None = all ; un int pour lisser le rattrapage
 
# Configurable via Airflow Variable "find_location_min_score" (défaut : 8)
DEFAULT_MIN_SCORE_LOCATION = 6


SELECT_PENDING = """
    SELECT b.*
    FROM raw.job_offer b
    LEFT JOIN staging.enriched_offers s ON s.id_offer = b.id_job
    WHERE s.id_offer IS NULL
    ORDER BY collected_at DESC;
"""

SELECT_PROFILE = """
    SELECT id_prompt, prompt
    FROM analytics.prompt_relevancy
    ORDER BY created_at DESC
    LIMIT 1;
"""



def normalize_name(name: str) -> str:
    return (name or "").strip().lower()

def get_db() -> Database:
    return Database(
        db_host           = Variable.get("DB_HOST"),
        db_name           = Variable.get("DB_NAME"),
        db_user           = Variable.get("DB_USER"),
        db_password       = Variable.get("DB_PASSWORD"),
        db_sslmode        = Variable.get("DB_SSLMODE",       default_var="require"),
        db_channelbinding = Variable.get("DB_CHANNELBIDING", default_var="disable"),
    )



@dag(
    dag_id='silver_enrichment',
    start_date=datetime(2026, 6, 7),
    schedule=[BRONZE_OFFERS],
    catchup=False,
    max_active_runs=1,
    tags=["silver", "enrichment", "llm"],
    default_args={'owner': 'internship_latam'},
)
def silver_enrichment():
 
    @task(task_id="enrich", outlets=[STAGING_ENRICHED])
    def enrich():
        from graph_silver_enrichment import graph
        from silver_enrichment import map_bronze_to_JobOfferState, map_prompt_to_JobOfferState
        from LLMprovider import LLM
        from APIendpoint import PlacesAPIId, PlacesAPIDetails
        from utils import clean_location_raw
 
        llm = LLM()
        llm_model_name = llm.enrichement.model
 
        db = get_db()
        places_id = PlacesAPIId()
        places_details = PlacesAPIDetails()
 
        id_tracking: dict[str, dict] = {}  # place_id -> details, cache global au run
 
        # 1 - Profil utilisateur
        prompt_rows = db.execute(SELECT_PROFILE)
        if not prompt_rows:
            raise ValueError("Aucun profil dans analytics.prompt_relevancy")
        profile_state = map_prompt_to_JobOfferState(prompt_rows[0])
 
        # 2 - Offres non enrichies
        pending = db.execute(SELECT_PENDING)
        if MAX_PER_RUN:
            pending = pending[:MAX_PER_RUN]
        if not pending:
            raise AirflowSkipException("[ENRICH] status=nothing_to_enrich")
 
        logger.info(f"[ENRICH] pending={len(pending)}")
 
        min_score_location = float(
            Variable.get("find_location_min_score", default_var=DEFAULT_MIN_SCORE_LOCATION)
        )
 
        # ---------------------------------------------------------- helpers
        def build_city_index() -> dict:
            """
            {(city_lower, country_code): (lat, lon)} construit une seule fois par run.
            geonamescache embarque ~25 000 villes hors-ligne, aucun appel réseau.
            """
            import geonamescache
            gc = geonamescache.GeonamesCache()
            index = {}
            for _, c in gc.get_cities().items():
                key = (c["name"].strip().lower(), c["countrycode"])
                # Garde la ville la plus peuplée en cas d'homonymes dans le même pays
                existing = index.get(key)
                if existing is None or c["population"] > existing[2]:
                    index[key] = (c["latitude"], c["longitude"], c["population"])
            return {k: (v[0], v[1]) for k, v in index.items()}


        city_index = build_city_index()
        logger.info(f"[ENRICH] city_index={len(city_index)} villes chargées")
 
        def lookup_existing_locations(company_names: list[str]) -> dict:
            """Une seule requête pour tout le batch en cours : nom canonique + raw_names."""
            if not company_names:
                return {}
            rows = db.execute(
                """
                SELECT c.id_company, c.company_name, c.raw_names,
                       cl.id_location, cl.city, cl.country, cl.source
                FROM analytics.company c
                LEFT JOIN analytics.company_location cl ON cl.id_company = c.id_company
                WHERE c.company_name = ANY(%(names)s)
                   OR raw_names && %(names)s
                """,
                {"names": company_names},
            )
            index = {}
            for row in rows:
                entry = {
                    "id_company":  row["id_company"],
                    "id_location": row["id_location"],
                    "city":        row["city"],
                    "country":     row["country"],
                    "source":      row["source"],
                }
                index[normalize_name(row["company_name"])] = entry
                for rn in (row.get("raw_names") or []):
                    index[normalize_name(rn)] = entry
            return index
                
        def forward_geocode(location_raw: str, city: str, country: str, api_source: str = None) -> dict | None:
            """
            Résolution niveau ville, gratuite et hors-ligne via geonamescache.
            Si city est NULL (fréquent chez JSearch), tente de l'extraire
            depuis location_raw nettoyé avant de renoncer.
            """
            candidates = []

            if city:
                candidates.append(city)

            # Repli : premier segment de location_raw nettoyé
            loc_clean = clean_location_raw(location_raw, api_source)
            if loc_clean:
                candidates.append(loc_clean.split(",")[0])

            for candidate in candidates:
                key = (candidate.strip().lower(), country)
                coords = city_index.get(key)
                if coords:
                    return {
                        "lat": coords[0], "lon": coords[1],
                        "city": candidate.strip(), "country": country,
                        "geo_source": "geonames",
                    }

            return None

        def resolve_location(entry: dict, existing_index: dict) -> dict:
            """
            1. Deja en base, source == 'find_place'      -> reutilisation directe.
            2. Sinon, si score > min_score_location :
                    - search_id
                    - id deja dans id_tracking (ce run)      -> reutilisation
                    - sinon search_details
                        - rien trouve                        -> forward_geocode
                        - trouve                              -> mis en cache + retourne
            3. Score <= min_score_location, ou rien trouve cote Find Place
                                                            -> forward_geocode.
            """
            company_name = entry.get("company_name")
            city = entry.get("city")
            country = entry.get("country")
            location_raw = entry.get("location_raw")
            api_source = entry.get("api_source")
            score = entry.get("score_relevancy")

            key = normalize_name(company_name)
            existing = existing_index.get(key)

            if existing and existing["source"] == "find_place":
                return {
                    "id_company": existing["id_company"],
                    "id_location": existing["id_location"],
                    "geo_source": "existing",
                }

            if score is not None and score > min_score_location:
                place_id = places_id.search_id(
                    company=company_name,
                    location=f"{city}, {country}" if city else country,
                )

                if place_id:
                    if place_id in id_tracking:
                        place_data = id_tracking[place_id]
                    else:
                        place_data = places_details.search_details(place_id)
                        if place_data:
                            id_tracking[place_id] = place_data

                    if place_data:
                        return {**place_data, "place_id": place_id, "geo_source": "find_place"}

                # pas d'id, ou details vide -> repli
                return forward_geocode(location_raw, city, country, api_source) or {"geo_source": "skipped"}

            # score insuffisant -> repli direct, pas d'appel Find Place
            return forward_geocode(location_raw, city, country, api_source) or {"geo_source": "skipped"}

        # ---------------------------------------------------------- boucle principale

        buffer_ids, results_batch = [], []
        ok, ko = 0, 0

        def flush():
            nonlocal buffer_ids, results_batch
            if not buffer_ids:
                return

            company_names = [r["company_name"] for r in results_batch if r.get("company_name")]
            existing_index = lookup_existing_locations(company_names)

            for entry in results_batch:
                entry["result"]["geo"] = resolve_location(entry, existing_index)

            db.bulk_insert(
                table="staging.enriched_offers",
                columns=["id_offer", "raw_result", "llm_model"],
                data=[
                    (e["id_job"], json.dumps(e["result"], default=str), llm_model_name)
                    for e in results_batch
                ],
            )
            buffer_ids, results_batch = [], []

        for i, row in enumerate(pending, 1):
            id_job = row["id_job"]
            try:
                state = map_bronze_to_JobOfferState(row) | profile_state
                result = graph.invoke(state)

                results_batch.append({
                    "id_job": id_job,
                    "result": result,
                    "company_name": result.get("company"),
                    "city": result.get("city"),
                    "country": result.get("country"),
                    "location_raw": row.get("location_raw"),
                    "api_source": row.get("api_source"),
                    "score_relevancy": result.get("score_relevancy"),
                })
                buffer_ids.append(id_job)
                ok += 1
                logger.info(f"[ENRICH] {i}/{len(pending)} id={id_job} score={result.get('score_relevancy')}")

            except Exception as e:
                ko += 1
                logger.warning(f"[ENRICH] {i}/{len(pending)} id={id_job} status=failed err={e}")
                logger.warning(traceback.format_exc())

            if len(buffer_ids) >= SAVE_EVERY:
                flush()

        flush()
        logger.info(
            f"[ENRICH] done ok={ok} failed={ko} total={len(pending)} "
            f"find_place_calls={len(id_tracking)}"
        )

    enrich()
 
 
silver_enrichment()