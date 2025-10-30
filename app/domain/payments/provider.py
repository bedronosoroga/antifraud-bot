from __future__ import annotations

from typing import Literal, Optional, TypedDict

from app.config import PAYMENTS_ACTIVE_PROVIDER, PLANS
from app.core import db as dal
from app.domain.referrals import service as refs
from app.domain.subs import service as subs

PlanName = Literal["p20", "p50", "unlim"]
PaymentStatus = Literal["waiting", "confirmed", "rejected"]


class PaymentInit(TypedDict):
    payment_id: str
    uid: int
    plan: PlanName
    amount_kop: int
    status: PaymentStatus
    provider: str
    provider_invoice_id: Optional[str]
    metadata: dict


class ConfirmResult(TypedDict):
    ok: bool
    payment_id: str
    status_was: PaymentStatus
    status_now: PaymentStatus
    activated_plan: Optional[str]
    referral_award_kop: int
    need_company_ati_capture: bool
    reason: Optional[str]


class RejectResult(TypedDict):
    ok: bool
    payment_id: str
    status_was: PaymentStatus
    status_now: PaymentStatus
    reason: Optional[str]


def is_sandbox_provider(provider: Optional[str]) -> bool:
    """Return True if the provided provider (or active provider) is sandbox."""

    if provider is None:
        provider = PAYMENTS_ACTIVE_PROVIDER
    return provider == "sandbox"


async def create_payment(
    uid: int,
    plan: PlanName,
    *,
    provider: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> PaymentInit:
    if plan not in PLANS:
        raise ValueError(f"unknown plan '{plan}'")

    provider_name = provider or PAYMENTS_ACTIVE_PROVIDER
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault("provider", provider_name)

    price_kop = int(PLANS[plan]["price_kop"])
    payload = await dal.create_pending_payment(
        uid,
        plan=plan,
        amount_kop=price_kop,
        provider_invoice_id=None,
        metadata=payload_metadata,
    )

    return PaymentInit(
        payment_id=payload["id"],
        uid=uid,
        plan=plan,
        amount_kop=price_kop,
        status=payload["status"],
        provider=provider_name,
        provider_invoice_id=payload.get("provider_invoice_id"),
        metadata=payload.get("metadata") or {},
    )


async def confirm_payment(payment_id: str) -> ConfirmResult:
    payment = await dal.get_payment(payment_id)
    if payment is None:
        return ConfirmResult(
            ok=False,
            payment_id=payment_id,
            status_was="waiting",
            status_now="waiting",
            activated_plan=None,
            referral_award_kop=0,
            need_company_ati_capture=False,
            reason="not-found",
        )

    status_was: PaymentStatus = payment["status"]
    uid = payment["uid"]
    plan: PlanName = payment["plan"]
    amount_kop = payment["amount_kop"]

    if status_was == "rejected":
        return ConfirmResult(
            ok=False,
            payment_id=payment_id,
            status_was=status_was,
            status_now="rejected",
            activated_plan=None,
            referral_award_kop=0,
            need_company_ati_capture=False,
            reason="already-rejected",
        )

    if status_was == "confirmed":
        return ConfirmResult(
            ok=True,
            payment_id=payment_id,
            status_was=status_was,
            status_now="confirmed",
            activated_plan=None,
            referral_award_kop=0,
            need_company_ati_capture=False,
            reason=None,
        )

    await dal.mark_payment_status(uid, payment_id, status="confirmed")
    await subs.purchase(uid, plan)
    award = await refs.record_paid_subscription(uid, amount_kop=amount_kop)

    confirmed_count = await dal.count_confirmed_payments(uid)
    user = await dal.get_user(uid)
    company_ati = user.get("company_ati") if user else None
    need_capture = confirmed_count == 1 and company_ati is None

    return ConfirmResult(
        ok=True,
        payment_id=payment_id,
        status_was=status_was,
        status_now="confirmed",
        activated_plan=plan,
        referral_award_kop=int(award.get("awarded_kop", 0)),
        need_company_ati_capture=need_capture,
        reason=None,
    )


async def reject_payment(payment_id: str, *, reason: Optional[str] = None) -> RejectResult:
    payment = await dal.get_payment(payment_id)
    if payment is None:
        return RejectResult(
            ok=False,
            payment_id=payment_id,
            status_was="waiting",
            status_now="waiting",
            reason="not-found",
        )

    status_was: PaymentStatus = payment["status"]
    uid = payment["uid"]

    if status_was == "confirmed":
        return RejectResult(
            ok=False,
            payment_id=payment_id,
            status_was=status_was,
            status_now="confirmed",
            reason="already-confirmed",
        )

    if status_was == "rejected":
        return RejectResult(
            ok=True,
            payment_id=payment_id,
            status_was=status_was,
            status_now="rejected",
            reason=None,
        )

    await dal.mark_payment_status(uid, payment_id, status="rejected")
    return RejectResult(
        ok=True,
        payment_id=payment_id,
        status_was=status_was,
        status_now="rejected",
        reason=reason,
    )


__all__ = [
    "PlanName",
    "PaymentStatus",
    "PaymentInit",
    "ConfirmResult",
    "RejectResult",
    "create_payment",
    "is_sandbox_provider",
    "confirm_payment",
    "reject_payment",
]
