from __future__ import annotations

from datetime import datetime
from typing import Literal, NamedTuple

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.types import Message

from app import texts
from app.keyboards import kb_after_report, kb_main
from app.domain.checks.service import CheckerService
from app.domain.checks.formatter import build_report_text, choose_report_type
from app.domain.onboarding import free as free_dal
from app.domain.subs import service as subs_service
from app.config import cfg
from app.core import db as dal


router = Router(name="numeric")


class _QuotaRuntime:
    free: free_dal.FreeService | None = None
    subs = subs_service


_quota = _QuotaRuntime()


def init_quota_runtime(*, free: free_dal.FreeService | None, subs: object | None) -> None:
    """Вызывается из main при сборке DI-контейнера."""

    _quota.free = free
    if subs is not None:
        _quota.subs = subs


class ConsumeResult(NamedTuple):
    allowed: bool
    source: Literal["admin", "free", "sub", "none"]
    reason: str | None
    subs_status: subs_service.SubInfo | None


async def _resolve_and_consume(user_id: int, now: datetime) -> ConsumeResult:
    # Админы проходят всегда, ничего не списываем
    if user_id in cfg.admin_ids:
        return ConsumeResult(True, "admin", None, None)

    # 1) Бесплатные 5 на 3 дня
    if _quota.free is not None:
        await _quota.free.ensure_pack(user_id, now)
        ok, _reason = await _quota.free.can_consume(user_id, now)
        if ok:
            await _quota.free.consume_one(user_id, now)
            return ConsumeResult(True, "free", None, None)

    # 2) Подписка
    if _quota.subs is not None:
        ok_result = await _quota.subs.can_consume(uid=user_id, now_ts=now.timestamp())
        ok = ok_result.get("ok", False)
        reason = ok_result.get("reason")
        if ok:
            await _quota.subs.consume(user_id, now_ts=now.timestamp())
            status_after = await _quota.subs.get_status(user_id, now_ts=now.timestamp())
            return ConsumeResult(True, "sub", None, status_after)
        status = await _quota.subs.get_status(user_id, now_ts=now.timestamp())
        return ConsumeResult(False, "none", reason, status)

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


@router.message(StateFilter(None), F.text.regexp(r"^\d{1,7}$"))
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
    cons = await _resolve_and_consume(user_id=from_user.id, now=now)
    if not cons.allowed:
        await message.answer(texts.paywall_no_checks(), reply_markup=kb_main())
        return

    try:
        raw = (message.text or "").strip()
        code = _runtime.checker.normalize_code(raw)
        res = _runtime.checker.check(code)
        report_type = choose_report_type(res, _runtime.lin_ok, _runtime.exp_ok)
        await dal.append_history(
            from_user.id,
            ati=res.ati,
            ts=now.timestamp(),
            lin=res.lin_index,
            exp=res.exp_index,
            risk=res.risk,
            report_type=report_type,
        )
        report = build_report_text(code, res, _runtime.lin_ok, _runtime.exp_ok)
        await message.answer(report, reply_markup=kb_after_report())
    except Exception:
        # не раскрываем деталей пользователю
        await message.answer(
            "Не удалось выполнить проверку. Попробуйте ещё раз.",
            reply_markup=kb_main(),
        )
