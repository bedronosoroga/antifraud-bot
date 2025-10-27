from __future__ import annotations

"""Subscription service providing pure business logic for subscription handling."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal, Optional, Protocol


PlanCode = Literal["p20", "p50", "unlim"]


@dataclass(frozen=True)
class PlanTerms:
    """Terms for a subscription plan."""

    code: PlanCode
    period_days: int
    included_per_period: int
    daily_cap: Optional[int]


PLANS: dict[PlanCode, PlanTerms] = {
    "p20": PlanTerms("p20", period_days=30, included_per_period=20, daily_cap=None),
    "p50": PlanTerms("p50", period_days=30, included_per_period=50, daily_cap=None),
    "unlim": PlanTerms("unlim", period_days=30, included_per_period=0, daily_cap=50),
}


class SubsRepo(Protocol):
    """Protocol describing the storage of user subscriptions."""

    def get_latest_subscription(self, user_id: int) -> Subscription | None:
        """Return the latest subscription for the user or ``None`` if absent."""

    def add_subscription(
        self,
        user_id: int,
        plan: PlanCode,
        purchased_at: datetime,
        starts_at: datetime,
        ends_at: datetime,
    ) -> Subscription:
        """Persist a subscription purchase and return the stored entity."""


class UsageRepo(Protocol):
    """Protocol describing usage accounting for subscriptions."""

    def count_used_since(self, user_id: int, since: datetime) -> int:
        """Count how many checks were used since the given moment."""

    def count_used_on_date(self, user_id: int, on: date) -> int:
        """Count how many checks were used on a particular date."""

    def add_usage(self, user_id: int, at: datetime) -> None:
        """Record that a single check was consumed at the given moment."""


@dataclass(frozen=True)
class Subscription:
    """Concrete subscription purchase entry."""

    user_id: int
    plan: PlanCode
    purchased_at: datetime
    starts_at: datetime
    ends_at: datetime


@dataclass(frozen=True)
class SubsStatus:
    """Aggregated status information for UI handlers."""

    user_id: int
    plan: PlanCode | None
    period_start: Optional[datetime]
    period_end: Optional[datetime]
    used: Optional[int]
    total: Optional[int]
    daily_used: Optional[int]
    daily_cap: Optional[int]
    can_consume: bool
    reason: str | None


class SubsService:
    """Pure business logic service for handling subscription operations."""

    def __init__(self, subs_repo: SubsRepo, usage_repo: UsageRepo) -> None:
        """Initialize the service with required repositories."""

        self._subs_repo = subs_repo
        self._usage_repo = usage_repo

    def current(self, user_id: int, now: datetime) -> Subscription | None:
        """Return the active subscription for ``user_id`` at ``now`` if available."""

        latest = self._subs_repo.get_latest_subscription(user_id)
        if latest is None:
            return None
        if latest.starts_at <= now < latest.ends_at:
            return latest
        return None

    def get_status(self, user_id: int, now: datetime) -> SubsStatus:
        """Return subscription status for the given user and moment."""

        subscription = self.current(user_id, now)
        if subscription is None:
            return SubsStatus(
                user_id=user_id,
                plan=None,
                period_start=None,
                period_end=None,
                used=None,
                total=None,
                daily_used=None,
                daily_cap=None,
                can_consume=False,
                reason="нет активной подписки",
            )

        terms = PLANS[subscription.plan]
        if terms.daily_cap is None:
            used = self._usage_repo.count_used_since(user_id, subscription.starts_at)
            total = terms.included_per_period
            can_consume = used < total
            reason = None if can_consume else "закончились проверки"
            return SubsStatus(
                user_id=user_id,
                plan=subscription.plan,
                period_start=subscription.starts_at,
                period_end=subscription.ends_at,
                used=used,
                total=total,
                daily_used=None,
                daily_cap=None,
                can_consume=can_consume,
                reason=reason,
            )

        today = now.date()
        daily_used = self._usage_repo.count_used_on_date(user_id, today)
        can_consume = daily_used < terms.daily_cap
        reason = None if can_consume else "достигнут дневной лимит"
        return SubsStatus(
            user_id=user_id,
            plan=subscription.plan,
            period_start=subscription.starts_at,
            period_end=subscription.ends_at,
            used=None,
            total=None,
            daily_used=daily_used,
            daily_cap=terms.daily_cap,
            can_consume=can_consume,
            reason=reason,
        )

    def can_consume(self, user_id: int, now: datetime) -> tuple[bool, str | None]:
        """Return whether a user can consume one more check right now."""

        status = self.get_status(user_id, now)
        return status.can_consume, status.reason

    def consume_one(self, user_id: int, now: datetime) -> SubsStatus:
        """Consume a single check if possible and return the updated status."""

        status = self.get_status(user_id, now)
        if not status.can_consume:
            return status

        self._usage_repo.add_usage(user_id, now)
        return self.get_status(user_id, now)

    def purchase(self, user_id: int, plan: PlanCode, purchased_at: datetime) -> Subscription:
        """Register a new subscription purchase and return the stored entity."""

        terms = PLANS[plan]
        starts_at = purchased_at
        ends_at = purchased_at + timedelta(days=terms.period_days)
        return self._subs_repo.add_subscription(
            user_id=user_id,
            plan=plan,
            purchased_at=purchased_at,
            starts_at=starts_at,
            ends_at=ends_at,
        )


__all__ = [
    "PlanCode",
    "PlanTerms",
    "PLANS",
    "SubsRepo",
    "UsageRepo",
    "Subscription",
    "SubsStatus",
    "SubsService",
]
