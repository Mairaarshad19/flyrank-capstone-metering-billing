import os
import sqlite3

DEFAULT_DB_PATH = os.environ.get("DATABASE_PATH", "data/billing.db")

_MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "migrations")


def get_connection(db_path=None):
    path = db_path or DEFAULT_DB_PATH
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_migrations(conn):
    migration_files = sorted(f for f in os.listdir(_MIGRATIONS_DIR) if f.endswith(".sql"))
    for filename in migration_files:
        with open(os.path.join(_MIGRATIONS_DIR, filename), "r") as handle:
            script = handle.read()
        conn.executescript(script)
    conn.commit()


def init_db(db_path=None):
    conn = get_connection(db_path)
    run_migrations(conn)
    return conn
