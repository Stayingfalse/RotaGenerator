from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Generator

DB_PATH = os.environ.get("ROTA_DB", "rota.db")


@contextmanager
def _get_conn() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(seed_payload: dict) -> None:
    """Create the config table and seed it with *seed_payload* if it is empty.

    The seed is only applied once — on first run when no config row exists yet.
    Subsequent starts leave the stored data intact.
    """
    with _get_conn() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS dashboard_config "
            "(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)"
        )
        row = conn.execute("SELECT COUNT(*) FROM dashboard_config").fetchone()
        if row[0] == 0:
            conn.execute(
                "INSERT INTO dashboard_config (id, payload) VALUES (1, ?)",
                (json.dumps(seed_payload),),
            )


def load_config() -> dict:
    """Return the stored dashboard config dict, or {} if none exists."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT payload FROM dashboard_config WHERE id = 1"
        ).fetchone()
        if row:
            return json.loads(row[0])
        return {}


def save_config(payload: dict) -> None:
    """Persist *payload* as the dashboard config, replacing any existing value."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO dashboard_config (id, payload) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
            (json.dumps(payload),),
        )
