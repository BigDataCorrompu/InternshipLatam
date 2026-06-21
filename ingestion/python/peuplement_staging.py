import sys


import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# 1. Calcule le chemin absolu du dossier où se trouve CE script (peuplement_staging.py)
script_dir = Path(__file__).resolve().parent

# 2. Tente de charger le .env s'il est dans le même dossier
env_path = script_dir / ".env"

# NOTE : Si ton fichier .env est un ou deux dossiers plus haut dans ton repo Perforce,
# décommente la ligne appropriée ci-dessous :
# env_path = script_dir.parent / ".env"         # Si le .env est dans 'ingestion/'
# env_path = script_dir.parent.parent / ".env"  # Si le .env est dans 'InternshipLatam/'

# 3. Force le chargement et affiche un retour clair pour le debug
if env_path.exists():
    load_dotenv(dotenv_path=env_path, override=True)
    print(f"✅ Fichier .env chargé avec succès depuis : {env_path}")
else:
    print(f"❌ Impossible de trouver le fichier .env à l'emplacement : {env_path}")

# 4. Configurer les chemins d'importation
sys.path.append(str(script_dir / "src"))
sys.path.append(str(script_dir / "LangGraph_Agent"))

# 5. Tes imports locaux
from silver_enrichment import *
from database import Database
# ... (le reste de tes imports)

sys.path.append("./src")
sys.path.append("./LangGraph_Agent")

from utils import *
from langgraph.graph import StateGraph, START, END
from IPython.display import Image, display

from silver_enrichment import *
from graph_silver_enrichment import *
from APIendpoint import PlacesAPI
from database import Database
import time
import os
from dotenv import load_dotenv
load_dotenv(override=True)
import json
from functools import reduce
import datetime
import time
from functools import reduce
import ctypes


def prevent_sleep():
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001 | 0x00000002)

def allow_sleep():
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

def main():
    
    llm = LLM()
    places_api = PlacesAPI(os.getenv('MAPS_APP_KEY'))
    db = Database()
    graph = builder.compile()

    columns = ("id_offer", "raw_result")
    query = """
        SELECT DISTINCT ON (rjo.id_job) rjo.*
        FROM raw.job_offer rjo
        LEFT JOIN staging.enriched_offers se ON se.id_offer = rjo.id_job
        WHERE se.id_offer IS NULL
        ORDER BY rjo.id_job;
    """
    raw = db.execute(query)
    print(f"📋 {len(raw)} offres à traiter")
    batch_size = 15
    results = []
    t0 = time.time()

    for i in range(len(raw)):
        state = map_bronze_to_JobOfferState(raw[i])
        try:
            r = graph.invoke(state)
            results.append((r.get('id_job'), r))
        except Exception as e:
            print(f"❌ {raw[i].get('id_job')}: {e}")
            continue

        if len(results) >= batch_size:
            db.bulk_insert(table="staging.enriched_offers", columns=columns, data=results)
            elapsed = time.time() - t0
            avg_per_offer = elapsed / (i + 1)
            remaining = (len(raw) - (i + 1)) * avg_per_offer
            print(f"✅ Batch inséré ({i+1}/{len(raw)}) — écoulé: {elapsed/60:.1f}min, restant estimé: {remaining/60:.1f}min")
            results = []
        # time.sleep(20)

    if results:  # dernier batch incomplet
        db.bulk_insert(table="staging.enriched_offers", columns=columns, data=results)
        print(f"✅ Dernier batch inséré ({len(raw)}/{len(raw)})")



if __name__ == "__main__":
    prevent_sleep()
    try:
        main()
    finally:
        allow_sleep()