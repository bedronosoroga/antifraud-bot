from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.core import db as dal


@dataclass(frozen=True)
class QuotaState:
    balance: int
    last_daily_grant: Optional[date]


class InsufficientQuotaError(Exception):
    """Raised when a quota operation would drop the balance below zero."""


class QuotaService:
    """Manages request balances, daily bonuses and accounting."""

    def __init__(self, *, tz: str = "Europe/Moscow") -> None:
        self.tz = ZoneInfo(tz)

    async def ensure_account(self, uid: int) -> QuotaState:
        record = await dal.ensure_quota_account(uid)
        return self._build_state(record)

    async def get_state(self, uid: int, *, now: Optional[datetime] = None, ensure_daily: bool = True) -> QuotaState:
        if ensure_daily:
            return await self.ensure_daily_bonus(uid, now=now)
        record = await dal.get_quota_account(uid)
        if record is None:
            record = await dal.ensure_quota_account(uid)
        return self._build_state(record)

    async def ensure_daily_bonus(self, uid: int, *, now: Optional[datetime] = None) -> QuotaState:
        record = await dal.get_quota_account(uid)
        if record is None:
            record = await dal.ensure_quota_account(uid)

        current_date = self._current_msk_date(now)
        last_grant: Optional[date] = record.get("last_daily_grant")
        if isinstance(last_grant, datetime):
            last_grant = last_grant.date()
        balance = int(record.get("balance", 0))

        if balance > 0 or (last_grant is not None and last_grant >= current_date):
            return self._build_state(record)

        updated = await dal.change_quota_balance(
            uid,
            1,
            source="daily-grant",
            set_last_daily=current_date,
        )
        return self._build_state(updated)

    async def add(self, uid: int, amount: int, *, source: str, metadata: Optional[dict] = None) -> QuotaState:
        updated = await dal.increment_quota(uid, amount, source=source, metadata=metadata)
        return self._build_state(updated)

    async def consume(self, uid: int, *, amount: int = 1, now: Optional[datetime] = None) -> QuotaState:
        state = await self.ensure_daily_bonus(uid, now=now)
        if state.balance < amount:
            raise InsufficientQuotaError("insufficient quota balance")
        updated = await dal.consume_quota(uid, amount=amount)
        return self._build_state(updated)

    async def set_last_daily(self, uid: int, grant_date: date) -> QuotaState:
        updated = await dal.set_last_daily_grant(uid, grant_date=grant_date)
        return self._build_state(updated)

    def _build_state(self, record: dict) -> QuotaState:
        last_daily = record.get("last_daily_grant")
        if isinstance(last_daily, datetime):
            last_daily = last_daily.date()
        return QuotaState(balance=int(record.get("balance", 0)), last_daily_grant=last_daily)

    def _current_msk_date(self, now: Optional[datetime]) -> date:
        aware = self._ensure_utc(now).astimezone(self.tz)
        return aware.date()

    @staticmethod
    def _ensure_utc(value: Optional[datetime]) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


__all__ = ["QuotaService", "QuotaState", "InsufficientQuotaError"]
