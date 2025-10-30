from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, TypedDict

from app.core import db as dal


class RateLimitExceeded(Exception):
    def __init__(self, scope: str, retry_after: int, reset_at: datetime):
        self.scope = scope
        self.retry_after = retry_after
        self.reset_at = reset_at
        super().__init__(f"rate limit exceeded for {scope}, retry in {retry_after}s")


DEFAULT_RULES: dict[str, tuple[int, int]] = {
    "checks:run": (8, 30),
    "pay:sbox": (10, 60),
    "pay:init": (5, 60),
    "pay:status": (10, 60),
    "admin:action": (20, 60),
}


class RateLimitResult(TypedDict):
    allowed: bool
    remaining: int
    limit: int
    window_seconds: int
    retry_after: int
    reset_at: datetime


def _resolve_rule(scope: str, limit: Optional[int], per_seconds: Optional[int]) -> tuple[int, int]:
    if limit is not None and per_seconds is not None:
        return limit, per_seconds
    if scope not in DEFAULT_RULES:
        raise ValueError(f"no rate limit rule configured for scope '{scope}'")
    rule_limit, rule_window = DEFAULT_RULES[scope]
    limit = limit if limit is not None else rule_limit
    per_seconds = per_seconds if per_seconds is not None else rule_window
    return limit, per_seconds


def _now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


async def check_and_hit(
    uid: int,
    scope: str,
    *,
    limit: Optional[int] = None,
    per_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> RateLimitResult:
    limit_value, window_seconds = _resolve_rule(scope, limit, per_seconds)
    current_ts = _now(now)
    window_delta = timedelta(seconds=window_seconds)
    window_start = current_ts - window_delta

    hits = await dal.rl_count_since(uid, scope, window_start)
    oldest = await dal.rl_first_hit_since(uid, scope, window_start) if hits > 0 else None

    if hits >= limit_value:
        baseline = oldest if oldest is not None else current_ts
        reset_at = baseline + window_delta
        retry_after = max(0, int((reset_at - current_ts).total_seconds()))
        return RateLimitResult(
            allowed=False,
            remaining=0,
            limit=limit_value,
            window_seconds=window_seconds,
            retry_after=retry_after,
            reset_at=reset_at,
        )

    await dal.rl_hit(uid, scope, at=current_ts)
    if oldest is None:
        oldest = current_ts
    reset_at = oldest + window_delta
    remaining = max(0, limit_value - hits - 1)

    return RateLimitResult(
        allowed=True,
        remaining=remaining,
        limit=limit_value,
        window_seconds=window_seconds,
        retry_after=0,
        reset_at=reset_at,
    )


async def enforce(uid: int, scope: str, **kwargs: object) -> None:
    result = await check_and_hit(uid, scope, **kwargs)
    if not result["allowed"]:
        raise RateLimitExceeded(scope, result["retry_after"], result["reset_at"])


def scope_for_check(ati_code: str) -> str:
    return "checks:run"


__all__ = [
    "RateLimitExceeded",
    "DEFAULT_RULES",
    "RateLimitResult",
    "check_and_hit",
    "enforce",
    "scope_for_check",
]
