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
    String,
    Table,
    Text,
    UniqueConstraint,
    delete,
    func,
    insert,
    literal,
    select,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from app.config import DEV_CREATE_ALL, PG, RUN_MIGRATIONS


metadata = MetaData()

PLAN_ENUM_VALUES = [
    "none",
    "p20",
    "p50",
    "unlim",
    "pkg5",
    "pkg15",
    "pkg35",
    "pkg75",
    "pkg150",
    "pkg500",
]
plan_enum = Enum(*PLAN_ENUM_VALUES, name="plan_enum", create_type=False, metadata=metadata)
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
    Column("total_earned_kop", BigInteger, nullable=False, server_default=text("0")),
    Column("paid_refs_count", Integer, nullable=False, server_default=text("0")),
    Column("first_paid_at", DateTime(timezone=True), nullable=True),
    Column("inviter_bonus_granted", Boolean, nullable=False, server_default=text("false")),
    Column("custom_tag", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("custom_tag", name="uq_referrals_custom_tag"),
)

Index("idx_referrals_referred_by", referrals.c.referred_by)

ref_payouts = Table(
    "ref_payouts",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("amount_kop", BigInteger, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("status", payment_status_enum, nullable=False),
    Column("details", JSONB, nullable=True),
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

rate_limit_hits = Table(
    "rate_limit_hits",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("uid", BigInteger, nullable=False),
    Column("scope", Text, nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

Index("idx_rl_uid_scope_ts", rate_limit_hits.c.uid, rate_limit_hits.c.scope, rate_limit_hits.c.ts.desc())

user_notifications = Table(
    "user_notifications",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("uid", BigInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("sent_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

Index("idx_un_uid_kind", user_notifications.c.uid, user_notifications.c.kind)

ati_code_cache = Table(
    "ati_code_cache",
    metadata,
    Column("ati_id", String(10), primary_key=True),
    Column("status", Text, nullable=False),
    Column("canonical_ati_id", String(10), nullable=True),
    Column("checked_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
)

b2b_ati_leads = Table(
    "b2b_ati_leads",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("username", Text, nullable=True),
    Column("first_name", Text, nullable=True),
    Column("last_name", Text, nullable=True),
    Column("payload", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("status", Text, nullable=False, server_default=text("'new'")),
    Column("extra", JSONB, nullable=True),
)

quota_balances = Table(
    "quota_balances",
    metadata,
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("balance", Integer, nullable=False, server_default=text("0")),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    Column("last_daily_grant", Date, nullable=True),
)

quota_events = Table(
    "quota_events",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("uid", BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    Column("delta", Integer, nullable=False),
    Column("source", Text, nullable=False),
    Column("event_key", Text, nullable=True),
    Column("metadata", JSONB, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
    UniqueConstraint("uid", "event_key", name="uq_quota_events_uid_key"),
)

Index("idx_quota_events_uid", quota_events.c.uid)

engine = create_async_engine(
    PG.url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=10,
    future=True,
)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

PROJECT_ROOT = Path(__file__).resolve().parents[2]

PLAN_VALUES = frozenset(PLAN_ENUM_VALUES)
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


def _ensure_datetime_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    ts: datetime | float,
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

    if isinstance(ts, datetime):
        ts_dt = _ensure_datetime_utc(ts)
    else:
        ts_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)

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


def _history_events_subquery(uid: int):
    return (
        select(
            literal("check").label("type"),
            history.c.ts.label("ts"),
            history.c.uid.label("uid"),
            history.c.ati.label("ati"),
            history.c.report_type.label("report_type"),
            history.c.lin.label("lin"),
            history.c.exp.label("exp"),
            literal(None).label("plan"),
            literal(None).label("amount_kop"),
        )
        .where(history.c.uid == uid)
        .subquery()
    )


async def get_history(uid: int, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    events_subq = _history_events_subquery(uid)
    stmt = (
        select(events_subq)
        .order_by(events_subq.c.ts.desc())
        .limit(limit)
        .offset(offset)
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return [dict(row) for row in result.mappings().all()]


async def count_history(uid: int) -> int:
    events_subq = _history_events_subquery(uid)
    stmt = select(func.count()).select_from(events_subq)
    async with Session() as session:
        result = await session.execute(stmt)
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


async def extend_or_start_plan(
    uid: int,
    *,
    plan: str,
    start_ts: float,
    checks_total: Optional[int] = None,
    day_cap_total: Optional[int] = None,
) -> None:
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

    if plan in {"p20", "p50"}:
        if checks_total is None or checks_total <= 0:
            raise ValueError("checks_total must be provided for quota plans")
        values["checks_left"] = checks_total
    elif plan == "unlim":
        if day_cap_total is None or day_cap_total <= 0:
            raise ValueError("day_cap_total must be provided for unlimited plan")
        values["day_cap_left"] = day_cap_total
        values["last_day_reset"] = start_dt.date()

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


async def get_payment(payment_id: str) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(pending_payments).where(pending_payments.c.id == payment_id))
        row = result.mappings().first()
        return dict(row) if row else None


async def count_confirmed_payments(uid: int) -> int:
    stmt = (
        select(func.count())
        .select_from(pending_payments)
        .where(pending_payments.c.uid == uid)
        .where(pending_payments.c.status == "confirmed")
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return int(result.scalar_one())


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
                .where((referrals.c.referred_by.is_(None)))
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
    total_earned_delta_kop: int = 0,
    paid_refs_increment: int = 0,
) -> dict[str, Any]:
    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .values(
            paid_count=referrals.c.paid_count + paid_increment,
            paid_refs_count=referrals.c.paid_refs_count + paid_refs_increment,
            balance_kop=referrals.c.balance_kop + balance_delta_kop,
            total_earned_kop=referrals.c.total_earned_kop + total_earned_delta_kop,
            updated_at=now_utc(),
        )
        .returning(referrals)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            raise ValueError("referral record not found")
        if int(row["balance_kop"]) < 0:
            raise ValueError("referral balance cannot be negative")
        return dict(row)


async def set_ref_tier(uid: int, *, tier: int, percent: int) -> None:
    if tier < 0:
        raise ValueError("tier must be non-negative")
    if percent < 0 or percent > 100:
        raise ValueError("percent must be between 0 and 100")

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


async def get_ref_by_custom_tag(tag: str) -> Optional[dict[str, Any]]:
    normalized = tag.strip().lower()
    if not normalized:
        return None
    async with Session() as session:
        result = await session.execute(select(referrals).where(referrals.c.custom_tag == normalized))
        row = result.mappings().first()
        return dict(row) if row else None


async def set_ref_custom_tag(uid: int, tag: str) -> dict[str, Any]:
    normalized = tag.strip().lower()
    if not normalized:
        raise ValueError("tag must be non-empty")

    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .values(custom_tag=normalized, updated_at=now_utc())
        .returning(referrals)
    )

    async with Session() as session, session.begin():
        try:
            result = await session.execute(stmt)
        except IntegrityError as exc:
            raise ValueError("tag already in use") from exc
        row = result.mappings().first()
        if row is None:
            raise ValueError("referral record not found")
        return dict(row)


async def add_b2b_ati_lead(
    uid: int,
    *,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    payload: str,
    source: str,
    status: str = "new",
    extra: Optional[dict[str, Any]] = None,
) -> None:
    text_payload = payload.strip()
    if not text_payload:
        raise ValueError("payload must be non-empty")
    stmt = insert(b2b_ati_leads).values(
        uid=uid,
        username=username,
        first_name=first_name,
        last_name=last_name,
        payload=text_payload,
        source=source,
        status=status,
        extra=extra,
    )
    async with Session() as session, session.begin():
        await session.execute(stmt)


async def mark_invite_bonus_granted(uid: int) -> bool:
    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .where(referrals.c.inviter_bonus_granted.is_(False))
        .values(inviter_bonus_granted=True, updated_at=now_utc())
        .returning(referrals.c.uid)
    )
    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None


async def mark_ref_first_paid(uid: int, *, when: Optional[datetime] = None) -> Optional[int]:
    ts = _ensure_datetime_utc(when or now_utc())
    stmt = (
        update(referrals)
        .where(referrals.c.uid == uid)
        .where(referrals.c.first_paid_at.is_(None))
        .values(first_paid_at=ts, updated_at=now_utc())
        .returning(referrals.c.referred_by)
    )
    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            return None
        sponsor = row.get("referred_by")
        return int(sponsor) if sponsor is not None else None


async def list_direct_referrals(uid: int, *, limit: int = 10, offset: int = 0) -> list[dict[str, Any]]:
    stmt = (
        select(
            referrals.c.uid.label("ref_uid"),
            referrals.c.referred_by,
            referrals.c.first_paid_at,
            referrals.c.created_at,
            referrals.c.inviter_bonus_granted,
            users.c.username,
            users.c.first_name,
            users.c.last_name,
        )
        .join(users, users.c.id == referrals.c.uid)
        .where(referrals.c.referred_by == uid)
        .order_by(referrals.c.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return [dict(row) for row in result.mappings().all()]


async def count_direct_referrals(
    uid: int,
    *,
    paid_only: bool = False,
    since: Optional[datetime] = None,
) -> int:
    stmt = select(func.count()).select_from(referrals).where(referrals.c.referred_by == uid)
    if paid_only:
        stmt = stmt.where(referrals.c.first_paid_at.is_not(None))
    if since is not None:
        stmt = stmt.where(referrals.c.created_at >= _ensure_datetime_utc(since))
    async with Session() as session:
        result = await session.execute(stmt)
        return int(result.scalar_one())


async def count_second_line_referrals(uid: int, *, paid_only: bool = False) -> int:
    lvl1 = aliased(referrals)
    lvl2 = aliased(referrals)
    stmt = (
        select(func.count())
        .select_from(lvl2.join(lvl1, lvl1.c.uid == lvl2.c.referred_by))
        .where(lvl1.c.referred_by == uid)
    )
    if paid_only:
        stmt = stmt.where(lvl2.c.first_paid_at.is_not(None))
    async with Session() as session:
        result = await session.execute(stmt)
        return int(result.scalar_one())


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


async def add_payout(uid: int, *, amount_kop: int, status: str, details: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if status not in PAYMENT_STATUS_VALUES:
        raise ValueError(f"unknown payment status '{status}'")
    if amount_kop <= 0:
        raise ValueError("amount_kop must be positive")

    stmt = (
        insert(ref_payouts)
        .values(uid=uid, amount_kop=amount_kop, status=status, details=details)
        .returning(ref_payouts)
    )

    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        return dict(result.mappings().one())


async def ensure_quota_account(uid: int) -> dict[str, Any]:
    stmt = pg_insert(quota_balances).values(uid=uid).on_conflict_do_nothing(index_elements=[quota_balances.c.uid])
    async with Session() as session, session.begin():
        await session.execute(stmt)
        result = await session.execute(select(quota_balances).where(quota_balances.c.uid == uid))
        row = result.mappings().first()
        if row is None:
            raise RuntimeError("failed to ensure quota account")
        return dict(row)


async def get_quota_account(uid: int) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(quota_balances).where(quota_balances.c.uid == uid))
        row = result.mappings().first()
        return dict(row) if row else None


async def change_quota_balance(
    uid: int,
    delta: int,
    *,
    source: str,
    metadata: Optional[dict[str, Any]] = None,
    allow_negative: bool = False,
    set_last_daily: Optional[date] = None,
) -> dict[str, Any]:
    if delta == 0 and set_last_daily is None:
        account = await get_quota_account(uid)
        if account is None:
            return await ensure_quota_account(uid)
        return account

    now = now_utc()
    metadata_payload = metadata or {}

    async with Session() as session, session.begin():
        await session.execute(
            pg_insert(quota_balances)
            .values(uid=uid)
            .on_conflict_do_nothing(index_elements=[quota_balances.c.uid])
        )

        update_values: dict[str, Any] = {"updated_at": now}
        if delta != 0:
            update_values["balance"] = quota_balances.c.balance + delta
        if set_last_daily is not None:
            update_values["last_daily_grant"] = set_last_daily

        stmt = (
            update(quota_balances)
            .where(quota_balances.c.uid == uid)
            .values(**update_values)
            .returning(quota_balances)
        )
        result = await session.execute(stmt)
        row = result.mappings().first()
        if row is None:
            raise RuntimeError("quota account missing")

        balance = int(row["balance"])
        if not allow_negative and balance < 0:
            raise ValueError("insufficient quota balance")

        if delta != 0:
            await session.execute(
                insert(quota_events).values(
                    uid=uid,
                    delta=delta,
                    source=source,
                    event_key=None,
                    metadata=metadata_payload,
                )
            )

        return dict(row)


async def increment_quota(
    uid: int,
    amount: int,
    *,
    source: str,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("amount must be positive")
    return await change_quota_balance(uid, amount, source=source, metadata=metadata)


async def consume_quota(
    uid: int,
    amount: int = 1,
    *,
    source: str = "request",
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("amount must be positive")
    return await change_quota_balance(uid, -amount, source=source, allow_negative=False)


async def set_last_daily_grant(uid: int, *, grant_date: date) -> dict[str, Any]:
    return await change_quota_balance(uid, 0, source="daily-grant", set_last_daily=grant_date)


async def ensure_free_grant(
    uid: int,
    *,
    granted_at_ts: float,
    expires_at_ts: float,
    total: int,
) -> None:
    if total <= 0:
        raise ValueError("total must be positive")
    if expires_at_ts <= granted_at_ts:
        raise ValueError("expires_at_ts must be greater than granted_at_ts")

    granted_at = datetime.fromtimestamp(granted_at_ts, tz=timezone.utc)
    expires_at = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)

    stmt = (
        pg_insert(free_grants)
        .values(
            uid=uid,
            granted_at=granted_at,
            expires_at=expires_at,
            total=total,
            used=0,
        )
        .on_conflict_do_nothing(index_elements=[free_grants.c.uid])
    )

    async with Session() as session, session.begin():
        await session.execute(stmt)


async def set_free_grant(
    uid: int,
    *,
    granted_at_ts: float,
    expires_at_ts: float,
    total: int,
) -> None:
    if total <= 0:
        raise ValueError("total must be positive")
    if expires_at_ts <= granted_at_ts:
        raise ValueError("expires_at_ts must be greater than granted_at_ts")

    granted_at = datetime.fromtimestamp(granted_at_ts, tz=timezone.utc)
    expires_at = datetime.fromtimestamp(expires_at_ts, tz=timezone.utc)

    stmt = (
        pg_insert(free_grants)
        .values(
            uid=uid,
            granted_at=granted_at,
            expires_at=expires_at,
            total=total,
            used=0,
        )
        .on_conflict_do_update(
            index_elements=[free_grants.c.uid],
            set_={
                "granted_at": granted_at,
                "expires_at": expires_at,
                "total": total,
                "used": 0,
            },
        )
    )

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


async def rl_hit(uid: int, scope: str, *, at: Optional[datetime] = None) -> None:
    ts = _ensure_datetime_utc(at) if at is not None else now_utc()
    async with Session() as session, session.begin():
        await session.execute(
            insert(rate_limit_hits).values(uid=uid, scope=scope, ts=ts)
        )


async def rl_count_since(uid: int, scope: str, since: datetime) -> int:
    since_dt = _ensure_datetime_utc(since)
    stmt = (
        select(func.count())
        .select_from(rate_limit_hits)
        .where(rate_limit_hits.c.uid == uid)
        .where(rate_limit_hits.c.scope == scope)
        .where(rate_limit_hits.c.ts >= since_dt)
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return int(result.scalar_one())


async def rl_first_hit_since(uid: int, scope: str, since: datetime) -> Optional[datetime]:
    since_dt = _ensure_datetime_utc(since)
    stmt = (
        select(rate_limit_hits.c.ts)
        .where(rate_limit_hits.c.uid == uid)
        .where(rate_limit_hits.c.scope == scope)
        .where(rate_limit_hits.c.ts >= since_dt)
        .order_by(rate_limit_hits.c.ts.asc())
        .limit(1)
    )
    async with Session() as session:
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


async def rl_prune(before: datetime) -> int:
    before_dt = _ensure_datetime_utc(before)
    stmt = (
        delete(rate_limit_hits)
        .where(rate_limit_hits.c.ts < before_dt)
        .returning(rate_limit_hits.c.id)
    )
    async with Session() as session, session.begin():
        result = await session.execute(stmt)
        rows = result.fetchall()
        return len(rows)


async def rl_prune_before(ts: datetime) -> int:
    return await rl_prune(ts)


async def get_ati_cache(ati_id: str) -> Optional[dict[str, Any]]:
    async with Session() as session:
        result = await session.execute(select(ati_code_cache).where(ati_code_cache.c.ati_id == ati_id))
        row = result.mappings().first()
        return dict(row) if row else None


async def upsert_ati_cache(
    ati_id: str,
    *,
    status: str,
    checked_at: datetime,
    canonical_ati_id: Optional[str] = None,
) -> None:
    checked = _ensure_datetime_utc(checked_at)
    stmt = (
        pg_insert(ati_code_cache)
        .values(
            ati_id=ati_id,
            status=status,
            canonical_ati_id=canonical_ati_id,
            checked_at=checked,
        )
        .on_conflict_do_update(
            index_elements=[ati_code_cache.c.ati_id],
            set_={
                "status": status,
                "canonical_ati_id": canonical_ati_id,
                "checked_at": checked,
            },
        )
    )
    async with Session() as session, session.begin():
        await session.execute(stmt)
