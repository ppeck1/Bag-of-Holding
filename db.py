"""db.py: Database connection and initialization for Bag of Holding v0P."""

import sqlite3
import os
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
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()


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
