from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import select, func

from app.core import db as dal

DB_PATH = Path(os.getenv("BETA_FORM_DB", "data/beta_forms.db"))

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def init_activity_db() -> None:
    conn = _get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS beta_activity (
            uid INTEGER PRIMARY KEY,
            first_start_at TIMESTAMP,
            reminder_start_sent INTEGER DEFAULT 0,
            reminder_3h_sent INTEGER DEFAULT 0,
            reminder_24_sent_at TIMESTAMP,
            reminder_24_count INTEGER DEFAULT 0,
            reminder_48_sent_at TIMESTAMP,
            inactive INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()


def ensure_activity(uid: int, first_start_at: Optional[datetime] = None) -> None:
    conn = _get_conn()
    conn.execute(
        """
        INSERT INTO beta_activity(uid, first_start_at)
        VALUES (?, ?)
        ON CONFLICT(uid) DO NOTHING
        """,
        (uid, first_start_at),
    )
    if first_start_at is not None:
        conn.execute(
            "UPDATE beta_activity SET first_start_at=COALESCE(first_start_at, ?), updated_at=CURRENT_TIMESTAMP WHERE uid=?",
            (first_start_at, uid),
        )
    conn.commit()


def mark_inactive(uid: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE beta_activity SET inactive=1, updated_at=CURRENT_TIMESTAMP WHERE uid=?",
        (uid,),
    )
    conn.commit()


def mark_start_reminder_sent(uid: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE beta_activity SET reminder_start_sent=1, updated_at=CURRENT_TIMESTAMP WHERE uid=?",
        (uid,),
    )
    conn.commit()


def mark_3h_sent(uid: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE beta_activity SET reminder_3h_sent=1, updated_at=CURRENT_TIMESTAMP WHERE uid=?",
        (uid,),
    )
    conn.commit()


def mark_24h_sent(uid: int) -> None:
    conn = _get_conn()
    conn.execute(
        """
        UPDATE beta_activity
        SET reminder_24_sent_at=CURRENT_TIMESTAMP,
            reminder_24_count=COALESCE(reminder_24_count,0)+1,
            updated_at=CURRENT_TIMESTAMP
        WHERE uid=?
        """,
        (uid,),
    )
    conn.commit()


def mark_48h_sent(uid: int) -> None:
    conn = _get_conn()
    conn.execute(
        "UPDATE beta_activity SET reminder_48_sent_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE uid=?",
        (uid,),
    )
    conn.commit()


def get_activity_rows() -> list[sqlite3.Row]:
    conn = _get_conn()
    cur = conn.execute("SELECT * FROM beta_activity")
    return cur.fetchall()


async def get_history_stats(uid: int) -> Tuple[int, Optional[datetime], Optional[datetime]]:
    async with dal.Session() as session:
        result = await session.execute(
            select(
                func.count(dal.history.c.id),
                func.min(dal.history.c.ts),
                func.max(dal.history.c.ts),
            ).where(dal.history.c.uid == uid)
        )
        count, first_ts, last_ts = result.first()
        return int(count or 0), first_ts, last_ts


async def populate_first_start_from_history(uid: int) -> Optional[datetime]:
    count, first_ts, _ = await get_history_stats(uid)
    if first_ts is None:
        return None
    ensure_activity(uid, first_ts)
    return first_ts


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
