import os
import logging
from dotenv import load_dotenv
import psycopg2

load_dotenv()

# ── Logger ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("/app/logs/pipeline.log"),
    ],
)
log = logging.getLogger(__name__)


def test_neon():
    """Test de connexion à Neon PostgreSQL."""
    log.info("─" * 50)
    log.info("🟦 TEST NEON")
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()

        # Version PostgreSQL
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        log.info(f"  ✅ Connexion OK")
        log.info(f"  📦 {version.split(',')[0]}")

        # Schémas disponibles
        cur.execute("""
            SELECT schema_name 
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast');
        """)
        schemas = [row[0] for row in cur.fetchall()]
        log.info(f"  📂 Schémas : {schemas}")

        # Tables disponibles
        cur.execute("""
            SELECT table_schema, table_name 
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
            AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name;
        """)
        tables = cur.fetchall()
        if tables:
            for schema, table in tables:
                log.info(f"  📋 {schema}.{table}")
        else:
            log.warning("  ⚠️  Aucune table trouvée — pense à exécuter 001_init.sql sur Neon")

        # Contenu de la table test
        cur.execute("SELECT id_test, nom, timestamp FROM test;")
        rows = cur.fetchall()
        if rows:
            log.info(f"  🧪 Table test — {len(rows)} ligne(s) trouvée(s) :")
            for id_test, nom, timestamp in rows:
                log.info(f"     [{id_test}] {nom} — {timestamp}")
        else:
            log.warning("  ⚠️  Table test vide")

        cur.close()
        conn.close()
        return True

    except Exception as e:
        log.error(f"  ❌ Erreur Neon : {e}")
        return False


def test_airflow():
    """Test de connexion à la base PostgreSQL Airflow."""
    log.info("─" * 50)
    log.info("🟪 TEST AIRFLOW")
    try:
        conn = psycopg2.connect(
            host="airflow-postgres",
            port=5432,
            user="airflow",
            password="airflow",
            dbname="airflow",
        )
        cur = conn.cursor()

        # Vérifie que les tables Airflow existent
        cur.execute("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = 'public';
        """)
        table_count = cur.fetchone()[0]
        log.info(f"  ✅ Connexion OK")
        log.info(f"  📋 Tables Airflow initialisées : {table_count}")

        cur.close()
        conn.close()
        return True

    except Exception as e:
        log.error(f"  ❌ Échec connexion Airflow DB : {e}")
        log.error("     → Vérifie que airflow-init a bien tourné (docker compose logs airflow-init)")
        return False


if __name__ == "__main__":
    log.info("=" * 50)
    log.info("   HELLO WORLD — LatAm Pipeline")
    log.info("=" * 50)

    neon_ok    = test_neon()
    airflow_ok = test_airflow()

    log.info("─" * 50)
    log.info("📊 RÉSULTAT")
    log.info(f"  Neon    : {'✅ OK' if neon_ok    else '❌ FAIL'}")
    log.info(f"  Airflow : {'✅ OK' if airflow_ok else '❌ FAIL'}")
    log.info("=" * 50)

    if not neon_ok or not airflow_ok:
        exit(1)