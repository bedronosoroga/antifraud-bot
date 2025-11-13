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
from app.keyboards import kb_after_report, kb_menu, kb_request_no_balance
from app.bot.state import NAV_STACK_KEY, REPORT_HAS_BALANCE_KEY

router = Router(name="numeric")


class _Runtime:
    checker: CheckerService | None = None
    lin_ok: int = 2
    exp_ok: int = 5


_runtime = _Runtime()

REPORT_SCREEN = "report"


def init_checks_runtime(checker: CheckerService, lin_ok: int = 2, exp_ok: int = 5) -> None:
    _runtime.checker = checker
    _runtime.lin_ok = int(lin_ok)
    _runtime.exp_ok = int(exp_ok)


async def _not_ready_reply(message: Message) -> None:
    await message.answer(
        "Сервис проверок сейчас недоступен. Попробуйте чуть позже.",
        reply_markup=kb_menu(),
    )


async def _get_nav_stack(state: FSMContext) -> list[str]:
    data = await state.get_data()
    stack = data.get(NAV_STACK_KEY)
    if not stack:
        stack = ["menu"]
    return stack


async def _set_nav_stack(state: FSMContext, stack: list[str]) -> None:
    await state.update_data({NAV_STACK_KEY: stack})


async def _activate_report_screen(state: FSMContext) -> None:
    stack = await _get_nav_stack(state)
    if stack[-1] == REPORT_SCREEN:
        return
    stack.append(REPORT_SCREEN)
    await _set_nav_stack(state, stack)


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

    remaining_balance: int | None = None
    if uid in cfg.admin_ids:
        allowed = True
        remaining_balance = 1
    else:
        quota = bot_runtime.get_quota_service()
        try:
            quota_state = await quota.consume(uid, now=now)
            allowed = True
            remaining_balance = quota_state.balance
        except InsufficientQuotaError:
            allowed = False

    if not allowed:
        await message.answer(texts.request_limit_text(), reply_markup=kb_request_no_balance())
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
        await message.answer(report)
        has_balance = (remaining_balance is None) or (remaining_balance > 0)
        actions_keyboard = kb_after_report(has_balance=has_balance)
        await message.answer(texts.report_actions_text(), reply_markup=actions_keyboard)
        await state.update_data({REPORT_HAS_BALANCE_KEY: has_balance})
        await _activate_report_screen(state)
    except Exception:
        await message.answer(
            "Не удалось выполнить проверку. Попробуйте ещё раз.",
            reply_markup=kb_menu(),
        )
