from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.getenv("BETA_FORM_DB", "data/beta_forms.db"))

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute(
            """
            CREATE TABLE IF NOT EXISTS whitelist (
                uid INTEGER PRIMARY KEY,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        _conn.commit()
    return _conn


def add_to_whitelist(uid: int) -> None:
    conn = _get_conn()
    conn.execute("INSERT OR IGNORE INTO whitelist (uid) VALUES (?)", (uid,))
    conn.commit()


def is_whitelisted(uid: int) -> bool:
    conn = _get_conn()
    cur = conn.execute("SELECT 1 FROM whitelist WHERE uid=? LIMIT 1", (uid,))
    return cur.fetchone() is not None
