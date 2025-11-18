from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from app.config import COINMARKETCAP_API_KEY

logger = logging.getLogger(__name__)

_USDT_RUB_CACHE: Optional[float] = None
_USDT_RUB_UPDATED_AT: Optional[datetime] = None
_CACHE_TTL = timedelta(minutes=5)
_CMC_URL = "https://pro-api.coinmarketcap.com/v1/tools/price-conversion"


class RateError(RuntimeError):
    """Raised when the rate cannot be fetched."""


async def _fetch_usdt_rub_rate() -> float:
    api_key = COINMARKETCAP_API_KEY
    if not api_key:
        raise RateError("CoinMarketCap API key is not configured")

    params = {
        "amount": "1",
        "symbol": "USDT",
        "convert": "RUB",
    }
    headers = {
        "X-CMC_PRO_API_KEY": api_key,
    }
    timeout = aiohttp.ClientTimeout(total=30)
    connector = aiohttp.TCPConnector(limit=5)
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.get(_CMC_URL, params=params, headers=headers) as resp:
            if resp.status != 200:
                text = await resp.text()
                logger.error("CoinMarketCap error %s: %s", resp.status, text)
                raise RateError(f"CoinMarketCap responded with status {resp.status}")
            payload = await resp.json()
    try:
        quote = payload["data"]["quote"]["RUB"]["price"]
        rate = float(quote)
    except (KeyError, TypeError, ValueError) as exc:
        logger.exception("Failed to parse CoinMarketCap response: %s", payload)
        raise RateError("Invalid response from CoinMarketCap") from exc
    if rate <= 0:
        raise RateError("CoinMarketCap returned non-positive rate")
    return rate


async def get_usdt_rub_rate() -> float:
    """Return the USDT→RUB rate, cached for 10 minutes."""

    global _USDT_RUB_CACHE, _USDT_RUB_UPDATED_AT

    now = datetime.now(timezone.utc)
    if (
        _USDT_RUB_CACHE is not None
        and _USDT_RUB_UPDATED_AT is not None
        and now - _USDT_RUB_UPDATED_AT < _CACHE_TTL
    ):
        return _USDT_RUB_CACHE

    rate = await _fetch_usdt_rub_rate()
    _USDT_RUB_CACHE = rate
    _USDT_RUB_UPDATED_AT = now
    return rate


__all__ = ["get_usdt_rub_rate", "RateError"]
