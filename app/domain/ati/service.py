from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, date
from typing import Literal, Optional

import aiohttp

from app.config import AtiConfig
from app.core import db as dal

logger = logging.getLogger(__name__)

AtiStatus = Literal["ok", "not_found", "error"]


@dataclass(slots=True)
class AtiCheckResult:
    status: AtiStatus
    canonical_ati_id: Optional[str] = None
    reason: Optional[str] = None


class AtiVerifier:
    ERROR_CACHE_TTL = timedelta(minutes=5)
    DAILY_LIMIT = 5000
    RPS_INTERVAL = 0.11  # ~9 requests/sec

    def __init__(self, cfg: AtiConfig) -> None:
        self.cfg = cfg
        self.tokens = [token for token in cfg.tokens if token]
        self._token_state: dict[str, dict[str, object]] = {
            token: {
                "date": date.today(),
                "count": 0,
                "last_request": 0.0,
            }
            for token in self.tokens
        }
        self._token_locks: dict[str, asyncio.Lock] = {token: asyncio.Lock() for token in self.tokens}

    async def verify_code(self, ati_id: str) -> AtiCheckResult:
        normalized = ati_id.strip()
        now = datetime.now(timezone.utc)
        cached = await dal.get_ati_cache(normalized)
        if cached:
            status = cached["status"]
            checked_at: datetime = cached["checked_at"]
            age = now - checked_at
            if status == "error":
                if age < self.ERROR_CACHE_TTL:
                    return AtiCheckResult(status="error")
            elif age < timedelta(hours=self.cfg.cache_ttl_hours):
                if status == "ok":
                    return AtiCheckResult(status="ok", canonical_ati_id=cached.get("canonical_ati_id"))
                if status == "not_found":
                    return AtiCheckResult(status="not_found")

        if not self.tokens:
            return AtiCheckResult(status="error")

        result = await self._query_with_tokens(normalized)
        try:
            if result.status == "ok":
                await dal.upsert_ati_cache(normalized, status="ok", checked_at=now, canonical_ati_id=result.canonical_ati_id)
            elif result.status == "not_found":
                await dal.upsert_ati_cache(normalized, status="not_found", checked_at=now)
            else:
                await dal.upsert_ati_cache(normalized, status="error", checked_at=now)
        except Exception:
            logger.exception("Failed to update ATI cache for %s", normalized)
        return result

    async def _query_with_tokens(self, ati_id: str) -> AtiCheckResult:
        last_error: Optional[AtiCheckResult] = None
        for token in self.tokens:
            lock = self._token_locks[token]
            async with lock:
                if not self._can_use_token(token):
                    continue
                result = await self._call_single(token, ati_id)
                if result.status == "error":
                    last_error = result
                    continue
                return result
        return last_error or AtiCheckResult(status="error")

    def _can_use_token(self, token: str) -> bool:
        state = self._token_state.setdefault(
            token,
            {"date": date.today(), "count": 0, "last_request": 0.0},
        )
        today = date.today()
        token_date: date = state["date"]  # type: ignore[assignment]
        if token_date != today:
            state["date"] = today
            state["count"] = 0
        count = state["count"]  # type: ignore[assignment]
        return count < self.DAILY_LIMIT

    async def _call_single(self, token: str, ati_id: str) -> AtiCheckResult:
        state = self._token_state[token]
        now = time.monotonic()
        last_request: float = state["last_request"]  # type: ignore[assignment]
        delay = self.RPS_INTERVAL - (now - last_request)
        if delay > 0:
            await asyncio.sleep(delay)
        state["last_request"] = time.monotonic()
        timeout = aiohttp.ClientTimeout(total=self.cfg.request_timeout_sec)
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        url = f"{self.cfg.base_url.rstrip('/')}/v1.0/firms/summary/{ati_id}"
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    state["count"] = state.get("count", 0) + 1  # type: ignore[assignment]
                    if resp.status == 200:
                        text = await resp.text()
                        text_stripped = text.strip()
                        if text_stripped.lower() == "null":
                            return AtiCheckResult(status="not_found", reason="null")
                        try:
                            payload = json.loads(text)
                        except json.JSONDecodeError:
                            logger.warning("ATI returned invalid JSON for %s", ati_id)
                            return AtiCheckResult(status="error")
                        data = payload.get("data")
                        if data is None and isinstance(payload, dict):
                            data = payload
                        if not isinstance(data, dict):
                            return AtiCheckResult(status="error")
                        canonical = data.get("ati_id")
                        if canonical is None:
                            canonical = data.get("atiId")
                        if canonical is None:
                            logger.warning("ATI response for %s lacks ati_id field", ati_id)
                            return AtiCheckResult(status="error")
                        canonical_str = str(canonical).strip()
                        if not canonical_str:
                            logger.warning("ATI response for %s has empty ati_id", ati_id)
                            return AtiCheckResult(status="error")
                        if canonical_str != ati_id:
                            logger.info("ATI reported code %s moved to %s", ati_id, canonical_str)
                            return AtiCheckResult(
                                status="not_found",
                                canonical_ati_id=canonical_str,
                                reason="moved",
                            )
                        return AtiCheckResult(status="ok", canonical_ati_id=canonical_str)
                    if resp.status in (401, 403, 429):
                        logger.warning("ATI token %s rejected with status %s", token[:4] + "...", resp.status)
                        return AtiCheckResult(status="error")
                    if 500 <= resp.status < 600:
                        return AtiCheckResult(status="error")
                    return AtiCheckResult(status="error")
        except asyncio.TimeoutError:
            logger.warning("ATI request timed out for code %s", ati_id)
            return AtiCheckResult(status="error")
        except aiohttp.ClientError:
            logger.exception("ATI client error for code %s", ati_id)
            return AtiCheckResult(status="error")


__all__ = ["AtiVerifier", "AtiCheckResult"]
