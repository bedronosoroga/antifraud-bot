from __future__ import annotations

from typing import Iterable, Set

from app.domain.checks.loader import DataCatalog, DataSource

__all__ = ["AtiCodeCache"]


def _normalize_code(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    try:
        return str(int(text))
    except ValueError:
        return text


class AtiCodeCache:
    """In-memory cache of normalized ATI codes from the Excel catalog."""

    def __init__(self) -> None:
        self._codes: Set[str] = set()

    @staticmethod
    def _sources(catalog: DataCatalog) -> Iterable[DataSource]:
        yield from catalog.carriers
        yield from catalog.forwarders
        yield from catalog.blacklist

    def refresh_from_catalog(self, catalog: DataCatalog) -> None:
        codes: Set[str] = set()
        for source in self._sources(catalog):
            df = getattr(source, "df_norm", None)
            if df is None or df.empty:
                continue
            for value in df.values.flatten():
                code = _normalize_code(value)
                if code:
                    codes.add(code)
        self._codes = codes

    def has(self, code: str) -> bool:
        normalized = _normalize_code(code)
        if not normalized:
            return False
        return normalized in self._codes

    def size(self) -> int:
        return len(self._codes)
