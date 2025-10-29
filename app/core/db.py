from __future__ import annotations

import asyncio
from asyncio.subprocess import PIPE
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    String,
    insert,
    select,
    text,
    update,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import DEV_CREATE_ALL, PG, RUN_MIGRATIONS


metadata = MetaData()

plan_enum = Enum("none", "p20", "p50", "unlim", name="plan_enum", create_type=False, metadata=metadata)
risk_enum = Enum("none", "elevated", "critical", "scarce", "unknown", name="risk_enum", create_type=False, metadata=metadata)
report_enum = Enum("A", "B", "C", "D", "E", name="report_enum", create_type=False, metadata=metadata)
payment_status_enum = Enum("waiting", "confirmed", "rejected", name="payment_status_enum", create_type=False, metadata=metadata)

users = Table(
    "users",
    metadata,
    Column("id", BigInteger, primary_key=True),
    Column("username", Text, nullable=True),
    Column("first_name", Text, nullable=True),
    Column("last_name", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("company_ati", String(length=7), nullable=True),
    CheckConstraint("company_ati ~ '^[0-9]{1,7}$'", name="ck_users_company_ati_format"),
)

subs = Table(
    "subs",
    metadata,
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("plan", plan_enum, nullable=False, server_default=text("'none'::plan_enum")),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("expires_at", DateTime(timezone=True), nullable=True),
    Column("checks_left", Integer, nullable=True),
    Column("day_cap_left", Integer, nullable=True),
    Column("last_day_reset", Date, nullable=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

history = Table(
    "history",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("ati", String(length=7), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("lin", Integer, nullable=False, server_default=text("0")),
    Column("exp", Integer, nullable=False, server_default=text("0")),
    Column("risk", risk_enum, nullable=False),
    Column("report_type", report_enum, nullable=False),
    CheckConstraint("ati ~ '^[0-9]{1,7}$'", name="ck_history_ati_format"),
)

Index("ix_history_uid_ts_desc", history.c.uid, history.c.ts.desc())
Index("ix_history_ati", history.c.ati)

user_flags = Table(
    "user_flags",
    metadata,
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("unlimited_override", Boolean, nullable=False, server_default=text("false")),
)

referrals = Table(
    "referrals",
    metadata,
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("code", Text, nullable=False, unique=True),
    Column("referred_by", BigInteger, ForeignKey("users.id"), nullable=True),
    Column("paid_count", Integer, nullable=False, server_default=text("0")),
    Column("tier", Integer, nullable=False, server_default=text("0")),
    Column("percent", Integer, nullable=False, server_default=text("10")),
    Column("balance_kop", BigInteger, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

ref_payouts = Table(
    "ref_payouts",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("amount_kop", BigInteger, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("status", payment_status_enum, nullable=False),
)

pending_payments = Table(
    "pending_payments",
    metadata,
    Column("id", Text, primary_key=True),
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("plan", plan_enum, nullable=False),
    Column("amount_kop", Integer, nullable=False),
    Column("provider_invoice_id", Text, nullable=True),
    Column("status", payment_status_enum, nullable=False, server_default=text("'waiting'::payment_status_enum")),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("metadata", JSONB, nullable=True),
)

Index("ix_pending_payments_uid_status", pending_payments.c.uid, pending_payments.c.status)

free_grants = Table(
    "free_grants",
    metadata,
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("granted_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("total", Integer, nullable=False, server_default=text("5")),
    Column("used", Integer, nullable=False, server_default=text("0")),
)

engine = create_async_engine(
    PG.url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    future=True,
)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PLAN_VALUES = frozenset(["none", "p20", "p50", "unlim"])
PAID_PLAN_VALUES = frozenset(["p20", "p50", "unlim"])
RISK_VALUES = frozenset(["none", "elevated", "critical", "scarce", "unknown"])
REPORT_VALUES = frozenset(["A", "B", "C", "D", "E"])
PAYMENT_STATUS_VALUES = frozenset(["waiting", "confirmed", "rejected"])

ATI_RE = re.compile(r"^\d{1,7}$")


def now_ts() -> float:
    return time.time()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def today_date() -> str:
    return now_utc().date().isoformat()


def base36(n: int) -> str:
    if n < 0:
        raise ValueError("n must be >= 0")
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while n:
        n, r = divmod(n, 36)
        out = digits[r] + out
    return out or "0"


def _to_datetime(value: Any, field: str) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    raise ValueError(f"{field} must be datetime/float/int/str or None")


def _to_date(value: Any, field: str) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValueError(f"{field} must be date/str or None")


async def init_db(run_migrations: bool = False, dev_create_all: bool = False) -> None:
    effective_run = run_migrations or RUN_MIGRATIONS
    effective_create_all = dev_create_all or DEV_CREATE_ALL

    if effective_run:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "alembic",
            "upgrade",
            "head",
            cwd=str(PROJECT_ROOT),
            stdout=PIPE,
            stderr=PIPE,
        )
        stdout, stderr = await process.communicate()
        return_code = process.returncode
        if return_code != 0:
            stderr_text = (stderr.decode() if stderr else "").strip()
            raise RuntimeError(f"alembic upgrade head failed: {stderr_text}")
        return

    if effective_create_all:
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE TYPE IF NOT EXISTS plan_enum AS ENUM ('none','p20','p50','unlim')")
            )
            await conn.execute(
                text("CREATE TYPE IF NOT EXISTS risk_enum AS ENUM ('none','elevated','critical','scarce','unknown')")
            )
            await conn.execute(
                text("CREATE TYPE IF NOT EXISTS report_enum AS ENUM ('A','B','C','D','E')")
            )
            await conn.execute(
                text("CREATE TYPE IF NOT EXISTS payment_status_enum AS ENUM ('waiting','confirmed','rejected')")
            )
            await conn.run_sync(metadata.create_all)
        return

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def dispose_engine() -> None:
    await engine.dispose()


async def ensure_user(
    uid: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
) -> None:
    stmt = pg_insert(users).values(
        id=uid,
        username=username,
        first_name=first_name,
        last_name=last_name,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[users.c.id],
        set_={
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        },
    )

    async with Session() as session, session.begin():
        await session.execute(stmt)


async def get_user(uid: int) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(users).where(users.c.id == uid))
        row = result.mappings().first()
        return dict(row) if row else None


async def set_company_ati(uid: int, ati_code: Optional[str]) -> None:
    if ati_code is not None:
        if not ATI_RE.match(ati_code):
            raise ValueError("company ATI must be digits, length up to 7")

    async with Session() as session, session.begin():
        stmt = (
            update(users)
            .where(users.c.id == uid)
            .values(company_ati=ati_code)
        )
        await session.execute(stmt)


async def append_history(
    uid: int,
    *,
    ati: str,
    ts: float,
    lin: int,
    exp: int,
    risk: str,
    report_type: str,
) -> None:
    if not ATI_RE.match(ati):
        raise ValueError("ati must be 1..7 digits")
    if risk not in RISK_VALUES:
        raise ValueError(f"unknown risk '{risk}'")
    if report_type not in REPORT_VALUES:
        raise ValueError(f"unknown report_type '{report_type}'")

    ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc)

    async with Session() as session, session.begin():
        await session.execute(
            insert(history).values(
                uid=uid,
                ati=ati,
                ts=ts_dt,
                lin=int(lin),
                exp=int(exp),
                risk=risk,
                report_type=report_type,
            )
        )


async def get_history(uid: int, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
    stmt = (
        select(history)
        .where(history.c.uid == uid)
        .order_by(history.c.ts.desc())
        .limit(limit)
        .offset(offset)
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return [dict(row) for row in result.mappings().all()]


async def count_history(uid: int) -> int:
    async with Session() as session:
        result = await session.execute(
            select(func.count()).select_from(history).where(history.c.uid == uid)
        )
        return int(result.scalar_one())


async def get_sub(uid: int) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(subs).where(subs.c.uid == uid))
        row = result.mappings().first()
        return dict(row) if row else None


async def set_sub(uid: int, data: dict) -> None:
    allowed_keys = {
        "plan",
        "started_at",
        "expires_at",
        "checks_left",
        "day_cap_left",
        "last_day_reset",
        "updated_at",
    }
    unexpected = set(data) - allowed_keys
    if unexpected:
        raise ValueError(f"unexpected sub fields: {', '.join(sorted(unexpected))}")
    if "plan" not in data:
        raise ValueError("plan is required")

    plan_value = data["plan"]
    if plan_value not in PLAN_VALUES:
        raise ValueError(f"unknown plan '{plan_value}'")

    started_at = _to_datetime(data.get("started_at"), "started_at")
    expires_at = _to_datetime(data.get("expires_at"), "expires_at")
    last_day_reset = _to_date(data.get("last_day_reset"), "last_day_reset")
    updated_at = _to_datetime(data.get("updated_at"), "updated_at") or now_utc()

    checks_left = data.get("checks_left")
    if checks_left is not None and not isinstance(checks_left, int):
        raise ValueError("checks_left must be int or None")
    day_cap_left = data.get("day_cap_left")
    if day_cap_left is not None and not isinstance(day_cap_left, int):
        raise ValueError("day_cap_left must be int or None")

    payload = dict(
        uid=uid,
        plan=plan_value,
        started_at=started_at,
        expires_at=expires_at,
        checks_left=checks_left,
        day_cap_left=day_cap_left,
        last_day_reset=last_day_reset,
        updated_at=updated_at,
    )

    stmt = pg_insert(subs).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=[subs.c.uid],
        set_={
            "plan": plan_value,
            "started_at": started_at,
            "expires_at": expires_at,
            "checks_left": checks_left,
            "day_cap_left": day_cap_left,
            "last_day_reset": last_day_reset,
            "updated_at": updated_at,
        },
    )

    async with Session() as session, session.begin():
        await session.execute(stmt)


async def extend_or_start_plan(uid: int, *, plan: str, start_ts: float) -> None:
    if plan not in PAID_PLAN_VALUES:
        raise ValueError(f"plan must be one of {', '.join(sorted(PAID_PLAN_VALUES))}")

    start_dt = datetime.fromtimestamp(start_ts, tz=timezone.utc)
    expires_dt = start_dt + timedelta(days=30)

    values: dict[str, Any] = {
        "uid": uid,
        "plan": plan,
        "started_at": start_dt,
        "expires_at": expires_dt,
        "checks_left": None,
        "day_cap_left": None,
        "last_day_reset": None,
        "updated_at": now_utc(),
    }

    if plan == "p20":
        values["checks_left"] = 20
    elif plan == "p50":
        values["checks_left"] = 50
    elif plan == "unlim":
        values["day_cap_left"] = 50
        values["last_day_reset"] = date.fromisoformat(today_date())

    stmt = pg_insert(subs).values(values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[subs.c.uid],
        set_={
            "plan": values["plan"],
            "started_at": values["started_at"],
            "expires_at": values["expires_at"],
            "checks_left": values["checks_left"],
            "day_cap_left": values["day_cap_left"],
            "last_day_reset": values["last_day_reset"],
            "updated_at": values["updated_at"],
        },
    )

    async with Session() as session, session.begin():
        await session.execute(stmt)


async def decrement_check(uid: int, *, now_ts: float) -> None:
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    stmt = (
        update(subs)
        .where(subs.c.uid == uid)
        .where(subs.c.checks_left.isnot(None))
        .where(subs.c.checks_left > 0)
        .values(checks_left=subs.c.checks_left - 1, updated_at=now_dt)
        .returning(subs.c.checks_left)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        remaining = result.scalar_one_or_none()
        if remaining is None:
            raise ValueError("no checks left")


async def ensure_unlim_daycap(uid: int, *, now_date: str, cap_total: int = 50) -> None:
    date_value = date.fromisoformat(now_date)
    stmt = (
        update(subs)
        .where(subs.c.uid == uid)
        .where(subs.c.day_cap_left.isnot(None))
        .where(
            (subs.c.last_day_reset.is_(None))
            | (subs.c.last_day_reset != date_value)
        )
        .values(day_cap_left=cap_total, last_day_reset=date_value, updated_at=now_utc())
    )

    async with Session() as session, session.begin():
        await session.execute(stmt)


async def decrement_unlim_daycap(uid: int, *, now_date: str, cap_total: int = 50) -> None:
    date_value = date.fromisoformat(now_date)
    stmt = (
        update(subs)
        .where(subs.c.uid == uid)
        .where(subs.c.day_cap_left.isnot(None))
        .where(subs.c.last_day_reset == date_value)
        .where(subs.c.day_cap_left > 0)
        .values(day_cap_left=subs.c.day_cap_left - 1, updated_at=now_utc())
        .returning(subs.c.day_cap_left)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        remaining = result.scalar_one_or_none()
        if remaining is None:
            raise ValueError("day cap exceeded")


async def set_unlimited_override(uid: int, enabled: bool) -> None:
    stmt = pg_insert(user_flags).values(uid=uid, unlimited_override=enabled)
    stmt = stmt.on_conflict_do_update(
        index_elements=[user_flags.c.uid],
        set_={"unlimited_override": enabled},
    )
    async with Session() as session, session.begin():
        await session.execute(stmt)


async def get_unlimited_override(uid: int) -> bool:
    async with Session() as session:
        result = await session.execute(select(user_flags.c.unlimited_override).where(user_flags.c.uid == uid))
        value = result.scalar_one_or_none()
        return bool(value) if value is not None else False


async def create_pending_payment(
    uid: int,
    *,
    plan: str,
    amount_kop: int,
    provider_invoice_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict[str, Any]:
    if plan not in PLAN_VALUES:
        raise ValueError(f"unknown plan '{plan}'")
    if amount_kop <= 0:
        raise ValueError("amount_kop must be positive")

    payment_id = f"{int(time.time() * 1000)}-{uid}"

    stmt = (
        insert(pending_payments)
        .values(
            id=payment_id,
            uid=uid,
            plan=plan,
            amount_kop=amount_kop,
            provider_invoice_id=provider_invoice_id,
            metadata=metadata,
        )
        .returning(pending_payments)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        row = result.mappings().one()
        return dict(row)


async def list_pending_payments(uid: int) -> list[dict[str, Any]]:
    stmt = (
        select(pending_payments)
        .where(pending_payments.c.uid == uid)
        .order_by(pending_payments.c.created_at.desc())
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return [dict(row) for row in result.mappings().all()]


async def mark_payment_status(uid: int, payment_id: str, *, status: str) -> None:
    if status not in PAYMENT_STATUS_VALUES:
        raise ValueError(f"unknown payment status '{status}'")

    stmt = (
        update(pending_payments)
        .where(pending_payments.c.uid == uid, pending_payments.c.id == payment_id)
        .values(status=status)
        .returning(pending_payments.c.id)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ValueError("pending payment not found")


async def ensure_ref(uid: int, referred_by: Optional[int] = None) -> dict[str, Any]:
    if referred_by is not None and referred_by == uid:
        raise ValueError("user cannot refer themselves")

    code = base36(uid)

    stmt = pg_insert(referrals).values(
        uid=uid,
        code=code,
        referred_by=referred_by,
    ).on_conflict_do_nothing(index_elements=[referrals.c.uid])

    async with Session() as session, session.begin():
        await session.execute(stmt)
        if referred_by is not None:
            await session.execute(
                update(referrals)
                .where(referrals.c.uid == uid)
                .values(referred_by=referred_by, updated_at=now_utc())
            )
        result = await session.execute(select(referrals).where(referrals.c.uid == uid))
        row = result.mappings().first()
        if row is None:
            raise RuntimeError("failed to ensure referral record")
        return dict(row)


async def get_ref(uid: int) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(referrals).where(referrals.c.uid == uid))
        row = result.mappings().first()
        return dict(row) if row else None


async def update_ref_stats(
    uid: int,
    *,
    paid_increment: int = 0,
    balance_delta_kop: int = 0,
) -> dict[str, Any]:
    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .values(
            paid_count=referrals.c.paid_count + paid_increment,
            balance_kop=referrals.c.balance_kop + balance_delta_kop,
            updated_at=now_utc(),
        )
        .returning(referrals)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            raise ValueError("referral record not found")
        return dict(row)


async def set_ref_tier(uid: int, *, tier: int, percent: int) -> None:
    if tier not in {0, 1, 2, 3, 4}:
        raise ValueError("tier must be between 0 and 4")
    if percent not in {10, 20, 30, 40, 50}:
        raise ValueError("percent must be one of 10,20,30,40,50")

    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .values(tier=tier, percent=percent, updated_at=now_utc())
        .returning(referrals.c.uid)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        if result.scalar_one_or_none() is None:
            raise ValueError("referral record not found")


async def spend_ref_balance(uid: int, *, amount_kop: int) -> bool:
    if amount_kop <= 0:
        raise ValueError("amount_kop must be positive")

    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .where(referrals.c.balance_kop >= amount_kop)
        .values(balance_kop=referrals.c.balance_kop - amount_kop, updated_at=now_utc())
        .returning(referrals.c.balance_kop)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def add_payout(uid: int, *, amount_kop: int, status: str) -> dict[str, Any]:
    if status not in PAYMENT_STATUS_VALUES:
        raise ValueError(f"unknown payment status '{status}'")
    if amount_kop <= 0:
        raise ValueError("amount_kop must be positive")

    stmt = (
        insert(ref_payouts)
        .values(uid=uid, amount_kop=amount_kop, status=status)
        .returning(ref_payouts)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        return dict(result.mappings().one())


async def ensure_free_grant(uid: int, *, now_ts: float) -> None:
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    expires_dt = now_dt + timedelta(days=3)

    stmt = pg_insert(free_grants).values(
        uid=uid,
        granted_at=now_dt,
        expires_at=expires_dt,
        total=5,
        used=0,
    ).on_conflict_do_nothing(index_elements=[free_grants.c.uid])

    async with Session() as session, session.begin():
        await session.execute(stmt)


async def get_free_grant(uid: int) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(free_grants).where(free_grants.c.uid == uid))
        row = result.mappings().first()
        return dict(row) if row else None


async def free_grant_active(uid: int, *, now_ts: float) -> bool:
    record = await get_free_grant(uid)
    if not record:
        return False

    expires_at: datetime = record["expires_at"]
    used: int = record["used"]
    total: int = record["total"]
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    return used < total and now_dt < expires_at


async def increment_free_used(uid: int, *, now_ts: float) -> None:
    now_dt = datetime.fromtimestamp(now_ts, tz=timezone.utc)
    stmt = (
        update(free_grants)
        .where(free_grants.c.uid == uid)
        .where(free_grants.c.expires_at > now_dt)
        .where(free_grants.c.used < free_grants.c.total)
        .values(used=free_grants.c.used + 1)
        .returning(free_grants.c.used, free_grants.c.total)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        row = result.first()
        if row is None:
            raise ValueError("free grant inactive")
