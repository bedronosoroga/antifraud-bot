from __future__ import annotations

from typing import Literal, Optional, TypedDict

from app.config import PAYMENTS_ACTIVE_PROVIDER, REQUEST_PACKAGES, RequestPackage
from app.core import db as dal
from app.domain.quotas.service import QuotaService
from app.domain.referrals import service as refs

PaymentStatus = Literal["waiting", "confirmed", "rejected"]


class PaymentInit(TypedDict):
    payment_id: str
    uid: int
    package_code: str
    amount_kop: int
    status: PaymentStatus
    provider: str
    provider_invoice_id: Optional[str]
    metadata: dict


class ConfirmResult(TypedDict, total=False):
    ok: bool
    payment_id: str
    status_was: PaymentStatus
    status_now: PaymentStatus
    package_code: Optional[str]
    granted_requests: int
    referral_award_kop: int
    second_line_awarded_kop: int
    need_company_ati_capture: bool
    reason: Optional[str]


class RejectResult(TypedDict):
    ok: bool
    payment_id: str
    status_was: PaymentStatus
    status_now: PaymentStatus
    reason: Optional[str]


_PACKAGE_MAP = {f"pkg{pkg.qty}": pkg for pkg in REQUEST_PACKAGES}
_quota: QuotaService | None = None


def init_payment_runtime(*, quota: QuotaService) -> None:
    global _quota
    _quota = quota


def is_sandbox_provider(provider: Optional[str]) -> bool:
    if provider is None:
        provider = PAYMENTS_ACTIVE_PROVIDER
    return provider == "sandbox"


def _ensure_package(code: str) -> RequestPackage:
    package = _PACKAGE_MAP.get(code)
    if package is None:
        raise ValueError(f"unknown package '{code}'")
    return package


async def create_payment(
    uid: int,
    package_code: str,
    *,
    provider: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> PaymentInit:
    package = _ensure_package(package_code)
    provider_name = provider or PAYMENTS_ACTIVE_PROVIDER
    payload_metadata = dict(metadata or {})
    payload_metadata.setdefault("provider", provider_name)
    payload_metadata.setdefault("package_code", package_code)

    payment = await dal.create_pending_payment(
        uid,
        plan=package_code,
        amount_kop=package.price_rub * 100,
        provider_invoice_id=None,
        metadata=payload_metadata,
    )

    return PaymentInit(
        payment_id=payment["id"],
        uid=uid,
        package_code=package_code,
        amount_kop=package.price_rub * 100,
        status=payment["status"],
        provider=provider_name,
        provider_invoice_id=payment.get("provider_invoice_id"),
        metadata=payment.get("metadata") or {},
    )


async def confirm_payment(payment_id: str) -> ConfirmResult:
    payment = await dal.get_payment(payment_id)
    if payment is None:
        return ConfirmResult(
            ok=False,
            payment_id=payment_id,
            status_was="waiting",
            status_now="waiting",
            package_code=None,
            granted_requests=0,
            referral_award_kop=0,
            second_line_awarded_kop=0,
            need_company_ati_capture=False,
            reason="not-found",
        )

    status_was: PaymentStatus = payment["status"]
    uid = payment["uid"]
    package_code = payment["plan"]

    if status_was == "rejected":
        return ConfirmResult(
            ok=False,
            payment_id=payment_id,
            status_was=status_was,
            status_now="rejected",
            package_code=package_code,
            granted_requests=0,
            referral_award_kop=0,
            second_line_awarded_kop=0,
            need_company_ati_capture=False,
            reason="already-rejected",
        )

    if status_was == "confirmed":
        return ConfirmResult(
            ok=True,
            payment_id=payment_id,
            status_was=status_was,
            status_now="confirmed",
            package_code=package_code,
            granted_requests=0,
            referral_award_kop=0,
            second_line_awarded_kop=0,
            need_company_ati_capture=False,
            reason="duplicate",
        )

    package = _PACKAGE_MAP.get(package_code)
    if package is None:
        return ConfirmResult(
            ok=False,
            payment_id=payment_id,
            status_was=status_was,
            status_now=status_was,
            package_code=package_code,
            granted_requests=0,
            referral_award_kop=0,
            second_line_awarded_kop=0,
            need_company_ati_capture=False,
            reason="unknown-package",
        )

    if _quota is None:
        raise RuntimeError("quota service is not initialized for payments")

    await dal.mark_payment_status(uid, payment_id, status="confirmed")
    await _quota.add(uid, package.qty, source="purchase", metadata={"payment_id": payment_id})

    award = await refs.record_paid_subscription(uid, amount_kop=payment["amount_kop"])

    confirmed_count = await dal.count_confirmed_payments(uid)
    user = await dal.get_user(uid)
    company_ati = user.get("company_ati") if user else None
    need_capture = confirmed_count == 1 and company_ati is None

    return ConfirmResult(
        ok=True,
        payment_id=payment_id,
        status_was=status_was,
        status_now="confirmed",
        package_code=package_code,
        granted_requests=package.qty,
        referral_award_kop=int(award.get("awarded_kop", 0)),
        second_line_awarded_kop=int(award.get("second_line_awarded_kop", 0)),
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
    "PaymentInit",
    "ConfirmResult",
    "RejectResult",
    "create_payment",
    "confirm_payment",
    "reject_payment",
    "is_sandbox_provider",
    "init_payment_runtime",
]
