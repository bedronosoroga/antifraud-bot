from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.domain.checks.loader import (
    BlacklistKind,
    DataCatalog,
    DataSource,
    clean_value,
)

Risk = Literal["none", "elevated", "critical"]


@dataclass(frozen=True)
class CheckResult:
    """Результат вычисления по одному коду АТИ."""

    ati: str
    lin_index: int
    exp_index: int
    risk: Risk


class CheckerService:
    """Высокоуровневый сервис проверки кодов АТИ."""

    def __init__(self, catalog: DataCatalog, lin_ok: int = 2, exp_ok: int = 5) -> None:
        self.catalog = catalog
        self.lin_ok = lin_ok
        self.exp_ok = exp_ok

    def refresh(self, catalog: DataCatalog) -> None:
        """Обновляет используемый каталог данных."""

        self.catalog = catalog

    def normalize_code(self, code: str) -> str:
        """Нормализует код АТИ, удаляя ведущие нули."""

        t = (code or "").strip()
        try:
            return str(int(t))
        except ValueError:
            return clean_value(t)

    def contains_code(self, source: DataSource, code: str) -> bool:
        """Проверяет, содержит ли источник указанный код."""

        df = source.df_norm
        if df.empty:
            return False
        try:
            return bool(df.eq(code).any().any())
        except Exception:
            return False

    def _calc_index(self, sources: list[DataSource], code: str) -> int:
        """Подсчитывает количество источников, содержащих код."""

        return sum(1 for source in sources if self.contains_code(source, code))

    def calc_lin_index(self, code: str) -> int:
        """Возвращает индекс перевозчика для кода."""

        return self._calc_index(self.catalog.carriers, code)

    def calc_exp_index(self, code: str) -> int:
        """Возвращает индекс экспедитора для кода."""

        return self._calc_index(self.catalog.forwarders, code)

    def find_risk(self, code: str) -> Risk:
        """Определяет уровень риска для кода по чёрным спискам."""

        elevated_found = False
        for source in self.catalog.blacklist:
            if not self.contains_code(source, code):
                continue
            kind: BlacklistKind | None = source.blacklist_kind
            if kind == "critical":
                return "critical"
            if kind == "elevated":
                elevated_found = True
        return "elevated" if elevated_found else "none"

    def check(self, code: str) -> CheckResult:
        """Выполняет полный расчёт индексов и риска для кода."""

        code_norm = self.normalize_code(code)
        risk = self.find_risk(code_norm)
        if risk != "none":
            return CheckResult(ati=code_norm, lin_index=0, exp_index=0, risk=risk)
        lin_index = self.calc_lin_index(code_norm)
        exp_index = self.calc_exp_index(code_norm)
        return CheckResult(ati=code_norm, lin_index=lin_index, exp_index=exp_index, risk="none")
