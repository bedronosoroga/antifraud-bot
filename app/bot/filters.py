from __future__ import annotations

from typing import Any, Dict, Optional

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from app.config import ADMINS


class IsPrivate(BaseFilter):
    async def __call__(self, message: Message, *args: Any, **kwargs: Any) -> bool:
        chat = getattr(message, "chat", None)
        if chat is None:
            return False
        return getattr(chat, "type", None) == "private"


class IsAdmin(BaseFilter):
    async def __call__(
        self,
        event: Message | CallbackQuery,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        from_user = getattr(event, "from_user", None)
        if from_user is None:
            if isinstance(event, CallbackQuery):
                from_user = getattr(event.message, "from_user", None)
            if from_user is None:
                return False
        user_id = getattr(from_user, "id", None)
        if user_id is None:
            return False
        return user_id in ADMINS


class IsAtiDigits(BaseFilter):
    async def __call__(
        self,
        event: Message | CallbackQuery,
        *args: Any,
        **kwargs: Any,
    ) -> bool | Dict[str, Any]:
        if not isinstance(event, Message):
            return False
        text = event.text or ""
        digits = "".join(ch for ch in text if ch.isdigit())
        if 1 <= len(digits) <= 7:
            return {"ati_code_normalized": digits}
        return False


class IsCallbackPrefix(BaseFilter):
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def __call__(
        self,
        cq: CallbackQuery,
        *args: Any,
        **kwargs: Any,
    ) -> bool | Dict[str, Any]:
        data = cq.data
        if data is None:
            return False
        if data.startswith(self.prefix):
            return {"cbq_tail": data[len(self.prefix) :]}
        return False


__all__ = [
    "IsPrivate",
    "IsAdmin",
    "IsAtiDigits",
    "IsCallbackPrefix",
]
