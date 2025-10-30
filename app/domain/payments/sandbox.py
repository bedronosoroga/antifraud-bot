from __future__ import annotations

from typing import Optional

from app.domain.payments import provider as pay


async def start_demo_checkout(
    uid: int,
    plan: str,
    *,
    metadata: Optional[dict] = None,
) -> pay.PaymentInit:
    """Create a pending sandbox payment and return its descriptor."""

    return await pay.create_payment(uid, plan, provider="sandbox", metadata=metadata or {})


async def simulate_success(payment_id: str) -> pay.ConfirmResult:
    """Confirm a sandbox payment (idempotent)."""

    return await pay.confirm_payment(payment_id)


async def simulate_failure(
    payment_id: str,
    *,
    reason: Optional[str] = None,
) -> pay.RejectResult:
    """Reject a sandbox payment (idempotent)."""

    return await pay.reject_payment(payment_id, reason=reason)


__all__ = [
    "start_demo_checkout",
    "simulate_success",
    "simulate_failure",
]
