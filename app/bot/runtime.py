from __future__ import annotations

from app.domain.quotas.service import QuotaService

_quota_service: QuotaService | None = None


def set_quota_service(service: QuotaService) -> None:
    global _quota_service
    _quota_service = service


def get_quota_service() -> QuotaService:
    if _quota_service is None:
        raise RuntimeError("QuotaService is not initialized")
    return _quota_service


__all__ = ["set_quota_service", "get_quota_service"]
