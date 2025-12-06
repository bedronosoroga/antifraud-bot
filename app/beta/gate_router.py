from __future__ import annotations

import os
from aiogram import Router
from aiogram.filters import CommandStart, BaseFilter
from aiogram.types import Message

from app.beta.whitelist import is_whitelisted

router = Router(name="beta_gate")


def _beta_only_enabled() -> bool:
    return os.getenv("BETA_ONLY", "").lower() in ("1", "true", "yes", "on")


class BetaBlockStart(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        if not _beta_only_enabled():
            return False
        uid = message.from_user.id if message.from_user else None
        if uid is None:
            return False
        return not is_whitelisted(uid)


@router.message(CommandStart(), BetaBlockStart())
async def gate_start(_: Message) -> None:
    # если не в белом списке — просто молчим (никаких ответов)
    return
