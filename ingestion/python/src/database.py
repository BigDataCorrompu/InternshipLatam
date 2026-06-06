import os 
import requests
import psycopg2
from dotenv import load_dotenv
import logging
from typing import Literal, Any


load_dotenv()
log = logging.getLogger(__name__)

class Database:
    def __init__(
        self,
        db_host:            str = None,
        db_name:            str = None,
        db_user:            str = None,
        db_password:        str = None,
        db_sslmode:         str = None,
        db_channelbinding:  str = None
    ):
        self.db_host           = db_host           or os.getenv('DB_HOST')
        self.db_name           = db_name           or os.getenv('DB_NAME')
        self.db_user           = db_user           or os.getenv('DB_USER')
        self.db_password       = db_password       or os.getenv('DB_PASSWORD')
        self.db_sslmode        = db_sslmode        or os.getenv('DB_SSLMODE')
        self.db_channelbinding = db_channelbinding or os.getenv('DB_CHANNELBIDING')
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
                

    def bulk_insert(
            self, 
            table:str, 
            columns: list[str], 
            data: list[tuple[Any]], 
            batch_size: int=500, 
            onConflict: Literal["update", "nothing"] | None = None,
            conflict_columns: list[str] = None
            ) -> None:
        total = len(data) # Total of lines to insert
        inserted = 0 

        conflict_clause = self._build_conflict_clause(onConflict, conflict_columns, columns) 
        cols = ", ".join(f'"{c}"' for c in columns) # Generate columns name keeping the upper case 

        for i in range(0, total, batch_size): # Run from first to last with batch_size step
            chunk = data[i:i + batch_size] # chunk from i to i+batch_size
            # Parameters : $1, $2, $3...
            rows_placeholders = ", ".join(
                f"({ ', '.join(f'${i * len(columns) + j + 1}' for j in range(len(columns))) })"
                for i, _ in enumerate(chunk)
            )
            # Generate query (Handle schemas)
            if '.' in table:
                schema, tbl = table.split('.', 1)
                table_sql = f'"{schema}"."{tbl}"'
            else:
                table_sql = f'"{table}"'

            query = f'INSERT INTO {table_sql} ({cols}) VALUES {rows_placeholders} {conflict_clause};'

            print(f"Query : {query}")

            # Aplatit toutes les valeurs en une seule liste
            params = [None if v is None else v for row in chunk for v in row]
            
            self.execute(query, params)  #  params passés séparément, jamais dans la string
            
            inserted += len(chunk)
            log.info(f"✅ Batch {i // batch_size + 1} OK ({inserted}/{total} lignes)")

        log.info(f"✅ Bulk insert terminé ({total} lignes en {-(-total // batch_size)} requêtes)")


    def _build_conflict_clause(self, on_conflict, conflict_columns, columns) -> str:
        if not conflict_columns or on_conflict is None:
            return ""
        
        conflict_cols = ", ".join(f'"{c}"' for c in conflict_columns)
        
        if on_conflict == "nothing":
            return f"ON CONFLICT ({conflict_cols}) DO NOTHING"
        
        # UPDATE — met à jour toutes les colonnes sauf celles de conflict
        update_cols = [c for c in columns if c not in conflict_columns]
        updates = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in update_cols)
        return f"ON CONFLICT ({conflict_cols}) DO UPDATE SET {updates}"
    

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
    db = Database()

    print("\n" + "═" * 60)
    print("🧪 DATABASE TEST SUITE")
    print("═" * 60)
    
    # ── Nettoyage initial ─────────────────────────────────────
    print("\n--- INIT : Nettoyage avant tests ---")
    db.execute('DELETE FROM test WHERE "Nom" LIKE $1;', ["bulk%"])
    db.execute('DELETE FROM test WHERE "Nom" LIKE $1;', ["stress%"])
    db.execute(
        'DELETE FROM test WHERE "Nom" = ANY($1::text[]);',
        [["test_simple", "string_test", "l'apostrophe", "null_test"]]
    )
    print("  ✅ Table nettoyée")

    # ── Test 1 : Connexion & SELECT ───────────────────────────
    print("\n--- TEST 1 : Connexion & SELECT ---")
    rows = db.execute("SELECT * FROM test;")
    print(f"  ✅ Connexion OK — {len(rows)} ligne(s) existante(s)")

    # ── Test 2 : INSERT simple avec params ────────────────────
    print("\n--- TEST 2 : INSERT simple (paramétré) ---")
    db.execute(
        'INSERT INTO test ("Nom", timestamp) VALUES ($1, $2);',
        ["test_simple", "2026-05-29"]
    )
    rows = db.execute('SELECT * FROM test WHERE "Nom" = $1;', ["test_simple"])
    print(f"  ✅ {len(rows)} ligne(s) insérée(s) : {rows}")

    # ── Test 3 : BULK INSERT 10 lignes ────────────────────────
    print("\n--- TEST 3 : BULK INSERT 10 lignes ---")
    data_small = [(f"bulk{i}", "2026-05-29") for i in range(10)]
    db.bulk_insert("test", ["Nom", "timestamp"], data_small)
    rows = db.execute('SELECT COUNT(*) FROM test WHERE "Nom" LIKE $1;', ["bulk%"])
    print(f"  ✅ {rows[0]['count']} ligne(s) bulk trouvée(s)")

    # ── Test 4 : BULK INSERT 1500 lignes (multi-batch) ────────
    print("\n--- TEST 4 : BULK INSERT 1500 lignes (3 batchs de 500) ---")
    data_large = [(f"stress{i}", "2026-05-29") for i in range(10)]
    db.bulk_insert("test", ["Nom", "timestamp"], data_large, batch_size=500)
    rows = db.execute('SELECT COUNT(*) FROM test WHERE "Nom" LIKE $1;', ["stress%"])
    print(f"  ✅ {rows[0]['count']} ligne(s) stress trouvée(s)")

    # ── Test 5 : Types variés + NULL ──────────────────────────
    print("\n--- TEST 5 : Types variés (string, apostrophe, NULL) ---")
    data_types = [
        ("string_test",  "2026-05-29"),
        ("l'apostrophe", "2026-05-29"),
        ("null_test",    None),
    ]
    db.bulk_insert("test", ["Nom", "timestamp"], data_types)
    rows = db.execute(
        'SELECT * FROM test WHERE "Nom" = ANY($1::text[]);',
        [["string_test", "l'apostrophe", "null_test"]]
    )
    print(f"  ✅ {len(rows)} ligne(s) avec types variés")
    for row in rows:
        print(f"     {row}")



    # ── Test 6 : ON CONFLICT DO NOTHING ──────────────────────
    print("\n--- TEST 6 : ON CONFLICT DO NOTHING ---")
    data_conflict = [("bulk0", "2026-05-29")]  # bulk0 existe déjà
    db.bulk_insert(
        "test", ["Nom", "timestamp"], data_conflict,
        onConflict="nothing",
        conflict_columns=["Nom"]   # ✅ manquait
    )
    rows = db.execute('SELECT COUNT(*) FROM test WHERE "Nom" = $1;', ["bulk0"])
    print(f"  ✅ Conflict ignoré — {rows[0]['count']} ligne(s) (doit rester 1)")

    # ── Test 7 : ON CONFLICT DO UPDATE ───────────────────────
    print("\n--- TEST 7 : ON CONFLICT DO UPDATE ---")
    data_update = [("bulk0", "2099-01-01")]  # mise à jour du timestamp
    db.bulk_insert(
        "test", ["Nom", "timestamp"], data_update,
        onConflict="update",
        conflict_columns=["Nom"]
    )
    rows = db.execute('SELECT * FROM test WHERE "Nom" = $1;', ["bulk0"])
    print(f"  ✅ Timestamp mis à jour : {rows[0]}")

    # ── Test 8 : Nettoyage ────────────────────────────────────
    print("\n--- TEST 8 : Nettoyage ---")
    db.execute('DELETE FROM test WHERE "Nom" LIKE $1;', ["bulk%"])
    db.execute('DELETE FROM test WHERE "Nom" LIKE $1;', ["stress%"])
    db.execute(
        'DELETE FROM test WHERE "Nom" = ANY($1::text[]);',
        [["test_simple", "string_test", "l'apostrophe", "null_test"]]
    )
    rows = db.execute("SELECT COUNT(*) FROM test;")
    print(f"  ✅ Nettoyage OK — {rows[0]['count']} ligne(s) restante(s)")

    print("\n" + "═" * 60)
    print("✅ TOUS LES TESTS TERMINÉS")
    print("═" * 60)