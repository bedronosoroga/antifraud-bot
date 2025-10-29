from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Literal, Optional, TypedDict

from app.config import PLANS
from app.core import db as dal

PlanName = Literal["p20", "p50", "unlim"]


class SubInfo(TypedDict, total=False):
    plan: str
    started_at_ts: Optional[float]
    expires_at_ts: Optional[float]
    checks_left: Optional[int]
    day_cap_left: Optional[int]
    last_day_reset: Optional[str]
    is_active: bool
    is_unlimited: bool
    unlimited_override: bool
    days_left: Optional[int]


class CanConsumeResult(TypedDict):
    ok: bool
    mode: Literal["none", "quota", "unlim", "override"]
    reason: Optional[str]


def utc_now_ts() -> float:
    return time.time()


def to_date_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


async def get_status(uid: int, *, now_ts: Optional[float] = None) -> SubInfo:
    ts = now_ts if now_ts is not None else utc_now_ts()
    sub = await dal.get_sub(uid)
    override = await dal.get_unlimited_override(uid)

    plan = sub["plan"] if sub and sub.get("plan") else "none"
    started_at = sub.get("started_at") if sub else None
    expires_at = sub.get("expires_at") if sub else None
    checks_left = sub.get("checks_left") if sub else None
    day_cap_left = sub.get("day_cap_left") if sub else None
    last_day_reset_value = sub.get("last_day_reset") if sub else None

    started_at_ts = started_at.timestamp() if isinstance(started_at, datetime) else None
    expires_at_ts = expires_at.timestamp() if isinstance(expires_at, datetime) else None
    last_day_reset = last_day_reset_value.isoformat() if last_day_reset_value else None

    is_active = bool(expires_at_ts is not None and expires_at_ts > ts)
    is_unlimited = bool(override or (plan == "unlim" and is_active))

    info: SubInfo = {
        "plan": plan,
        "started_at_ts": started_at_ts,
        "expires_at_ts": expires_at_ts,
        "checks_left": checks_left,
        "day_cap_left": day_cap_left,
        "last_day_reset": last_day_reset,
        "is_active": is_active,
        "is_unlimited": is_unlimited,
        "unlimited_override": override,
        "days_left": None,
    }

    if expires_at_ts is not None:
        delta_days = int((expires_at_ts - ts) // 86400)
        info["days_left"] = max(delta_days, 0)

    return info


async def purchase(uid: int, plan: PlanName, *, paid_at_ts: Optional[float] = None) -> None:
    if plan not in PLANS:
        raise ValueError(f"unknown plan '{plan}'")

    start_ts = paid_at_ts if paid_at_ts is not None else utc_now_ts()

    if plan == "unlim":
        cap_total = PLANS["unlim"]["day_cap"]
        await dal.extend_or_start_plan(
            uid,
            plan=plan,
            start_ts=start_ts,
            day_cap_total=cap_total,
        )
    else:
        checks_total = PLANS[plan]["checks_total"]
        await dal.extend_or_start_plan(
            uid,
            plan=plan,
            start_ts=start_ts,
            checks_total=checks_total,
        )


async def can_consume(uid: int, *, now_ts: Optional[float] = None) -> CanConsumeResult:
    ts = now_ts if now_ts is not None else utc_now_ts()

    if await dal.get_unlimited_override(uid):
        return CanConsumeResult(ok=True, mode="override", reason=None)

    sub = await dal.get_sub(uid)
    plan = sub["plan"] if sub and sub.get("plan") else "none"
    expires_at = sub.get("expires_at") if sub else None
    expires_at_ts = expires_at.timestamp() if isinstance(expires_at, datetime) else None
    is_active = bool(expires_at_ts is not None and expires_at_ts > ts)

    if plan == "unlim" and is_active:
        today = to_date_utc(ts)
        cap_total = PLANS["unlim"]["day_cap"]
        await dal.ensure_unlim_daycap(uid, now_date=today, cap_total=cap_total)
        refreshed = await dal.get_sub(uid) or {}
        day_cap_left = refreshed.get("day_cap_left")
        if day_cap_left is not None and day_cap_left > 0:
            return CanConsumeResult(ok=True, mode="unlim", reason=None)
        return CanConsumeResult(ok=False, mode="unlim", reason="day cap exceeded")

    if plan in {"p20", "p50"} and is_active:
        checks_left = sub.get("checks_left") if sub else None
        if checks_left is not None and checks_left > 0:
            return CanConsumeResult(ok=True, mode="quota", reason=None)
        return CanConsumeResult(ok=False, mode="quota", reason="no checks left")

    return CanConsumeResult(ok=False, mode="none", reason="no active subscription")


async def consume(uid: int, *, now_ts: Optional[float] = None) -> None:
    ts = now_ts if now_ts is not None else utc_now_ts()
    decision = await can_consume(uid, now_ts=ts)

    if not decision["ok"]:
        mode = decision["mode"]
        if mode == "none":
            raise ValueError("no active subscription")
        if mode == "quota":
            raise ValueError("no checks left")
        if mode == "unlim":
            raise ValueError("day cap exceeded")
        raise ValueError(decision.get("reason") or "cannot consume")

    mode = decision["mode"]
    if mode == "override":
        return

    if mode == "unlim":
        today = to_date_utc(ts)
        cap_total = PLANS["unlim"]["day_cap"]
        await dal.ensure_unlim_daycap(uid, now_date=today, cap_total=cap_total)
        await dal.decrement_unlim_daycap(uid, now_date=today, cap_total=cap_total)
        return

    if mode == "quota":
        await dal.decrement_check(uid, now_ts=ts)
        return

    raise ValueError("no active subscription")


__all__ = [
    "PlanName",
    "SubInfo",
    "CanConsumeResult",
    "utc_now_ts",
    "to_date_utc",
    "get_status",
    "purchase",
    "can_consume",
    "consume",
]
