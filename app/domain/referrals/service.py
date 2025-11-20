from __future__ import annotations

import math
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, TypedDict
from zoneinfo import ZoneInfo

from app.config import (
    REF_SECOND_LINE_PERCENT,
    REF_TIERS,
    REF_WITHDRAW_FEE_PERCENT,
    REF_WITHDRAW_MIN_KOP,
    REF_WITHDRAW_MIN_USD,
    cfg,
)
from app.core import db as dal

MSK_TZ = ZoneInfo(cfg.tz or "Europe/Moscow")
_TAG_RE = re.compile(r"^[a-z0-9_]{3,24}$")


class RefInfo(TypedDict, total=False):
    code: str
    custom_tag: Optional[str]
    referred_by: Optional[int]
    paid_count: int                # number of referral purchases credited
    paid_refs_count: int           # number of 1st-line referrals who paid at least once
    tier: int
    percent: int
    balance_kop: int
    total_earned_kop: int
    next_tier_at: Optional[int]


class AwardResult(TypedDict, total=False):
    sponsor_uid: Optional[int]
    percent: int
    amount_kop: int
    awarded_kop: int
    second_line_uid: Optional[int]
    second_line_percent: int
    second_line_awarded_kop: int


class ReferralDashboard(TypedDict):
    info: RefInfo
    direct_total: int
    direct_paid: int
    second_total: int
    second_paid: int
    today_direct: int


class ReferralEntry(TypedDict):
    uid: int
    username: Optional[str]
    full_name: str
    created_at: datetime
    paid: bool


class PayoutRequest(TypedDict):
    amount_kop: int
    net_amount_kop: int
    fee_kop: int
    accepted: bool
    reason: Optional[str]


def calc_percent_by_paid(paid_refs: int) -> tuple[int, int]:
    tier_index = 0
    percent = REF_TIERS[0]["percent"]
    for idx, tier in enumerate(REF_TIERS):
        if paid_refs >= tier["min_paid"]:
            tier_index = idx
            percent = tier["percent"]
        else:
            break
    return tier_index, percent


def next_tier_threshold(paid_refs: int) -> Optional[int]:
    for tier in REF_TIERS:
        if paid_refs < tier["min_paid"]:
            return tier["min_paid"]
    return None


def _ensure_utc(value: Optional[datetime] = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _msk_day_bounds(now: Optional[datetime] = None) -> tuple[datetime, datetime]:
    current = _ensure_utc(now).astimezone(MSK_TZ)
    start_local = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _build_ref_info(data: dict[str, object]) -> RefInfo:
    paid_count = int(data.get("paid_count", 0))
    paid_refs = int(data.get("paid_refs_count", 0))
    balance_kop = int(data.get("balance_kop", 0))
    total_earned = int(data.get("total_earned_kop", 0))
    stored_tier = int(data.get("tier", 0))
    stored_percent = int(data.get("percent", 0))
    computed_tier, computed_percent = calc_percent_by_paid(paid_refs)
    tier = stored_tier if stored_tier > computed_tier else computed_tier
    percent = stored_percent if stored_percent > computed_percent else computed_percent
    return RefInfo(
        code=str(data.get("code", "")),
        custom_tag=data.get("custom_tag"),
        referred_by=data.get("referred_by"),
        paid_count=paid_count,
        paid_refs_count=paid_refs,
        tier=tier,
        percent=percent,
        balance_kop=balance_kop,
        total_earned_kop=total_earned,
        next_tier_at=next_tier_threshold(paid_refs),
    )


async def ensure_profile(uid: int, referred_by_uid: Optional[int] = None) -> RefInfo:
    if referred_by_uid is not None and referred_by_uid == uid:
        referred_by_uid = None
    record = await dal.ensure_ref(uid, referred_by=referred_by_uid)
    return _build_ref_info(record)


async def get_info(uid: int) -> RefInfo:
    record = await dal.get_ref(uid)
    if record is None:
        record = await dal.ensure_ref(uid)
    return _build_ref_info(record)


async def resolve_ref_code(code: str) -> Optional[int]:
    stripped = code.strip().lower()
    if not stripped:
        return None
    custom = await dal.get_ref_by_custom_tag(stripped)
    if custom is not None:
        return int(custom["uid"])
    try:
        value = int(stripped, 36)
    except ValueError:
        return None
    return value if value >= 0 else None


async def _forms_cycle(uid: int, sponsor_uid: int) -> bool:
    current = sponsor_uid
    visited: set[int] = set()
    while current:
        if current == uid:
            return True
        if current in visited:
            break
        visited.add(current)
        record = await dal.get_ref(current)
        if record is None:
            break
        parent = record.get("referred_by")
        current = int(parent) if parent is not None else None
    return False


async def attach_referrer_by_code(uid: int, code: str) -> bool:
    sponsor_uid = await resolve_ref_code(code)
    if sponsor_uid is None or sponsor_uid == uid:
        return False

    if await _forms_cycle(uid, sponsor_uid):
        return False

    await ensure_profile(sponsor_uid)
    record = await dal.get_ref(uid)
    if record is None:
        record = await dal.ensure_ref(uid, referred_by=sponsor_uid)
        return record.get("referred_by") == sponsor_uid

    if record.get("referred_by") is not None:
        return False

    updated = await dal.ensure_ref(uid, referred_by=sponsor_uid)
    return updated.get("referred_by") == sponsor_uid


async def maybe_grant_invite_bonus(uid: int) -> Optional[int]:
    record = await dal.get_ref(uid)
    if record is None:
        return None
    sponsor = record.get("referred_by")
    if sponsor is None or sponsor == uid:
        return None
    granted = await dal.mark_invite_bonus_granted(uid)
    return sponsor if granted else None


async def record_paid_subscription(payer_uid: int, *, amount_kop: int) -> AwardResult:
    if amount_kop <= 0:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    payer_info = await ensure_profile(payer_uid)
    sponsor_uid = payer_info.get("referred_by")

    if sponsor_uid is None or sponsor_uid == payer_uid:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    sponsor_uid = int(sponsor_uid)
    sponsor_info = await ensure_profile(sponsor_uid)

    paid_refs_increment = 0
    sponsor_of_paid = await dal.mark_ref_first_paid(payer_uid)
    if sponsor_of_paid is not None and sponsor_of_paid == sponsor_uid:
        paid_refs_increment = 1

    paid_refs_total = sponsor_info.get("paid_refs_count", 0) + paid_refs_increment
    tier_index, percent = calc_percent_by_paid(paid_refs_total)
    direct_award = math.floor(amount_kop * percent / 100)

    updated = await dal.update_ref_stats(
        sponsor_uid,
        paid_increment=1,
        balance_delta_kop=direct_award,
        total_earned_delta_kop=direct_award,
        paid_refs_increment=paid_refs_increment,
    )
    await dal.set_ref_tier(sponsor_uid, tier=tier_index, percent=percent)

    second_line_uid = sponsor_info.get("referred_by")
    second_award = 0
    if second_line_uid is not None and second_line_uid not in {payer_uid, sponsor_uid}:
        second_award = math.floor(amount_kop * REF_SECOND_LINE_PERCENT / 100)
        await dal.update_ref_stats(
            int(second_line_uid),
            paid_increment=0,
            balance_delta_kop=second_award,
            total_earned_delta_kop=second_award,
        )

    return AwardResult(
        sponsor_uid=sponsor_uid,
        percent=percent,
        amount_kop=amount_kop,
        awarded_kop=direct_award,
        second_line_uid=int(second_line_uid) if second_award else None,
        second_line_percent=REF_SECOND_LINE_PERCENT if second_award else 0,
        second_line_awarded_kop=second_award,
    )


async def record_refund(payer_uid: int, *, amount_kop: int) -> AwardResult:
    if amount_kop <= 0:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    payer_info = await get_info(payer_uid)
    sponsor_uid = payer_info.get("referred_by")
    if sponsor_uid is None or sponsor_uid == payer_uid:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    sponsor_uid = int(sponsor_uid)
    sponsor_info = await get_info(sponsor_uid)
    tier_index, percent = calc_percent_by_paid(sponsor_info.get("paid_refs_count", 0))
    refund_amount = math.floor(amount_kop * percent / 100)
    to_deduct = min(refund_amount, sponsor_info["balance_kop"])

    if to_deduct > 0:
        updated = await dal.update_ref_stats(
            sponsor_uid,
            paid_increment=0,
            balance_delta_kop=-to_deduct,
            total_earned_delta_kop=-to_deduct,
        )
        await dal.set_ref_tier(sponsor_uid, tier=tier_index, percent=percent)

    second_line_uid = sponsor_info.get("referred_by")
    second_refund = 0
    if second_line_uid is not None and second_line_uid not in {payer_uid, sponsor_uid}:
        second_info = await get_info(int(second_line_uid))
        second_calc = math.floor(amount_kop * REF_SECOND_LINE_PERCENT / 100)
        second_refund = min(second_calc, second_info["balance_kop"])
        if second_refund > 0:
            await dal.update_ref_stats(
                int(second_line_uid),
                paid_increment=0,
                balance_delta_kop=-second_refund,
                total_earned_delta_kop=-second_refund,
            )

    return AwardResult(
        sponsor_uid=sponsor_uid,
        percent=percent,
        amount_kop=amount_kop,
        awarded_kop=-to_deduct,
        second_line_uid=int(second_line_uid) if second_refund else None,
        second_line_percent=REF_SECOND_LINE_PERCENT if second_refund else 0,
        second_line_awarded_kop=-second_refund,
    )


async def get_dashboard(uid: int, *, now: Optional[datetime] = None) -> ReferralDashboard:
    info = await get_info(uid)
    today_start, _ = _msk_day_bounds(now)
    direct_total = await dal.count_direct_referrals(uid)
    direct_paid = await dal.count_direct_referrals(uid, paid_only=True)
    second_total = await dal.count_second_line_referrals(uid)
    second_paid = await dal.count_second_line_referrals(uid, paid_only=True)
    today_direct = await dal.count_direct_referrals(uid, since=today_start)
    return ReferralDashboard(
        info=info,
        direct_total=direct_total,
        direct_paid=direct_paid,
        second_total=second_total,
        second_paid=second_paid,
        today_direct=today_direct,
    )


async def list_recent_referrals(uid: int, *, limit: int = 10) -> list[ReferralEntry]:
    rows = await dal.list_direct_referrals(uid, limit=limit)
    entries: list[ReferralEntry] = []
    for row in rows:
        username = row.get("username")
        first_name = row.get("first_name") or ""
        last_name = row.get("last_name") or ""
        full_name = (first_name + " " + last_name).strip()
        if not full_name and username:
            full_name = username
        entries.append(
            ReferralEntry(
                uid=int(row.get("ref_uid")),
                username=username,
                full_name=full_name or "Без имени",
                created_at=row.get("created_at"),
                paid=row.get("first_paid_at") is not None,
            )
        )
    return entries


def _validate_tag(tag: str) -> str:
    normalized = tag.strip().lower()
    if not _TAG_RE.fullmatch(normalized):
        raise ValueError(
            "Не получилось создать ссылку.\nТег должен быть от 3 до 24 символов и состоять из латинских букв, цифр или «_»."
        )
    return normalized


async def create_custom_tag(uid: int, tag: str) -> str:
    normalized = _validate_tag(tag)
    record = await dal.set_ref_custom_tag(uid, normalized)
    return str(record.get("custom_tag") or normalized)


async def request_payout(uid: int, *, amount_kop: int, details: Optional[dict] = None) -> PayoutRequest:
    details_payload: dict | None = details if isinstance(details, dict) else None
    amount_usdt: Optional[float] = None
    if details_payload is not None:
        raw_usdt = details_payload.get("amount_usdt")
        try:
            amount_usdt = float(raw_usdt)
        except (TypeError, ValueError):
            amount_usdt = None

    if amount_usdt is not None and amount_usdt < REF_WITHDRAW_MIN_USD:
        return PayoutRequest(
            amount_kop=amount_kop,
            net_amount_kop=0,
            fee_kop=0,
            accepted=False,
            reason="too_small",
        )

    if amount_usdt is None and amount_kop < REF_WITHDRAW_MIN_KOP:
        return PayoutRequest(
            amount_kop=amount_kop,
            net_amount_kop=0,
            fee_kop=0,
            accepted=False,
            reason="too_small",
        )

    info = await get_info(uid)
    if amount_kop > info["balance_kop"]:
        return PayoutRequest(
            amount_kop=amount_kop,
            net_amount_kop=0,
            fee_kop=0,
            accepted=False,
            reason="insufficient_funds",
        )

    fee_kop = math.floor(amount_kop * REF_WITHDRAW_FEE_PERCENT / 100)
    net_kop = max(amount_kop - fee_kop, 0)

    success = await dal.spend_ref_balance(uid, amount_kop=amount_kop)
    if not success:
        return PayoutRequest(
            amount_kop=amount_kop,
            net_amount_kop=0,
            fee_kop=0,
            accepted=False,
            reason="insufficient_funds",
        )

    await dal.add_payout(
        uid,
        amount_kop=amount_kop,
        status="waiting",
        details=details_payload,
    )
    return PayoutRequest(
        amount_kop=amount_kop,
        net_amount_kop=net_kop,
        fee_kop=fee_kop,
        accepted=True,
        reason=None,
    )


__all__ = [
    "RefInfo",
    "AwardResult",
    "ReferralDashboard",
    "ReferralEntry",
    "PayoutRequest",
    "calc_percent_by_paid",
    "next_tier_threshold",
    "ensure_profile",
    "get_info",
    "resolve_ref_code",
    "attach_referrer_by_code",
    "maybe_grant_invite_bonus",
    "record_paid_subscription",
    "record_refund",
    "get_dashboard",
    "list_recent_referrals",
    "create_custom_tag",
    "request_payout",
]
