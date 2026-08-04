"""
Test de géocodage via Nominatim (self-hosted ou API publique).

Principe :
- Lecture des données d'entreprise depuis le BRONZE (raw.job_offer) uniquement
- JOIN sur le GOLD (serving.job_offer) pour récupérer score_relevancy
- Cascade de géocodage à 4 niveaux, du plus précis au plus grossier :
    1. company + city + country       -> position de l'entreprise
    2. company + location_raw nettoyé -> entreprise via la loc brute JSearch
    3. city + country                 -> centroïde ville
    4. location_raw nettoyé           -> centroïde de ce qu'on peut extraire

Le nettoyage de location_raw retire le suffixe " • a través de <plateforme>"
et les mentions " (y N ubicaciones más)" propres à JSearch.

Usage:
    python test_geocode_nominatim_v2.py --limit 20 --min-score 6
"""

import argparse
import os
import re
import time
from typing import Optional

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
NOMINATIM_URL = os.getenv("NOMINATIM_URL", "http://localhost:8088")

# 1.1s obligatoire sur l'API publique (limite 1 req/s), ~0.1s suffit en self-hosted
SLEEP_BETWEEN_CALLS = float(os.getenv("GEOCODE_SLEEP", "1.1"))

IS_PUBLIC_API = "openstreetmap.org" in NOMINATIM_URL

NOMINATIM_URL="https://nominatim.openstreetmap.org"


# ---------------------------------------------------------------- Nettoyage

# " • a través de Trabajo.org" / " • a través de LinkedIn Uruguay" ...
RE_VIA = re.compile(r"\s*•.*$")
# " (y 1 ubicación más)" / " (y 3 ubicaciones más)"
RE_MORE_LOCATIONS = re.compile(
    r"\s*\(y\s+\d+\s+ubicaci[óo]n(?:es)?\s+m[áa]s\)", re.IGNORECASE
)

# Régions administratives -> ville principale (approximation assumée pour la carte)
REGION_TO_CITY = {
    "región metropolitana": "Santiago",
    "region metropolitana": "Santiago",
}

# Valeurs qui sont des pays, pas des villes
COUNTRY_TOKENS = {"chile", "uruguay", "argentina", "united states", "brasil", "brazil"}


def clean_location_raw(location_raw: Optional[str]) -> Optional[str]:
    """Retire le suffixe plateforme et les mentions de localisations multiples."""
    if not location_raw:
        return None

    cleaned = RE_VIA.sub("", location_raw)
    cleaned = RE_MORE_LOCATIONS.sub("", cleaned)
    cleaned = cleaned.strip(" ,-")

    if not cleaned:
        return None

    # Normalisation région -> ville sur le premier segment
    first_seg = cleaned.split(",")[0].strip()
    mapped = REGION_TO_CITY.get(first_seg.lower())
    if mapped:
        rest = cleaned.split(",")[1:]
        cleaned = ", ".join([mapped] + [s.strip() for s in rest])

    return cleaned


def is_country_only(cleaned: Optional[str]) -> bool:
    """True si la loc nettoyée ne contient qu'un nom de pays (pas de ville exploitable)."""
    if not cleaned:
        return False
    return cleaned.split(",")[0].strip().lower() in COUNTRY_TOKENS


# ---------------------------------------------------------------- SQL

QUERY_TOP_COMPANIES = """
SELECT
    b.company,
    b.city,
    b.country,
    b.location_raw,
    b.api_source,
    COUNT(*)                                  AS nb_offres,
    ROUND(AVG(g.score_relevancy)::numeric, 2) AS score_moyen,
    MAX(g.score_relevancy)                    AS score_max
FROM raw.job_offer b
JOIN serving.job_offer g
    ON g.id_offer = b.id_job
WHERE b.company IS NOT NULL
  AND g.score_relevancy IS NOT NULL
  AND g.score_relevancy >= %(min_score)s
GROUP BY b.company, b.city, b.country, b.location_raw, b.api_source
ORDER BY score_max DESC, score_moyen DESC, nb_offres DESC
LIMIT %(limit)s;
"""


def fetch_top_companies(conn, limit: int, min_score: float) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(QUERY_TOP_COMPANIES, {"limit": limit, "min_score": min_score})
        return [dict(row) for row in cur.fetchall()]


# ---------------------------------------------------------------- Géocodage


def build_query(*parts: Optional[str]) -> Optional[str]:
    kept = [p.strip() for p in parts if p and p.strip()]
    return ", ".join(kept) if kept else None


def geocode(query: str, timeout: int = 10) -> Optional[dict]:
    """Appelle Nominatim. Retourne None si aucun résultat ou erreur."""
    try:
        r = requests.get(
            f"{NOMINATIM_URL}/search",
            params={"q": query, "format": "jsonv2", "limit": 1, "addressdetails": 1},
            headers={"User-Agent": "InternshipLatam/1.0 (geocoding test)"},
            timeout=timeout,
        )
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"      [ERREUR] {query} -> {e}")
        return None

    data = r.json()
    if not data:
        return None

    hit = data[0]
    return {
        "lat": float(hit["lat"]),
        "lon": float(hit["lon"]),
        "display_name": hit.get("display_name"),
        "category": hit.get("category"),
    }


NO_RESULT = {
    "lat": None,
    "lon": None,
    "display_name": None,
    "category": None,
    "match_level": "none",
    "query_used": None,
}


def geocode_cascade(
    company: str,
    city: Optional[str],
    country: Optional[str],
    location_raw: Optional[str],
) -> dict:
    """
    Cascade 4 niveaux. On s'arrête au premier résultat.
    location_raw sert de source de repli quand city/country sont NULL (cas JSearch).
    """
    loc_clean = clean_location_raw(location_raw)
    country_only = is_country_only(loc_clean)

    # Niveau 1 : entreprise + ville structurée
    q = build_query(company, city, country)
    if city:
        res = geocode(q)
        if res:
            return {**res, "match_level": "company", "query_used": q}
        time.sleep(SLEEP_BETWEEN_CALLS)

    # Niveau 2 : entreprise + location_raw nettoyé (utile si city NULL)
    if loc_clean and not country_only:
        q = build_query(company, loc_clean)
        res = geocode(q)
        if res:
            return {**res, "match_level": "company_raw", "query_used": q}
        time.sleep(SLEEP_BETWEEN_CALLS)

    # Niveau 3 : ville structurée seule
    q = build_query(city, country)
    if q:
        res = geocode(q)
        if res:
            return {**res, "match_level": "city", "query_used": q}
        time.sleep(SLEEP_BETWEEN_CALLS)

    # Niveau 4 : location_raw nettoyé seul (ville OU pays)
    if loc_clean:
        q = loc_clean
        res = geocode(q)
        if res:
            level = "country_raw" if country_only else "city_raw"
            return {**res, "match_level": level, "query_used": q}

    return {**NO_RESULT, "query_used": build_query(company, city, country) or company}


# ---------------------------------------------------------------- Main

LEVEL_LABELS = {
    "company": "Entreprise (city structurée)",
    "company_raw": "Entreprise (via location_raw)",
    "city": "Ville (city structurée)",
    "city_raw": "Ville (via location_raw)",
    "country_raw": "Pays seul (via location_raw)",
    "none": "Aucun match",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--min-score", type=float, default=6.0)
    args = parser.parse_args()

    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL manquant dans l'environnement.")

    # Ping adapté : /status n'existe que sur une instance self-hosted
    try:
        if IS_PUBLIC_API:
            requests.get(
                f"{NOMINATIM_URL}/search",
                params={"q": "Santiago", "format": "jsonv2", "limit": 1},
                headers={"User-Agent": "InternshipLatam/1.0 (geocoding test)"},
                timeout=10,
            ).raise_for_status()
            print(f"Nominatim (API publique) : OK — sleep={SLEEP_BETWEEN_CALLS}s\n")
        else:
            ping = requests.get(f"{NOMINATIM_URL}/status", timeout=5)
            print(f"Nominatim (self-hosted) : {NOMINATIM_URL} -> HTTP {ping.status_code}\n")
    except requests.RequestException as e:
        raise SystemExit(f"Nominatim injoignable sur {NOMINATIM_URL} : {e}")

    conn = psycopg2.connect(DATABASE_URL)
    try:
        companies = fetch_top_companies(conn, args.limit, args.min_score)
    finally:
        conn.close()

    if not companies:
        print(f"Aucune entreprise avec score_relevancy >= {args.min_score}")
        return

    print(f"{len(companies)} entreprises récupérées (score >= {args.min_score})\n")
    print("-" * 100)

    stats = {k: 0 for k in LEVEL_LABELS}

    for i, row in enumerate(companies, 1):
        company = row["company"]
        city = row["city"]
        country = row["country"]
        location_raw = row["location_raw"]
        loc_clean = clean_location_raw(location_raw)

        print(f"[{i}/{len(companies)}] {company}  ({row['api_source']})")
        print(f"   city={city} | country={country}")
        if city is None and loc_clean:
            print(f"   location_raw -> nettoyé : '{loc_clean}'")
        print(
            f"   score_max={row['score_max']} | "
            f"score_moyen={row['score_moyen']} | offres={row['nb_offres']}"
        )

        result = geocode_cascade(company, city, country, location_raw)
        stats[result["match_level"]] += 1

        if result["lat"] is not None:
            print(f"   -> {result['lat']:.5f}, {result['lon']:.5f}  [{result['match_level']}]")
            print(f"      {result['display_name']}")
        else:
            print(f"   -> AUCUN RESULTAT (dernière query: {result['query_used']})")

        print("-" * 100)
        time.sleep(SLEEP_BETWEEN_CALLS)

    total = len(companies)
    print("\nRESUME")
    for level, label in LEVEL_LABELS.items():
        n = stats[level]
        if n:
            print(f"  {label:32s} : {n:3d}/{total} ({n/total*100:5.1f}%)")

    geocoded = total - stats["none"]
    print(f"\n  Couverture totale : {geocoded}/{total} ({geocoded/total*100:.1f}%)")
    print("  Coût : 0,00 €")


if __name__ == "__main__":
    main()