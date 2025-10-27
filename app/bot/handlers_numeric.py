from __future__ import annotations

from datetime import datetime
from typing import Literal, NamedTuple

from aiogram import Router, F
from aiogram.types import Message

from app import texts
from app.bot.keyboards import kb_after_report, kb_main
from app.domain.checks.service import CheckerService
from app.domain.checks.formatter import build_report_text
from app.domain.onboarding.free import FreeService
from app.domain.subs.service import SubsService, SubsStatus
from app.config import cfg


numeric_router = Router(name="numeric")


class _QuotaRuntime:
    free: FreeService | None = None
    subs: SubsService | None = None


_quota = _QuotaRuntime()


def init_quota_runtime(*, free: FreeService | None, subs: SubsService | None) -> None:
    """Вызывается из main при сборке DI-контейнера."""

    _quota.free = free
    _quota.subs = subs


class ConsumeResult(NamedTuple):
    allowed: bool
    source: Literal["admin", "free", "sub", "none"]
    reason: str | None
    subs_status: SubsStatus | None


def _resolve_and_consume(user_id: int, now: datetime) -> ConsumeResult:
    # Админы проходят всегда, ничего не списываем
    if user_id in cfg.admin_ids:
        return ConsumeResult(True, "admin", None, None)

    # 1) Бесплатные 5 на 3 дня
    if _quota.free is not None:
        ok, _reason = _quota.free.can_consume(user_id, now)
        if ok:
            _quota.free.consume_one(user_id, now)
            return ConsumeResult(True, "free", None, None)

    # 2) Подписка
    if _quota.subs is not None:
        ok, reason = _quota.subs.can_consume(user_id, now)
        if ok:
            status_after = _quota.subs.consume_one(user_id, now)
            return ConsumeResult(True, "sub", None, status_after)
        status = _quota.subs.get_status(user_id, now)
        return ConsumeResult(False, "none", status.reason, status)

    # 3) Сервисов нет — запрещаем (без «заглушек», чтобы не было «бесплатного пролива»)
    return ConsumeResult(False, "none", "нет активной подписки", None)


class _Runtime:
    checker: CheckerService | None = None
    lin_ok: int = 2
    exp_ok: int = 5


_runtime = _Runtime()


def init_checks_runtime(checker: CheckerService, lin_ok: int = 2, exp_ok: int = 5) -> None:
    """
    Вызывается при старте бота (в main.py) после загрузки каталога.
    Делает модуль готовым к обработке кодов.
    """
    _runtime.checker = checker
    _runtime.lin_ok = int(lin_ok)
    _runtime.exp_ok = int(exp_ok)


async def _not_ready_reply(message: Message) -> None:
    """Отправляет пользователю сообщение о недоступности сервиса."""
    # Используем простую подсказку и клавиатуру меню
    await message.answer(
        "Сервис проверок сейчас недоступен. Попробуйте чуть позже.",
        reply_markup=kb_main(),
    )


@numeric_router.message(F.text.regexp(r"^\d{1,7}$"))
async def on_ati_code(message: Message) -> None:
    """
    Ловим любой текст из 1–7 цифр: это код АТИ.
    Пайплайн:
      1) Проверяем, что runtime инициализирован.
      2) normalize_code -> check (service)
      3) build_report_text (formatter) c порогами из runtime
      4) ответ с kb_after_report()
    При ошибках — мягкий фолбэк на kb_main().
    """
    if _runtime.checker is None:
        await _not_ready_reply(message)
        return

    from_user = message.from_user
    if from_user is None:
        await message.answer(
            "Не удалось выполнить проверку. Попробуйте ещё раз.",
            reply_markup=kb_main(),
        )
        return

    now = datetime.now()
    cons = _resolve_and_consume(user_id=from_user.id, now=now)
    if not cons.allowed:
        await message.answer(texts.paywall_no_checks())
        return

    try:
        raw = (message.text or "").strip()
        code = _runtime.checker.normalize_code(raw)
        res = _runtime.checker.check(code)
        report = build_report_text(code, res, _runtime.lin_ok, _runtime.exp_ok)
        await message.answer(report, reply_markup=kb_after_report())
    except Exception:
        # не раскрываем деталей пользователю
        await message.answer(
            "Не удалось выполнить проверку. Попробуйте ещё раз.",
            reply_markup=kb_main(),
        )
