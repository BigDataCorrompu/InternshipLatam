import sys
sys.path.append("./src")
sys.path.append("./LangGraph_Agent")

import os
import time
from dotenv import load_dotenv
load_dotenv(override=True)

print("📦 Imports en cours...", flush=True)

from silver_enrichment import *
from graph_silver_enrichment import *
from APIendpoint import PlacesAPI
from database import Database

print("✅ Imports terminés", flush=True)

print("🔧 Initialisation LLM, PlacesAPI, Database...", flush=True)
llm = LLM()
print("  ✅ LLM initialisé", flush=True)

places_api = PlacesAPI(os.getenv('MAPS_APP_KEY'))
print("  ✅ PlacesAPI initialisé", flush=True)

db = Database()
print("  ✅ Database initialisée", flush=True)

# Instance FindMails avec la version corrigée
print("🔧 Instanciation FindMails...", flush=True)
find_mails_test = FindMails(llm=llm)
print("✅ FindMails instancié", flush=True)

# Test sur quelques cas connus
test_companies = [
    {"company_name": "Axity", "city": "Santiago", "country": "CL"},
    {"company_name": "Blend360", "city": "Santiago", "country": "CL"},
    {"company_name": "TestCompanyInconnue123", "city": "Santiago", "country": "CL"},
]

print(f"\n🚀 Début des tests sur {len(test_companies)} entreprises\n", flush=True)

for idx, state in enumerate(test_companies, 1):
    print("=" * 60, flush=True)
    print(f"[{idx}/{len(test_companies)}] Test: {state['company_name']}", flush=True)
    
    t0 = time.time()
    try:
        result = find_mails_test(state)
        elapsed = time.time() - t0
        print(f"⏱️  Terminé en {elapsed:.1f}s", flush=True)
        print(f"📦 Résultat final : {result}", flush=True)
    except Exception as e:
        elapsed = time.time() - t0
        print(f"❌ EXCEPTION après {elapsed:.1f}s : {type(e).__name__}: {e}", flush=True)
        import traceback
        traceback.print_exc()
    
    print("=" * 60, flush=True)
    print(flush=True)

print("🏁 Tous les tests terminés", flush=True)