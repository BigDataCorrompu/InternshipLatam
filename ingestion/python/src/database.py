import os 
import requests
import psycopg2
from dotenv import load_dotenv
import logging


load_dotenv()
log = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_host = os.getenv('DB_HOST')
        self.db_name = os.getenv('DB_NAME')
        self.db_user = os.getenv('DB_USER')
        self.db_password = os.getenv('DB_PASSWORD')
        self.db_sslmode = os.getenv('DB_SSLMODE')
        self.db_channelbinding = os.getenv('DB_CHANNELBIDING')
        self._compose_url()

    def _compose_url(self):
        self.database_url = (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}/{self.db_name}"
            f"?sslmode={self.db_sslmode}&channel_binding={self.db_channelbinding}"
        )


    def execute(self, query:str, params: list = None) -> list:
        """ PERMET DE GERER UNE BDD LOCAL OU CLOUD (Actuellement uniquement cloud)"""
        #Execute HTTP NEON
        return self._execute_http(query, params)
        # Execute Psycop2 NEON
        # Execute local Database


    def _execute_http(self, query: str, params: list = None) -> list:
        """Connexion via HTTP API Neon (port 443)."""
        try:
            url = f"https://{self.db_host}/sql"
            headers = {
                "Content-Type": "application/json",
                "Neon-Connection-String": self.database_url
            }

            # ✅ params envoyés séparément dans le payload, jamais interpolés
            payload = {"query": query}
            if params:
                payload["params"] = params

            response = requests.post(url, json=payload, headers=headers)
            data = response.json()

            if response.status_code != 200:
                log.error(f"❌ HTTP {response.status_code} : {data.get('message', 'Erreur inconnue')}")
                raise Exception(f"HTTP {response.status_code} : {data.get('message')}")

            rows = data.get("rows", [])
            log.info(f"✅ Query OK ({len(rows)} lignes)")
            return rows

        except Exception as e:
            log.error(f"❌ HTTP Error : {e}")
            raise
                
    def bulk_insert(self, table: str, columns: list, data: list, batch_size: int = 500) -> None:
        total = len(data)
        inserted = 0

        for i in range(0, total, batch_size):
            chunk = data[i:i + batch_size]
            
            cols = ", ".join(f'"{c}"' for c in columns)
            
            # Paramètres liés : $1, $2, $3...
            rows_placeholders = ", ".join(
                f"({ ', '.join(f'${i * len(columns) + j + 1}' for j in range(len(columns))) })"
                for i, _ in enumerate(chunk)
            )
            
            query = f'INSERT INTO "{table}" ({cols}) VALUES {rows_placeholders};'
            
            # Aplatit toutes les valeurs en une seule liste
            params = [None if v is None else v for row in chunk for v in row]
            
            self.execute(query, params)  #  params passés séparément, jamais dans la string
            
            inserted += len(chunk)
            log.info(f"✅ Batch {i // batch_size + 1} OK ({inserted}/{total} lignes)")

        log.info(f"✅ Bulk insert terminé ({total} lignes en {-(-total // batch_size)} requêtes)")


if __name__ == '__main__':
    db = Database()

    # ── Test 1 : SELECT initial ────────────────────────
    print("\n--- TEST 1 : SELECT initial ---")
    rows = db.execute("SELECT * FROM test;")
    print(f"  {len(rows)} ligne(s) : {rows}")

    # ── Test 2 : INSERT simple ─────────────────────────
    print("\n--- TEST 2 : INSERT simple ---")
    db.execute("INSERT INTO test (\"Nom\", timestamp) VALUES ('test_simple', '2026-05-29');")
    rows = db.execute("SELECT * FROM test WHERE \"Nom\" = 'test_simple';")
    print(f"  ✅ {len(rows)} ligne(s) insérée(s)")

    # ── Test 3 : BULK INSERT 10 lignes ─────────────────
    print("\n--- TEST 3 : BULK INSERT 10 lignes ---")
    data_small = [(f"bulk{i}", "2026-05-29") for i in range(10)]
    db.bulk_insert("test", ["Nom", "timestamp"], data_small)
    rows = db.execute("SELECT COUNT(*) FROM test WHERE \"Nom\" LIKE 'bulk%';")
    print(f"  ✅ {rows[0]['count']} ligne(s) bulk trouvée(s)")

    # ── Test 4 : BULK INSERT 1500 lignes ──────────────
    print("\n--- TEST 4 : BULK INSERT 1500 lignes ---")
    data_large = [(f"bulk{i}", "2026-05-29") for i in range(1500)]
    db.bulk_insert("test", ["Nom", "timestamp"], data_large)
    rows = db.execute("SELECT COUNT(*) FROM test WHERE \"Nom\" LIKE 'bulk%';")
    print(f"  ✅ {rows[0]['count']} ligne(s) bulk trouvée(s)")

    # ── Test 5 : Types variés ──────────────────────────
    print("\n--- TEST 5 : Types variés ---")
    data_types = [
        ("string_test", "2026-05-29"),
        ("l'apostrophe", "2026-05-29"),  # test échappement
        ("null_test", None),              # test NULL
    ]
    db.bulk_insert("test", ["Nom", "timestamp"], data_types)
    rows = db.execute("SELECT * FROM test WHERE \"Nom\" IN ('string_test', 'l''apostrophe', 'null_test');")
    print(f"  ✅ {len(rows)} ligne(s) avec types variés")
    for row in rows:
        print(f"     {row}")

    # ── Test 6 : Nettoyage ─────────────────────────────
    print("\n--- TEST 6 : Nettoyage ---")
    db.execute("DELETE FROM test WHERE \"Nom\" LIKE 'bulk%';")
    db.execute("DELETE FROM test WHERE \"Nom\" IN ('test_simple', 'string_test', 'l''apostrophe', 'null_test');")
    rows = db.execute("SELECT COUNT(*) FROM test;")
    print(f"  ✅ Nettoyage OK — {rows[0]['count']} ligne(s) restante(s)")