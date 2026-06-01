#!/usr/bin/env python3
"""
test_api.py — Banc de test pour APIendpoint.py (InternshipLatam)

Ce que fait le script :
  - Teste TOUS les endpoints de JsearchAPI et CareerJetAPI avec les paramètres
    réels documentés (cible : offres data / internship à Buenos Aires).
  - Jsearch : AUCUN filtre de champ (pas de paramètre `fields`) -> format BRUT complet.
  - Teste la PAGINATION des deux APIs (Jsearch = cursor, CareerJet = page).
  - Sauvegarde chaque réponse brute en JSON dans un dossier de run incrémenté :
        results/001/  puis  results/002/  à chaque exécution.
  - Génère par run : un fichier par test + _summary.json + _formats.json.

Usage :
    python test_api.py                 # appels réels (nécessite les clés API)
    python test_api.py --mock          # données simulées, AUCUN appel réseau
    python test_api.py --max-pages 5   # plafond de pages pour la pagination
"""

import os
import sys
import json
import argparse
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from APIendpoint import JsearchAPI, CareerJetAPI

BASE_RESULTS = Path(__file__).resolve().parent / "results"
RUN_DIR = None          # défini dans main() -> results/001, 002, ...
RESULTS = []            # accumulateur pour le résumé


# ════════════════════════════════════════════════════════════
#  PARAMÈTRES DES SCÉNARIOS  (cible : Buenos Aires, internship)
#  -> modifiables ici facilement
# ════════════════════════════════════════════════════════════
# Jsearch /search-v2 — PAS de "fields" : on veut le brut complet
JSEARCH_SEARCH = {
    "query":            "data engineer intern Buenos Aires Argentina",
    "country":          "ar",
    "num_pages":        "1",
    "date_posted":      "month",
    "employment_types": "INTERN,FULLTIME",   # INTERN seul possible mais souvent peu de résultats
    "language":         "es",
}
# Jsearch /job-details — kwargs (job_id récupéré dynamiquement de la recherche)
JSEARCH_DETAILS_KW = {"country": "ar", "language": "es"}
# Jsearch /estimated-salary
JSEARCH_SALARY = {
    "location":            "Buenos Aires, Argentina",
    "job_title":           "data engineer",
    "location_type":       "CITY",
    "years_of_experience": "LESS_THAN_ONE",
}
# Jsearch /company-job-salary
JSEARCH_COMPANY_SALARY = {
    "company":             "Globant",
    "job_title":           "data engineer",
    "location":            "Buenos Aires, Argentina",
    "location_type":       "CITY",
    "years_of_experience": "LESS_THAN_ONE",
}
# CareerJet /v4/query — internship (contract_type="i") à Buenos Aires
CAREERJET_SEARCH = {
    "keywords":      "data engineer",
    "location":      "Buenos Aires",
    "locale_code":   "es_AR",
    "contract_type": "i",      # i = stage / internship
    "work_hours":    "f",      # f = temps plein
    "sort":          "date",
    "page_size":     50,
}


# ──────────────────────────────────────────
#  Utilitaires
# ──────────────────────────────────────────
def describe_structure(obj, max_depth=5, _depth=0):
    """Squelette du format : clés + types, sans les valeurs."""
    if _depth >= max_depth:
        return f"<{type(obj).__name__}>"
    if isinstance(obj, dict):
        return {k: describe_structure(v, max_depth, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, list):
        if not obj:
            return ["<liste vide>"]
        return {"_type": "list", "_length": len(obj),
                "_item": describe_structure(obj[0], max_depth, _depth + 1)}
    if obj is None:
        return "null"
    return type(obj).__name__


def count_results(raw):
    """Compte les jobs dans une réponse, quelle que soit l'API."""
    if isinstance(raw, list):
        return len(raw)
    if isinstance(raw, dict):
        data = raw.get("data")
        if isinstance(data, dict) and "jobs" in data:
            return len(data.get("jobs") or [])
        if isinstance(data, list):
            return len(data)
        if "jobs" in raw:
            return len(raw.get("jobs") or [])
    return None


def save_json(filename, data):
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    path = RUN_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    return path


def next_run_dir(base):
    """Retourne results/NNN avec NNN incrémenté (001, 002, ...)."""
    base.mkdir(parents=True, exist_ok=True)
    nums = [int(p.name) for p in base.iterdir() if p.is_dir() and p.name.isdigit()]
    n = max(nums, default=0) + 1
    run = base / f"{n:03d}"
    run.mkdir()
    return run


# ──────────────────────────────────────────
#  Lanceurs de test
# ──────────────────────────────────────────
def run_endpoint_test(name, func, *args, **kwargs):
    """Appelle un endpoint, capture la réponse BRUTE, l'analyse, la sauvegarde."""
    print(f"\n▶ {name}")
    record = {
        "test": name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "callable": getattr(func, "__name__", str(func)),
        "args": list(args),
        "params": kwargs,
        "status": "OK",
        "error": None,
        "result_count": None,
        "format": None,
        "raw": None,
    }
    try:
        raw = func(*args, **kwargs)
        record["raw"] = raw
        record["format"] = describe_structure(raw)
        record["result_count"] = count_results(raw)
        n = record["result_count"]
        print("   ✓ OK" + (f" — {n} résultat(s)" if n is not None else ""))
    except Exception as e:
        record["status"] = "ERREUR"
        record["error"] = str(e)
        record["traceback"] = traceback.format_exc()
        print(f"   ✗ ERREUR : {e}")

    save_json(f"{name}.json", record)
    RESULTS.append({k: v for k, v in record.items() if k not in ("raw", "traceback")})
    return record


def _page_info(api, raw, page_counter):
    items = api._extract_results(raw)
    has_next = api._has_next_page(raw, page_counter)
    return {
        "page_counter": page_counter,
        "results_on_page": len(items),
        "has_next_page": bool(has_next),
        "next_token": api._next_page(raw, page_counter) if has_next else None,
        "format": describe_structure(raw),
    }


def test_pagination(name, api, search_func, max_pages=3, **kwargs):
    """
    Teste la pagination en envoyant le jeton sous le BON paramètre, lu
    directement sur la classe (api.PAGE_PARAM) -> toujours synchro avec
    APIendpoint.py (Jsearch -> 'cursor', CareerJet -> 'page').
    Plafonné à max_pages pour ménager le quota.
    """
    page_param = api.PAGE_PARAM
    print(f"\n▶ {name} (pagination — param='{page_param}', max {max_pages} page(s))")
    record = {
        "test": name,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "page_param": page_param,
        "status": "OK",
        "error": None,
        "max_pages": max_pages,
        "pages": [],
        "total_results": 0,
        "stopped_because": None,
    }
    try:
        page_counter = 1
        raw = search_func(**kwargs)                     # page 1 : sans paramètre de pagination
        all_results = list(api._extract_results(raw))
        info = _page_info(api, raw, page_counter)
        record["pages"].append(info)
        print(f"   • page 1: {info['results_on_page']} résultat(s), suivante={info['has_next_page']}")

        pages_done = 1
        while api._has_next_page(raw, page_counter) and pages_done < max_pages:
            token = api._next_page(raw, page_counter)
            raw = search_func(**{page_param: token}, **kwargs)
            all_results.extend(api._extract_results(raw))
            page_counter = token if isinstance(token, int) else page_counter + 1
            pages_done += 1
            info = _page_info(api, raw, page_counter)
            record["pages"].append(info)
            tok_disp = token if isinstance(token, int) else f"{str(token)[:12]}…"
            print(f"   • page {pages_done} (token={tok_disp}): {info['results_on_page']} résultat(s), suivante={info['has_next_page']}")

        record["total_results"] = len(all_results)
        record["stopped_because"] = ("plafond max_pages atteint"
                                     if api._has_next_page(raw, page_counter)
                                     else "plus de page suivante")
        print(f"   ✓ {record['total_results']} résultat(s) cumulé(s) sur {len(record['pages'])} page(s) ({record['stopped_because']})")
    except Exception as e:
        record["status"] = "ERREUR"
        record["error"] = str(e)
        record["traceback"] = traceback.format_exc()
        print(f"   ✗ ERREUR : {e}")

    save_json(f"{name}.json", record)
    RESULTS.append({k: v for k, v in record.items() if k != "traceback"})
    return record


# ──────────────────────────────────────────
#  Mode simulé (--mock) : aucune connexion réseau
# ──────────────────────────────────────────
def make_mock_call(kind):
    state = {"page": 0}

    def fake_call(endpoint, params):
        if kind == "jsearch":
            if endpoint == "search":
                state["page"] += 1
                last = state["page"] >= 2
                return {
                    "status": "OK",
                    "request_id": "mock-123",
                    "parameters": params,
                    "data": {
                        "jobs": [{
                            "job_id": f"mock_{state['page']}_{i}",
                            "job_title": "Data Engineer Intern",
                            "employer_name": "Globant",
                            "employer_website": "https://globant.com",
                            "job_publisher": "LinkedIn",
                            "job_employment_type": "INTERN",
                            "job_apply_link": "https://example.com/apply",
                            "job_city": "Buenos Aires",
                            "job_country": "AR",
                            "job_posted_at_datetime_utc": "2026-05-15T00:00:00.000Z",
                            "job_min_salary": None,
                            "job_max_salary": None,
                            "job_salary_currency": None,
                            "job_description": "Pasantía en ingeniería de datos...",
                        } for i in range(3)],
                        "cursor": None if last else f"CuRsOr_{state['page']}",
                    },
                }
            if endpoint == "details":
                return {"status": "OK", "data": [{
                    "job_id": params.get("job_id"), "job_title": "Data Engineer Intern",
                    "employer_name": "Globant", "job_country": params.get("country")}]}
            if endpoint == "salary":
                return {"status": "OK", "data": [{
                    "location": params.get("location"), "job_title": params.get("job_title"),
                    "min_salary": 12000, "max_salary": 24000, "median_salary": 18000,
                    "salary_currency": "USD", "salary_period": "YEAR", "confidence": "HIGH"}]}
            if endpoint == "company_salary":
                return {"status": "OK", "data": [{
                    "company": params.get("company"), "job_title": params.get("job_title"),
                    "median_salary": 20000, "salary_currency": "USD"}]}
        if kind == "careerjet":
            state["page"] += 1
            return {
                "type": "JOBS", "hits": 6, "message": "6 matching jobs found",
                "pages": 2, "response_time": 0.21,
                "jobs": [{
                    "title": "Pasante Data Engineer", "company": "NTT DATA",
                    "date": "2026-05-30", "description": "Pasantía...",
                    "locations": "Buenos Aires", "salary": "",
                    "salary_currency_code": "ARS", "salary_min": None, "salary_max": None,
                    "salary_type": "M", "site": "linkedin.com",
                    "url": "https://example.com/job"} for _ in range(3)],
            }
        return {}
    return fake_call


# ──────────────────────────────────────────
#  Résumé
# ──────────────────────────────────────────
def print_summary():
    print("\n" + "=" * 60 + "\n  RÉSUMÉ\n" + "=" * 60)
    ok = sum(1 for r in RESULTS if r["status"] == "OK")
    ko = len(RESULTS) - ok
    for r in RESULTS:
        icon = "✓" if r["status"] == "OK" else "✗"
        if r.get("result_count") is not None:
            extra = f"  ({r['result_count']} résultats)"
        elif "total_results" in r:
            extra = f"  ({r['total_results']} résultats / {len(r.get('pages', []))} pages)"
        else:
            extra = ""
        line = f"  {icon} {r['test']:<26}{extra}"
        if r["status"] != "OK":
            line += f"   → {r['error'].splitlines()[0]}"
        print(line)
    print("-" * 60)
    print(f"  {ok} réussi(s), {ko} échec(s)  —  fichiers dans  {RUN_DIR}/")
    print("=" * 60)


# ──────────────────────────────────────────
#  Programme principal
# ──────────────────────────────────────────
def main():
    global RUN_DIR
    parser = argparse.ArgumentParser(description="Banc de test pour APIendpoint.py")
    parser.add_argument("--api", choices=["all", "jsearch", "careerjet"], default="all",
                        help="Quelle(s) API tester (défaut: all)")
    parser.add_argument("--mock", action="store_true", help="Données simulées, aucun appel réseau")
    parser.add_argument("--max-pages", type=int, default=3, help="Plafond de pages pour la pagination")
    args = parser.parse_args()

    do_jsearch = args.api in ("all", "jsearch")
    do_careerjet = args.api in ("all", "careerjet")

    RUN_DIR = next_run_dir(BASE_RESULTS)
    print("=" * 60)
    print(f"  BANC DE TEST — {'MODE SIMULÉ (--mock)' if args.mock else 'APPELS RÉELS'}")
    print(f"  API testée(s) : {args.api}")
    print(f"  Run → {RUN_DIR}/")
    print("=" * 60)

    required = {}
    if do_jsearch:
        required["JSEARCH_APP_KEY"] = "Jsearch"
    if do_careerjet:
        required.update({"CAREERJET_APP_KEY": "CareerJet",
                         "SERVER_IP": "CareerJet (user_ip)",
                         "CAREERJET_REFERER": "CareerJet (header Referer / site déclaré)"})
    missing = [k for k in required if not os.getenv(k)]
    if missing and not args.mock:
        print("\n⚠  Variables d'environnement manquantes :")
        for k in missing:
            print(f"   - {k}  ({required[k]})")
        print("   → Les tests concernés échoueront. Lance avec --mock pour tester sans clé.")

    # ════════ JSEARCH ════════
    if do_jsearch:
        print("\n" + "─" * 60 + "\n  JSEARCH API  (champs NON filtrés — format brut)\n" + "─" * 60)
        jsearch = JsearchAPI()
        if args.mock:
            jsearch._call = make_mock_call("jsearch")

        rec = run_endpoint_test("jsearch_search", jsearch.search_jobs,
                                JSEARCH_SEARCH["query"],
                                **{k: v for k, v in JSEARCH_SEARCH.items() if k != "query"})

        # Récupère un job_id réel pour /job-details
        job_id = None
        raw = rec.get("raw")
        if isinstance(raw, dict):
            data = raw.get("data")
            jobs = data.get("jobs") if isinstance(data, dict) else (data if isinstance(data, list) else [])
            if jobs:
                job_id = jobs[0].get("job_id")

        if job_id:
            run_endpoint_test("jsearch_details", jsearch.get_details, job_id, **JSEARCH_DETAILS_KW)
        else:
            print("\n▶ jsearch_details — ignoré (aucun job_id récupéré de la recherche)")

        run_endpoint_test("jsearch_salary", jsearch.get_salary,
                          JSEARCH_SALARY["location"], JSEARCH_SALARY["job_title"],
                          **{k: v for k, v in JSEARCH_SALARY.items() if k not in ("location", "job_title")})

        run_endpoint_test("jsearch_company_salary", jsearch.get_company_salary,
                          JSEARCH_COMPANY_SALARY["company"], JSEARCH_COMPANY_SALARY["job_title"],
                          **{k: v for k, v in JSEARCH_COMPANY_SALARY.items() if k not in ("company", "job_title")})

        test_pagination("jsearch_pagination", jsearch, jsearch.search_jobs,
                        max_pages=args.max_pages, **JSEARCH_SEARCH)

    # ════════ CAREERJET ════════
    if do_careerjet:
        print("\n" + "─" * 60 + "\n  CAREERJET API\n" + "─" * 60)
        careerjet = CareerJetAPI()
        if args.mock:
            careerjet._call = make_mock_call("careerjet")

        run_endpoint_test("careerjet_search", careerjet.search_jobs, **CAREERJET_SEARCH)
        test_pagination("careerjet_pagination", careerjet, careerjet.search_jobs,
                        max_pages=args.max_pages, **CAREERJET_SEARCH)

    # ════════ SYNTHÈSE ════════
    save_json("_summary.json", {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run": RUN_DIR.name,
        "mode": "mock" if args.mock else "real",
        "tests": RESULTS,
    })
    formats = {}
    for r in RESULTS:
        if r.get("format") is not None:
            formats[r["test"]] = r["format"]
        elif r.get("pages"):
            formats[r["test"]] = r["pages"][0]["format"]
    save_json("_formats.json", formats)

    print_summary()


if __name__ == "__main__":
    main()