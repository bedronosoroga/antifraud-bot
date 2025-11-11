from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app import texts
from app.bot import runtime as bot_runtime
from app.config import cfg
from app.core import db as dal
from app.core import rate_limit
from app.domain.checks.formatter import build_report_text, choose_report_type
from app.domain.checks.service import CheckerService
from app.domain.quotas.service import InsufficientQuotaError
from app.keyboards import kb_after_report, kb_menu

router = Router(name="numeric")


class _Runtime:
    checker: CheckerService | None = None
    lin_ok: int = 2
    exp_ok: int = 5


_runtime = _Runtime()


def init_checks_runtime(checker: CheckerService, lin_ok: int = 2, exp_ok: int = 5) -> None:
    _runtime.checker = checker
    _runtime.lin_ok = int(lin_ok)
    _runtime.exp_ok = int(exp_ok)


async def _not_ready_reply(message: Message) -> None:
    await message.answer(
        "Сервис проверок сейчас недоступен. Попробуйте чуть позже.",
        reply_markup=kb_menu(),
    )


@router.message(StateFilter(None), F.text.regexp(r"^\d{1,7}$"))
async def on_ati_code(message: Message, state: FSMContext) -> None:
    if _runtime.checker is None:
        await _not_ready_reply(message)
        return

    from_user = message.from_user
    if from_user is None:
        await message.answer(texts.err_need_digits_upto_7(), reply_markup=kb_menu())
        return

    data = await state.get_data()
    if data.get("input_mode") not in (None, "none"):
        # Сейчас ждём другой ввод (настройки/вывод и т.п.) — пропускаем
        return

    uid = from_user.id
    now = datetime.now(timezone.utc)

    limiter = await rate_limit.check_and_hit(uid, "checks:run", now=now)
    if not limiter["allowed"]:
        await message.answer(texts.too_many_requests())
        return

    if uid in cfg.admin_ids:
        allowed = True
    else:
        quota = bot_runtime.get_quota_service()
        try:
            await quota.consume(uid, now=now)
            allowed = True
        except InsufficientQuotaError:
            allowed = False

    if not allowed:
        await message.answer(texts.request_limit_text(), reply_markup=kb_menu())
        return

    try:
        raw = (message.text or "").strip()
        code = _runtime.checker.normalize_code(raw)
        res = _runtime.checker.check(code)
        report_type = choose_report_type(res, _runtime.lin_ok, _runtime.exp_ok)
        await dal.append_history(
            uid,
            ati=res.ati,
            ts=now,
            lin=res.lin_index,
            exp=res.exp_index,
            risk=res.risk,
            report_type=report_type,
        )
        report = build_report_text(code, res, _runtime.lin_ok, _runtime.exp_ok)
        await message.answer(report, reply_markup=kb_after_report())
    except Exception:
        await message.answer(
            "Не удалось выполнить проверку. Попробуйте ещё раз.",
            reply_markup=kb_menu(),
        )
