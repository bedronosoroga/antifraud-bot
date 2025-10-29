from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional, TypedDict

from app.config import FREE
from app.core import db as dal

SECONDS_IN_HOUR = 3600


class FreeStatus(TypedDict):
    total: int
    used: int
    available: int
    active: bool
    granted_at_ts: float
    expires_at_ts: float
    hours_left: int


class CanFreeResult(TypedDict):
    ok: bool
    reason: Optional[str]


def _now_ts() -> float:
    return time.time()


def _to_timestamp(value: Optional[datetime]) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _build_status(record: dict | None, now_ts: float) -> FreeStatus:
    total = FREE["total"]
    ttl_hours = FREE["ttl_hours"]

    if record is None:
        granted_at_ts = now_ts
        expires_at_ts = now_ts + ttl_hours * SECONDS_IN_HOUR
        used = 0
    else:
        granted_at_ts = _to_timestamp(record.get("granted_at"))
        expires_at_ts = _to_timestamp(record.get("expires_at"))
        total = int(record.get("total", total))
        used = int(record.get("used", 0))

    available = max(total - used, 0)
    active = bool(now_ts < expires_at_ts and available > 0)
    hours_left = max(int((expires_at_ts - now_ts) // SECONDS_IN_HOUR), 0)

    return FreeStatus(
        total=total,
        used=used,
        available=available,
        active=active,
        granted_at_ts=granted_at_ts,
        expires_at_ts=expires_at_ts,
        hours_left=hours_left,
    )


async def ensure_on_first_seen(uid: int, *, now_ts: Optional[float] = None) -> None:
    ts = now_ts if now_ts is not None else _now_ts()
    grant = await dal.get_free_grant(uid)
    if grant is not None:
        return

    total = FREE["total"]
    ttl_hours = FREE["ttl_hours"]
    if total <= 0:
        raise ValueError("FREE.total must be positive")
    if ttl_hours <= 0:
        raise ValueError("FREE.ttl_hours must be positive")
    expires_at_ts = ts + ttl_hours * SECONDS_IN_HOUR
    await dal.ensure_free_grant(
        uid,
        granted_at_ts=ts,
        expires_at_ts=expires_at_ts,
        total=total,
    )


async def grant(
    uid: int,
    *,
    total: int,
    ttl_hours: int,
    now_ts: Optional[float] = None,
) -> None:
    if total <= 0:
        raise ValueError("total must be positive")
    if ttl_hours <= 0:
        raise ValueError("ttl_hours must be positive")

    ts = now_ts if now_ts is not None else _now_ts()
    expires_at_ts = ts + ttl_hours * SECONDS_IN_HOUR
    await dal.set_free_grant(
        uid,
        granted_at_ts=ts,
        expires_at_ts=expires_at_ts,
        total=total,
    )


async def _fetch_or_create(uid: int, ts: float) -> dict | None:
    record = await dal.get_free_grant(uid)
    if record is not None:
        return record
    await ensure_on_first_seen(uid, now_ts=ts)
    return await dal.get_free_grant(uid)


async def get_status(uid: int, *, now_ts: Optional[float] = None) -> FreeStatus:
    ts = now_ts if now_ts is not None else _now_ts()
    record = await _fetch_or_create(uid, ts)
    if record is None:
        return _build_status(None, ts)
    return _build_status(record, ts)


async def can_consume(uid: int, *, now_ts: Optional[float] = None) -> CanFreeResult:
    ts = now_ts if now_ts is not None else _now_ts()
    record = await _fetch_or_create(uid, ts)
    if record is None:
        return CanFreeResult(ok=False, reason="no-grant")

    status = _build_status(record, ts)
    if status["active"]:
        return CanFreeResult(ok=True, reason=None)

    expired = ts >= status["expires_at_ts"]
    if expired:
        return CanFreeResult(ok=False, reason="expired")
    if status["available"] <= 0:
        return CanFreeResult(ok=False, reason="exhausted")
    return CanFreeResult(ok=False, reason="no-grant")


async def consume(uid: int, *, now_ts: Optional[float] = None) -> None:
    ts = now_ts if now_ts is not None else _now_ts()
    record = await _fetch_or_create(uid, ts)
    if record is None:
        raise ValueError("free quota unavailable")

    status = _build_status(record, ts)
    if not status["active"]:
        raise ValueError("free quota unavailable")

    try:
        await dal.increment_free_used(uid, now_ts=ts)
    except ValueError as exc:
        raise ValueError("free quota unavailable") from exc


__all__ = [
    "FreeStatus",
    "CanFreeResult",
    "ensure_on_first_seen",
    "grant",
    "get_status",
    "can_consume",
    "consume",
]
