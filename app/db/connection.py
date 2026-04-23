"""app/db/connection.py: Database connection and initialization for Bag of Holding v2.

Migrated from db.py (v0P). Logic unchanged.
Phase 4 additions:
  - lineage table initialized here (CREATE TABLE IF NOT EXISTS in schema.sql)
  - corpus_class index created after ALTER TABLE
  - schema_version stamped v2.1.0 for Phase 4
Phase 8 additions (Daenary + DCNS):
  - doc_coordinates table created (migration-safe)
  - doc_edges table created (migration-safe)
  - schema_version stamped v2.2.0
"""

import sqlite3
import os
import time
from pathlib import Path

DB_PATH = os.environ.get("BOH_DB", "boh.db")
SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_conn()

    # Run base schema (idempotent via CREATE IF NOT EXISTS)
    # Strip the corpus_class index since the column may not exist yet
    schema = open(SCHEMA_PATH).read()
    # Remove the corpus_class index line — applied after ALTER TABLE below
    schema_safe = "\n".join(
        line for line in schema.splitlines()
        if "idx_docs_corpus_class" not in line
    )
    conn.executescript(schema_safe)

    # v2 migration-safe column additions
    _add_column_if_missing(conn, "conflicts", "acknowledged", "INTEGER DEFAULT 0")
    _add_column_if_missing(conn, "docs", "corpus_class", "TEXT DEFAULT 'CORPUS_CLASS:DRAFT'")

    # Now safe to create the corpus_class index
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_docs_corpus_class ON docs(corpus_class)"
    )

    # Phase 8: doc_coordinates and doc_edges tables (created via schema.sql IF NOT EXISTS —
    # but we also call executescript with the full schema so this is already handled above;
    # repeat explicitly here so existing databases get them via migration too).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS doc_coordinates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id          TEXT    NOT NULL,
            dimension       TEXT    NOT NULL,
            state           INTEGER NOT NULL,
            quality         REAL,
            confidence      REAL,
            mode            TEXT,
            observed_ts     INTEGER,
            valid_until_ts  INTEGER,
            source          TEXT    DEFAULT 'frontmatter',
            UNIQUE(doc_id, dimension)
        );
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_doc_id      ON doc_coordinates(doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_dimension   ON doc_coordinates(dimension);
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_state       ON doc_coordinates(state);
        CREATE INDEX IF NOT EXISTS idx_doc_coordinates_valid_until ON doc_coordinates(valid_until_ts);

        CREATE TABLE IF NOT EXISTS doc_edges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_doc_id   TEXT    NOT NULL,
            target_doc_id   TEXT    NOT NULL,
            edge_type       TEXT    NOT NULL,
            state           INTEGER,
            permeability    REAL,
            load_score      REAL,
            detected_ts     INTEGER NOT NULL,
            detail          TEXT,
            UNIQUE(source_doc_id, target_doc_id, edge_type)
        );
        CREATE INDEX IF NOT EXISTS idx_doc_edges_source ON doc_edges(source_doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_edges_target ON doc_edges(target_doc_id);
        CREATE INDEX IF NOT EXISTS idx_doc_edges_type   ON doc_edges(edge_type);
    """)

    # schema_version table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version TEXT NOT NULL,
            applied_ts INTEGER NOT NULL
        )
    """)
    for ver in ("v2.0.0", "v2.1.0", "v2.2.0"):
        existing = conn.execute(
            "SELECT version FROM schema_version WHERE version = ?", (ver,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO schema_version (version, applied_ts) VALUES (?, ?)",
                (ver, int(time.time())),
            )

    conn.commit()
    conn.close()


def _add_column_if_missing(conn: sqlite3.Connection, table: str, column: str, col_def: str):
    """Safely add a column to a table if it does not already exist."""
    existing_cols = {
        row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing_cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")


def fetchall(query: str, params=()) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def fetchone(query: str, params=()) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(query, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def execute(query: str, params=()):
    conn = get_conn()
    try:
        conn.execute(query, params)
        conn.commit()
    finally:
        conn.close()


def executemany(query: str, params_list: list):
    conn = get_conn()
    try:
        conn.executemany(query, params_list)
        conn.commit()
    finally:
        conn.close()
