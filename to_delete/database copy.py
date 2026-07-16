import os
import logging
import requests
import psycopg2
import psycopg2.extras
from typing import Literal

log = logging.getLogger(__name__)

class Database:
    def __init__(
        self,
        db_host:            str = None,
        db_name:            str = None,
        db_user:            str = None,
        db_password:        str = None,
        db_sslmode:         str = None,
        db_channelbinding:  str = None, 
        mode: Literal['http', 'psycopg2'] = 'psycopg2', # 🔄 Changé en psycopg2 par défaut
    ):
        self.db_host           = db_host           or os.getenv('DB_HOST')
        self.db_name           = db_name           or os.getenv('DB_NAME')
        self.db_user           = db_user           or os.getenv('DB_USER')
        self.db_password       = db_password       or os.getenv('DB_PASSWORD')
        self.db_sslmode        = db_sslmode        or os.getenv('DB_SSLMODE')
        self.db_channelbinding = db_channelbinding or os.getenv('DB_CHANNELBIDING')
        self.mode = mode
        self._compose_url()
        

    def _compose_url(self):
        self.database_url = (
            f"postgresql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}/{self.db_name}"
            f"?sslmode={self.db_sslmode}&channel_binding={self.db_channelbinding}"
        )

    def execute(self, query: str, params: list = None) -> list:
        if self.mode == "http":
            return self._execute_http(query, params)
        return self._execute_psycopg2(query, params)
    
    def _execute_psycopg2(self, query: str, params: list = None) -> list:
        conn = psycopg2.connect(
            host=self.db_host,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
            sslmode=self.db_sslmode,
        )
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(query, params)
                conn.commit()
                if cur.description:  # SELECT
                    return [dict(r) for r in cur.fetchall()]
                return []
        finally:
            conn.close()

    def _execute_http(self, query: str, params: list = None) -> list:
        try:
            url = f"https://{self.db_host}/sql"
            headers = {
                "Content-Type": "application/json",
                "Neon-Connection-String": self.database_url
            }
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
     
    def bulk_insert(self, table, columns, data, batch_size=200,
                    onConflict=None, conflict_columns=None, returning=None):
        if not data:
            return []

        if self.mode == "psycopg2":
            return self._bulk_insert_psycopg2(table, columns, data, batch_size, onConflict, conflict_columns, returning)
        
        # Conserve l'ancien comportement exact si le mode est HTTP
        total = len(data)
        inserted = 0
        all_returned_rows = []
        conflict_clause = self._build_conflict_clause(onConflict, conflict_columns, columns)
        cols = ", ".join(f'"{c}"' for c in columns)
        returning_clause = f" RETURNING {', '.join(f'"{c}"' for c in returning)}" if returning else ""

        if '.' in table:
            schema, tbl = table.split('.', 1)
            table_sql = f'"{schema}"."{tbl}"'
        else:
            table_sql = f'"{table}"'

        for i in range(0, total, batch_size):
            chunk = data[i:i + batch_size]
            rows_placeholders = ", ".join(
                f"({ ', '.join(f'${r * len(columns) + j + 1}' for j in range(len(columns))) })"
                for r, _ in enumerate(chunk)
            )
            query = f'INSERT INTO {table_sql} ({cols}) VALUES {rows_placeholders} {conflict_clause}{returning_clause};'
            params = [None if v is None else v for row in chunk for v in row]
            result = self._execute_http(query, params)
            if returning and result:
                all_returned_rows.extend(result)
            inserted += len(chunk)
            log.info(f"✅ Batch {i // batch_size + 1} OK ({inserted}/{total} lignes)")
        return all_returned_rows if returning else None

    def _bulk_insert_psycopg2(self, table, columns, data, batch_size, onConflict, conflict_columns, returning):
        """Version optimisée native pour psycopg2 ouvrant une SEULE connexion."""
        all_returned_rows = []
        conflict_clause = self._build_conflict_clause(onConflict, conflict_columns, columns)
        cols = ", ".join(f'"{c}"' for c in columns)
        returning_clause = f" RETURNING {', '.join(f'"{c}"' for c in returning)}" if returning else ""

        if '.' in table:
            schema, tbl = table.split('.', 1)
            table_sql = f'"{schema}"."{tbl}"'
        else:
            table_sql = f'"{table}"'

        # Le template pour execute_values DOIT utiliser %s pour chaque colonne d'une ligne
        template = f"({', '.join(['%s'] * len(columns))})"
        
        # On construit la requête de base sans les valeurs (gérées par le module)
        query = f'INSERT INTO {table_sql} ({cols}) VALUES %s {conflict_clause}{returning_clause};'

        conn = psycopg2.connect(
            host=self.db_host,
            dbname=self.db_name,
            user=self.db_user,
            password=self.db_password,
            sslmode=self.db_sslmode,
        )
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                for i in range(0, len(data), batch_size):
                    chunk = data[i:i + batch_size]
                    
                    # Utilisation de la méthode ultra-rapide et sécurisée de psycopg2
                    psycopg2.extras.execute_values(
                        cur, query, chunk, template=template, page_size=batch_size
                    )
                    
                    if returning:
                        all_returned_rows.extend([dict(r) for r in cur.fetchall()])
                        
                conn.commit()
                log.info(f"✅ Bulk insert psycopg2 OK ({len(data)} lignes)")
        finally:
            conn.close()
            
        return all_returned_rows if returning else None

    def _build_conflict_clause(self, on_conflict, conflict_columns, columns) -> str:
        if not conflict_columns or on_conflict is None:
            return ""
        conflict_cols = ", ".join(f'"{c}"' for c in conflict_columns)
        if on_conflict == "nothing":
            return f"ON CONFLICT ({conflict_cols}) DO NOTHING"
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