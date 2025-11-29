from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import aiohttp

from app.config import YooKassaConfig


@dataclass
class YKCreateResult:
    payment_id: str
    confirmation_url: str
    status: str


@dataclass
class YKStatusResult:
    payment_id: str
    status: str
    metadata: dict[str, Any]


class YooKassaService:
    def __init__(self, cfg: YooKassaConfig) -> None:
        self.cfg = cfg

    async def create_payment(
        self,
        *,
        internal_payment_id: int,
        user_id: int,
        qty: int,
        price_rub: int,
        return_url: str | None = None,
    ) -> YKCreateResult:
        final_return_url = return_url or self.cfg.return_url
        payload = {
            "amount": {"value": f"{price_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": final_return_url,
            },
            "description": f"Антифрод: {qty} запросов",
            "metadata": {
                "internal_payment_id": internal_payment_id,
                "user_id": user_id,
                "package_qty": qty,
            },
        }
        headers = {
            "Idempotence-Key": str(uuid.uuid4()),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.cfg.api_base_url}/payments",
                json=payload,
                headers=headers,
                auth=aiohttp.BasicAuth(self.cfg.shop_id, self.cfg.secret_key),
            ) as resp:
                data = await resp.json()
                if resp.status >= 400:
                    raise RuntimeError(f"YooKassa create failed: {resp.status} {data}")
        confirmation = data.get("confirmation") or {}
        return YKCreateResult(
            payment_id=data["id"],
            confirmation_url=confirmation.get("confirmation_url") or "",
            status=data.get("status") or "pending",
        )

    async def fetch_status(self, payment_id: str) -> YKStatusResult:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.cfg.api_base_url}/payments/{payment_id}",
                auth=aiohttp.BasicAuth(self.cfg.shop_id, self.cfg.secret_key),
            ) as resp:
                data = await resp.json()
                if resp.status >= 400:
                    raise RuntimeError(f"YooKassa status failed: {resp.status} {data}")
        return YKStatusResult(
            payment_id=data["id"],
            status=data.get("status") or "pending",
            metadata=data.get("metadata") or {},
        )


__all__ = ["YooKassaService", "YKCreateResult", "YKStatusResult"]
