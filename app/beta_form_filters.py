from __future__ import annotations

from aiogram.filters import Filter
from aiogram.types import CallbackQuery


class ConfirmFilter(Filter):
    def __init__(self, prefix: str) -> None:
        self.prefix = prefix

    async def __call__(self, query: CallbackQuery) -> bool:
        data = query.data or ""
        return data.startswith(self.prefix)
