import sys
sys.path.append("./src")

import json
from database import Database
from utils import normalise_list_language
print_list = list()
def safe_bulk_insert(db, table, columns, data, **kwargs):
    """Wrapper qui vérifie la cohérence colonnes/données avant d'appeler bulk_insert."""
    if data:
        n_cols = len(columns)
        n_vals = len(data[0])
        if n_cols != n_vals:
            raise ValueError(
                f"MISMATCH pour {table}: {n_cols} colonnes déclarées "
                f"({columns}) mais {n_vals} valeurs dans le premier tuple ({data[0]})"
            )
    return db.bulk_insert(table=table, columns=columns, data=data, **kwargs)

def parse_staging_rows(rows: list[dict]) -> list[dict]:
    """Parse les raw_result JSONB et filtre les lignes sans company_name valide."""
    INVALID_COMPANY_VALUES = {None, "null", "", "Empresa confidencial"}
    parsed = []
    for row in rows:
        r = row["raw_result"] if isinstance(row["raw_result"], dict) else json.loads(row["raw_result"])
        if r.get("company_name") not in INVALID_COMPANY_VALUES:
            parsed.append(r)
    return parsed


def dedupe_companies(parsed: list[dict]) -> list[tuple]:
    """Une seule ligne par company_name."""
    unique = {}
    for r in parsed:
        name = r["company_name"]
        if name not in unique:
            unique[name] = (name, r.get("company_website"), r.get("company_primary_type"))
    return list(unique.values())


def dedupe_locations(parsed: list[dict], company_id_map: dict) -> list[tuple]:
    unique = {}
    for r in parsed:
        id_company = company_id_map.get(r["company_name"])
        city = r.get("city")
        country = r.get("country")
        if id_company and city:
            key = (id_company, city, country)  # ajoute country dans la clé de dédup
            if key not in unique:
                unique[key] = (
                    id_company, r.get("address"), city, country,
                    r.get("lat"), r.get("lon"), r.get("phone"), r.get("business_status")
                )
    return list(unique.values())


def dedupe_contacts(parsed: list[dict], company_id_map: dict, location_id_map: dict) -> list[tuple]:
    """Une seule ligne par email."""
    unique = {}
    for r in parsed:
        id_company = company_id_map.get(r["company_name"])
        id_location = location_id_map.get((id_company, r.get("city")))
        for contact in r.get("contacts", []):
            email = contact.get("email")
            if email and email not in unique:
                unique[email] = (id_company, id_location, email, contact.get("score"), contact.get("reason"), "ddg_llm")
    return list(unique.values())


def truncate(value, max_length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:max_length]


def build_offer_rows(parsed: list[dict], company_id_map: dict, location_id_map: dict) -> list[tuple]:
    rows = []
    for r in parsed:
        id_company = company_id_map.get(r["company_name"])
        id_location = location_id_map.get((id_company, r.get("city"), r.get("country")))
        rows.append((
            r["id_job"], id_company, id_location,
            truncate(r.get("api_source"), 15),
            truncate(r.get("job_title"), 150),
            r.get("offer_description"),  # TEXT, pas de limite
            truncate(r.get("contract_type"), 20),
            r.get("is_remote"),
            truncate(r.get("job_publisher"), 100),
            truncate(r.get("location_raw"), 100),
            truncate(r.get("offer_url"), 500),
            truncate(r.get("source_platform"), 100),
            r.get("published_at"),
            r.get("collected_at")
        ))
        
    return rows

def build_requirement_rows(parsed: list[dict]) -> list[tuple]:
    # Debug ______________________________
    for r in parsed:
        print_list.append((r.get("offer_language"),normalise_list_language(r.get("offer_language"))))
    # _____________________________________
    return [
        (r["id_job"], r.get("seniority"), normalise_list_language(r.get("offer_language")), r.get("skills_languages"), r.get("skills_framework"),
         r.get("skills_aptitudes"), r.get("skills_soft"), r.get("alternative_job_titles"), "v1")
        for r in parsed
    ]


def build_relevancy_rows(parsed: list[dict]) -> list[tuple]:
    rows = []
    for r in parsed:
        scores = r.get("score_details", {})
        rows.append((
            r["id_job"], r.get("score_relevancy"), scores.get("score_job"), scores.get("score_skills"),
            scores.get("score_location"), scores.get("score_language"), scores.get("score_seniority"),
            scores.get("score_work_mode"), scores.get("score_company"), r.get("explanation")
        ))
    return rows


def transfer_staging_to_silver(db: Database):
    rows = db.execute("SELECT id_offer, raw_result FROM staging.enriched_offers")
    print(f"📋 {len(rows)} lignes en staging")

    parsed = parse_staging_rows(rows)
    print(f"📋 {len(parsed)} lignes valides (company_name présent)")

    # 1. Company
    company_values = dedupe_companies(parsed)
    company_results = safe_bulk_insert(
        db,
        table="analytics.company",
        columns=["company_name", "website", "primary_type"],
        data=company_values,
        onConflict="update",
        conflict_columns=["company_name"],
        returning=["id_company", "company_name"]
    )
    company_id_map = {row["company_name"]: row["id_company"] for row in company_results}
    print(f"✅ {len(company_id_map)} companies upsertées")

    # 2. Company location
    location_values = dedupe_locations(parsed, company_id_map)
    location_id_map = {}
    if location_values:
        location_results = safe_bulk_insert(
        db,
            table="analytics.company_location",
            columns=["id_company", "address", "city", "country", "lat", "lon", "phone", "business_status"],
            data=location_values,
            onConflict="update",
            conflict_columns=["id_company", "city", "country"],  # ajoute "country" ici
            returning=["id_location", "id_company", "city", "country"]
        )
        location_id_map = {(row["id_company"], row["city"], row["country"]): row["id_location"] for row in location_results}
    print(f"✅ {len(location_id_map)} locations upsertées")

    # 3. Job offer
    offer_values = build_offer_rows(parsed, company_id_map, location_id_map)
    safe_bulk_insert(
        db,
        table="analytics.job_offer",
        columns=["id_offer", "id_company", "id_location", "api_source", "job_title", "offer_description",
                 "contract_type", "is_remote", "job_publisher", "location_raw", "offer_url",
                 "source_platform", "published_at", "collected_at"],
        data=offer_values,
        onConflict="update",
        conflict_columns=["id_offer"]
    )
    print(f"✅ {len(offer_values)} job_offer insérées")

    # 4. Job requirement
    requirement_values = build_requirement_rows(parsed)
    safe_bulk_insert(
        db,
        table="analytics.job_requirement",
        columns=["id_offer", "seniority", "offer_languages", "skills_languages", "skills_frameworks",
                 "skills_aptitudes", "skills_soft", "alternative_job_titles", "prompt_version"],
        data=requirement_values,
        onConflict="update",
        conflict_columns=["id_offer"]
    )
    print(f"✅ {len(requirement_values)} job_requirement insérées")

    # 5. Job relevancy
    relevancy_values = build_relevancy_rows(parsed)
    safe_bulk_insert(
        db,
        table="analytics.job_relevancy",
        columns=["id_offer", "score_relevancy", "score_job", "score_skills", "score_location",
                 "score_language", "score_seniority", "score_work_mode", "score_company", "explanation"],
        data=relevancy_values,
        onConflict="update",
        conflict_columns=["id_offer"]
    )
    print(f"✅ {len(relevancy_values)} job_relevancy insérées")

    # 6. Company contact
    contact_values = dedupe_contacts(parsed, company_id_map, location_id_map)
    if contact_values:
        safe_bulk_insert(
        db,
            table="analytics.company_contact",
            columns=["id_company", "id_location", "email", "confidence", "explanation", "source"],
            data=contact_values,
            onConflict="update",
            conflict_columns=["email"]
        )
    print(f"✅ {len(contact_values)} contacts insérés")

    print(f"\n🏁 Transfert Staging → Silver terminé")
    print(print_list)


if __name__ == "__main__":
    db = Database()
    transfer_staging_to_silver(db)
