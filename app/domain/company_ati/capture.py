from __future__ import annotations

import re
from typing import Optional, TypedDict

from app.core import db as dal

ATI_RE = re.compile(r"^[0-9]{1,7}$")


class CaptureCheck(TypedDict):
    should_ask: bool
    reason: Optional[str]


class SetAtiResult(TypedDict):
    ok: bool
    code: Optional[str]
    reason: Optional[str]


class NormalizeResult(TypedDict):
    code: Optional[str]
    raw: str


def normalize_from_text(text: str) -> NormalizeResult:
    digits = "".join(ch for ch in text if ch.isdigit())
    code = digits if 1 <= len(digits) <= 7 else None
    return NormalizeResult(code=code, raw=text)


async def should_ask_after_first_payment(uid: int) -> CaptureCheck:
    user = await dal.get_user(uid)
    company_ati = user.get("company_ati") if user else None

    if company_ati is not None:
        return CaptureCheck(should_ask=False, reason="already-has-ati")

    payments_count = await dal.count_confirmed_payments(uid)
    if payments_count == 0:
        return CaptureCheck(should_ask=False, reason="no-payments-yet")
    if payments_count != 1:
        return CaptureCheck(should_ask=False, reason="not-first-payment")

    return CaptureCheck(should_ask=True, reason=None)


async def get_current(uid: int) -> Optional[str]:
    user = await dal.get_user(uid)
    return user.get("company_ati") if user else None


async def set_company_ati(uid: int, code: str) -> SetAtiResult:
    if not ATI_RE.fullmatch(code):
        return SetAtiResult(ok=False, code=None, reason="invalid-format")

    current = await get_current(uid)
    if current is not None:
        return SetAtiResult(ok=False, code=current, reason="already-set")

    await dal.set_company_ati(uid, code)
    return SetAtiResult(ok=True, code=code, reason=None)


__all__ = [
    "ATI_RE",
    "CaptureCheck",
    "SetAtiResult",
    "NormalizeResult",
    "normalize_from_text",
    "should_ask_after_first_payment",
    "get_current",
    "set_company_ati",
]
