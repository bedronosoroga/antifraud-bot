from __future__ import annotations

"""Helpers for selecting and building report texts based on check results."""

from app.domain.checks.service import CheckResult
from app import texts


def choose_report_type(res: CheckResult, lin_ok: int, exp_ok: int) -> str:
    """Return the report type code according to the provided thresholds."""

    if res.risk == "critical":
        return "D"
    if res.risk == "elevated":
        return "B"
    if res.lin_index == 0 and res.exp_index == 0:
        return "E"
    if res.lin_index >= lin_ok or res.exp_index >= exp_ok:
        return "A"
    return "C"


def build_report_text(ati: str, res: CheckResult, lin_ok: int, exp_ok: int) -> str:
    """Compose the final report text using templates from :mod:`app.texts`."""

    rtype = choose_report_type(res, lin_ok, exp_ok)
    if rtype == "D":
        return texts.report_d(ati, res.lin_index, res.exp_index)
    if rtype == "B":
        return texts.report_b(ati, res.lin_index, res.exp_index)
    if rtype == "E":
        return texts.report_e(ati)
    if rtype == "C":
        return texts.report_c(ati, res.lin_index, res.exp_index)

    tail = _build_tail_for_a(res, lin_ok, exp_ok)
    return texts.report_a(ati, res.lin_index, res.exp_index, tail=tail)


def _build_tail_for_a(res: CheckResult, lin_ok: int, exp_ok: int) -> str:
    """Generate the tail text for a successful type A report."""

    lin_ok_met = res.lin_index >= lin_ok
    exp_ok_met = res.exp_index >= exp_ok
    if lin_ok_met and not exp_ok_met:
        return (
            "Перевозка подтверждена; по экспедиции информации мало. "
            "Используйте эти показатели для оценки надёжности."
        )
    if exp_ok_met and not lin_ok_met:
        return (
            "Экспедиция подтверждена; по перевозке данных мало. "
            "Используйте эти показатели для оценки надёжности."
        )
    return (
        "Перевозка и экспедиция подтверждены. "
        "Используйте эти показатели для оценки надёжности."
    )
