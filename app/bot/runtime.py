from __future__ import annotations

from typing import Optional

from app.domain.quotas.service import QuotaService
from app.domain.checks.service import CheckerService
from app.domain.catalog_cache.service import AtiCodeCache
from app.domain.ati.service import AtiVerifier

_quota_service: QuotaService | None = None
_checker: CheckerService | None = None
_ati_code_cache: AtiCodeCache | None = None
_catalog_last_seen_mtime: float | None = None
_catalog_last_reload_mtime: float | None = None
_ati_verifier: AtiVerifier | None = None


def set_quota_service(service: QuotaService) -> None:
    global _quota_service
    _quota_service = service


def get_quota_service() -> QuotaService:
    if _quota_service is None:
        raise RuntimeError("QuotaService is not initialized")
    return _quota_service


def set_checker(service: CheckerService | None) -> None:
    global _checker
    _checker = service


def get_checker_or_none() -> CheckerService | None:
    return _checker


def set_ati_code_cache(cache: AtiCodeCache | None) -> None:
    global _ati_code_cache
    _ati_code_cache = cache


def get_ati_code_cache() -> Optional[AtiCodeCache]:
    return _ati_code_cache


def set_catalog_last_seen_mtime(value: float | None) -> None:
    global _catalog_last_seen_mtime
    _catalog_last_seen_mtime = value


def get_catalog_last_seen_mtime() -> float | None:
    return _catalog_last_seen_mtime


def set_catalog_last_reload_mtime(value: float | None) -> None:
    global _catalog_last_reload_mtime
    _catalog_last_reload_mtime = value


def get_catalog_last_reload_mtime() -> float | None:
    return _catalog_last_reload_mtime


def set_ati_verifier(verifier: AtiVerifier | None) -> None:
    global _ati_verifier
    _ati_verifier = verifier


def get_ati_verifier() -> AtiVerifier:
    if _ati_verifier is None:
        raise RuntimeError("AtiVerifier is not initialized")
    return _ati_verifier


__all__ = [
    "set_quota_service",
    "get_quota_service",
    "set_checker",
    "get_checker_or_none",
    "set_ati_code_cache",
    "get_ati_code_cache",
    "set_catalog_last_seen_mtime",
    "get_catalog_last_seen_mtime",
    "set_catalog_last_reload_mtime",
    "get_catalog_last_reload_mtime",
    "set_ati_verifier",
    "get_ati_verifier",
]
