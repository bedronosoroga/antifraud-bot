from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

__all__ = ["FreePack", "FreeStatus", "FreePackRepo", "FreeService"]


@dataclass(frozen=True)
class FreePack:
    """Snapshot of the state of a user's onboarding free package."""

    user_id: int
    total: int
    used: int
    granted_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class FreeStatus:
    """Aggregated view of the free package tailored for UI and handlers."""

    user_id: int
    has_pack: bool
    total: int | None
    used: int | None
    remaining: int | None
    granted_at: datetime | None
    expires_at: datetime | None
    is_active: bool
    can_consume: bool
    reason: str | None
    expiring_soon: bool
    low_left: bool
    expired_with_unused: bool


class FreePackRepo(Protocol):
    """Abstract storage interface for free package snapshots."""

    def get_pack(self, user_id: int) -> FreePack | None: ...

    def create_pack(
        self,
        user_id: int,
        granted_at: datetime,
        expires_at: datetime,
        total: int,
    ) -> FreePack: ...

    def set_used(self, user_id: int, used: int) -> FreePack: ...


class FreeService:
    """Business rules for granting and consuming onboarding free checks."""

    def __init__(self, repo: FreePackRepo, *, total: int, ttl_days: int) -> None:
        """Store configuration and dependencies for subsequent operations."""
        if total <= 0:
            msg = "total must be positive"
            raise ValueError(msg)
        if ttl_days <= 0:
            msg = "ttl_days must be positive"
            raise ValueError(msg)
        self._repo = repo
        self._total = total
        self._ttl = timedelta(days=ttl_days)

    def ensure_pack(self, user_id: int, now: datetime) -> FreePack:
        """Fetch the user's pack or lazily create one when it is missing."""
        pack = self._repo.get_pack(user_id)
        if pack is not None:
            return pack
        expires_at = now + self._ttl
        return self._repo.create_pack(user_id, now, expires_at, self._total)

    def get_status(self, user_id: int, now: datetime) -> FreeStatus:
        """Return the aggregated status of the user's free package."""
        pack = self._repo.get_pack(user_id)
        return self._build_status(pack, now, user_id=user_id)

    def can_consume(self, user_id: int, now: datetime) -> tuple[bool, str | None]:
        """Tell whether a free attempt may be consumed at the given moment."""
        status = self.get_status(user_id, now)
        return status.can_consume, status.reason

    def consume_one(self, user_id: int, now: datetime) -> FreeStatus:
        """Try consuming one attempt and return the resulting status snapshot."""
        pack = self._repo.get_pack(user_id)
        if pack is None:
            created_pack = self.ensure_pack(user_id, now)
            return self._build_status(created_pack, now, user_id=user_id)
        status = self._build_status(pack, now, user_id=user_id)
        if not status.can_consume:
            return status
        updated_pack = self._repo.set_used(user_id, pack.used + 1)
        return self._build_status(updated_pack, now, user_id=user_id)

    def _build_status(
        self,
        pack: FreePack | None,
        now: datetime,
        *,
        user_id: int | None = None,
    ) -> FreeStatus:
        """Compose a :class:`FreeStatus` instance from a raw pack snapshot."""
        has_pack = pack is not None
        if pack is not None:
            actual_user_id = pack.user_id
        elif user_id is not None:
            actual_user_id = user_id
        else:
            msg = "user_id must be provided when pack is None"
            raise ValueError(msg)
        total: int | None = pack.total if pack is not None else None
        used: int | None = pack.used if pack is not None else None
        granted_at: datetime | None = pack.granted_at if pack is not None else None
        expires_at: datetime | None = pack.expires_at if pack is not None else None
        is_active = pack is not None and now < pack.expires_at
        if pack is not None:
            remaining: int | None = max(pack.total - pack.used, 0)
        else:
            remaining = None
        can_consume = bool(is_active and remaining is not None and remaining > 0)
        if pack is None:
            reason = "пакет не выдан"
        elif not is_active:
            reason = "срок истёк"
        elif remaining == 0:
            reason = "закончились бесплатные"
        else:
            reason = None
        expiring_soon = bool(
            pack is not None
            and is_active
            and remaining is not None
            and remaining > 0
            and (pack.expires_at - now) <= timedelta(hours=24)
        )
        low_left = bool(
            pack is not None
            and is_active
            and remaining is not None
            and 0 < remaining <= 2
        )
        expired_with_unused = bool(
            pack is not None
            and not is_active
            and (pack.total - pack.used) > 0
        )
        return FreeStatus(
            user_id=actual_user_id,
            has_pack=has_pack,
            total=total,
            used=used,
            remaining=remaining,
            granted_at=granted_at,
            expires_at=expires_at,
            is_active=is_active,
            can_consume=can_consume,
            reason=reason,
            expiring_soon=expiring_soon,
            low_left=low_left,
            expired_with_unused=expired_with_unused,
        )
