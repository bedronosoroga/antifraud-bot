from __future__ import annotations

import math
from typing import Literal, Optional, TypedDict

from app.config import PLANS, REF_TIERS, REF_WITHDRAW_MIN_KOP
from app.core import db as dal

PlanName = Literal["p20", "p50", "unlim"]


class RefInfo(TypedDict):
    code: str
    referred_by: Optional[int]
    paid_count: int
    tier: int
    percent: int
    balance_kop: int
    next_tier_at: Optional[int]


class AwardResult(TypedDict):
    sponsor_uid: Optional[int]
    percent: int
    amount_kop: int
    awarded_kop: int


class SpendResult(TypedDict):
    plan: str
    price_kop: int
    covered_kop: int
    to_pay_kop: int
    success: bool


class PayoutRequest(TypedDict):
    amount_kop: int
    accepted: bool
    reason: Optional[str]


def calc_percent_by_paid(paid_count: int) -> tuple[int, int]:
    tier_index = 0
    percent = REF_TIERS[0]["percent"]
    for idx, tier in enumerate(REF_TIERS):
        if paid_count >= tier["min_paid"]:
            tier_index = idx
            percent = tier["percent"]
        else:
            break
    return tier_index, percent


def next_tier_threshold(paid_count: int) -> Optional[int]:
    for tier in REF_TIERS:
        if paid_count < tier["min_paid"]:
            return tier["min_paid"]
    return None


def decode_ref_code(code: str) -> Optional[int]:
    stripped = code.strip().lower()
    if not stripped:
        return None
    try:
        value = int(stripped, 36)
    except ValueError:
        return None
    return value if value >= 0 else None


def _build_ref_info(data: dict[str, object]) -> RefInfo:
    paid_count = int(data.get("paid_count", 0))
    balance_kop = int(data.get("balance_kop", 0))
    tier = int(data.get("tier", 0))
    percent = int(data.get("percent", 0))
    return RefInfo(
        code=str(data.get("code", "")),
        referred_by=data.get("referred_by"),
        paid_count=paid_count,
        tier=tier,
        percent=percent,
        balance_kop=balance_kop,
        next_tier_at=next_tier_threshold(paid_count),
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


async def attach_referrer_by_code(uid: int, code: str) -> bool:
    sponsor_uid = decode_ref_code(code)
    if sponsor_uid is None or sponsor_uid == uid:
        return False

    await ensure_profile(sponsor_uid)

    record = await dal.get_ref(uid)
    if record is None:
        record = await dal.ensure_ref(uid, referred_by=sponsor_uid)
        return record.get("referred_by") == sponsor_uid

    if record.get("referred_by") is not None:
        return False

    record = await dal.ensure_ref(uid, referred_by=sponsor_uid)
    return record.get("referred_by") == sponsor_uid


async def record_paid_subscription(payer_uid: int, *, amount_kop: int) -> AwardResult:
    if amount_kop <= 0:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    payer_info = await ensure_profile(payer_uid)
    sponsor_uid = payer_info.get("referred_by")

    if sponsor_uid is None or sponsor_uid == payer_uid:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    sponsor_info = await ensure_profile(int(sponsor_uid))
    _, percent = calc_percent_by_paid(sponsor_info["paid_count"])
    commission_kop = math.floor(amount_kop * percent / 100)

    updated = await dal.update_ref_stats(
        sponsor_uid,
        paid_increment=1,
        balance_delta_kop=commission_kop,
    )

    new_tier, new_percent = calc_percent_by_paid(int(updated["paid_count"]))
    await dal.set_ref_tier(sponsor_uid, tier=new_tier, percent=new_percent)

    return AwardResult(
        sponsor_uid=sponsor_uid,
        percent=percent,
        amount_kop=amount_kop,
        awarded_kop=commission_kop,
    )


async def record_refund(payer_uid: int, *, amount_kop: int) -> AwardResult:
    if amount_kop <= 0:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    payer_info = await get_info(payer_uid)
    sponsor_uid = payer_info.get("referred_by")

    if sponsor_uid is None or sponsor_uid == payer_uid:
        return AwardResult(sponsor_uid=None, percent=0, amount_kop=amount_kop, awarded_kop=0)

    sponsor_info = await get_info(int(sponsor_uid))
    _, percent = calc_percent_by_paid(sponsor_info["paid_count"])
    refund_kop = math.floor(amount_kop * percent / 100)
    available = sponsor_info["balance_kop"]
    to_deduct = min(refund_kop, available)

    if to_deduct > 0:
        updated = await dal.update_ref_stats(
            sponsor_uid,
            paid_increment=0,
            balance_delta_kop=-to_deduct,
        )
        new_tier, new_percent = calc_percent_by_paid(int(updated["paid_count"]))
        await dal.set_ref_tier(sponsor_uid, tier=new_tier, percent=new_percent)

    return AwardResult(
        sponsor_uid=sponsor_uid,
        percent=percent,
        amount_kop=amount_kop,
        awarded_kop=-to_deduct,
    )


async def apply_balance_to_plan(uid: int, plan: PlanName) -> SpendResult:
    if plan not in PLANS:
        raise ValueError(f"unknown plan '{plan}'")

    price_kop = int(PLANS[plan]["price_kop"])
    info = await get_info(uid)
    balance = info["balance_kop"]
    covered_kop = min(balance, price_kop)

    if covered_kop > 0:
        success = await dal.spend_ref_balance(uid, amount_kop=covered_kop)
        if not success:
            return SpendResult(
                plan=plan,
                price_kop=price_kop,
                covered_kop=0,
                to_pay_kop=price_kop,
                success=False,
            )
    else:
        return SpendResult(
            plan=plan,
            price_kop=price_kop,
            covered_kop=0,
            to_pay_kop=price_kop,
            success=True,
        )

    return SpendResult(
        plan=plan,
        price_kop=price_kop,
        covered_kop=covered_kop,
        to_pay_kop=price_kop - covered_kop,
        success=True,
    )


async def request_payout(uid: int, *, amount_kop: int) -> PayoutRequest:
    if amount_kop < REF_WITHDRAW_MIN_KOP:
        return PayoutRequest(amount_kop=amount_kop, accepted=False, reason="too_small")

    info = await get_info(uid)
    if amount_kop > info["balance_kop"]:
        return PayoutRequest(amount_kop=amount_kop, accepted=False, reason="insufficient_funds")

    success = await dal.spend_ref_balance(uid, amount_kop=amount_kop)
    if not success:
        return PayoutRequest(amount_kop=amount_kop, accepted=False, reason="insufficient_funds")

    await dal.add_payout(uid, amount_kop=amount_kop, status="waiting")
    return PayoutRequest(amount_kop=amount_kop, accepted=True, reason=None)


__all__ = [
    "RefInfo",
    "AwardResult",
    "SpendResult",
    "PayoutRequest",
    "calc_percent_by_paid",
    "next_tier_threshold",
    "decode_ref_code",
    "ensure_profile",
    "get_info",
    "attach_referrer_by_code",
    "record_paid_subscription",
    "record_refund",
    "apply_balance_to_plan",
    "request_payout",
]
