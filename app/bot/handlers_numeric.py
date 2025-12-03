from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from aiogram.exceptions import TelegramBadRequest

from app import texts
from app.bot import runtime as bot_runtime
from app.config import cfg
from app.core import db as dal
from app.core import rate_limit
from app.domain.checks.formatter import build_report_text, choose_report_type
from app.domain.checks.service import CheckerService
from app.domain.quotas.service import InsufficientQuotaError
from app.keyboards import kb_after_report, kb_menu, kb_request_no_balance, kb_request_has_balance
from app.bot.state import NAV_STACK_KEY, REPORT_HAS_BALANCE_KEY
from app.domain.ati.service import AtiCheckResult

logger = logging.getLogger(__name__)

router = Router(name="numeric")


_LIN_OK = 2
_EXP_OK = 5

REPORT_SCREEN = "report"


def init_checks_runtime(checker: CheckerService | None, lin_ok: int = 2, exp_ok: int = 5) -> None:
    global _LIN_OK, _EXP_OK
    _LIN_OK = int(lin_ok)
    _EXP_OK = int(exp_ok)
    bot_runtime.set_checker(checker)


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


async def _edit_message(message_obj: Message, text: str, keyboard) -> None:
    try:
        await message_obj.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        await message_obj.answer(text, reply_markup=keyboard)


@router.message(StateFilter(None), F.text.regexp(r"^\d{1,7}$"))
async def on_ati_code(message: Message, state: FSMContext) -> None:
    checker = bot_runtime.get_checker_or_none()
    if checker is None:
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

    logger.info("on_ati_code start uid=%s raw=%s", uid, message.text)

    try:
        raw_input = (message.text or "").strip()
        spinner = await message.answer(texts.ati_checking_text(raw_input))
        code = checker.normalize_code(raw_input)
        since_dt = now - timedelta(days=3)
        recent = False
        try:
            recent = await dal.was_checked_recently(uid, code, since_dt)
        except Exception:
            logger.exception("failed to check recent history for uid=%s code=%s", uid, code)
        logger.info("recent_check uid=%s code=%s recent=%s", uid, code, recent)
    except Exception:
        logger.exception("failed before ATI/checker uid=%s raw=%s", uid, message.text)
        await message.answer("Не удалось выполнить проверку. Попробуйте позже.", reply_markup=kb_menu())
        return

    quota_service = bot_runtime.get_quota_service()
    is_admin = uid in cfg.admin_ids
    remaining_balance: Optional[int]
    if is_admin:
        remaining_balance = None
    else:
        quota_state = await quota_service.get_state(uid)
        if quota_state.balance <= 0 and not recent:
            await message.answer(texts.request_limit_text(), reply_markup=kb_request_no_balance())
            return
        remaining_balance = quota_state.balance
    has_balance_flag = (remaining_balance is None) or (remaining_balance > 0) or recent

    cache = bot_runtime.get_ati_code_cache()
    verifier = bot_runtime.get_ati_verifier()
    skip_ati = cache.has(code) if cache else False
    ati_result = AtiCheckResult(status="ok")
    if not skip_ati:
        try:
            ati_result = await verifier.verify_code(code)
        except Exception:
            logger.exception("ATI verification failed for code %s", code)
            ati_result = AtiCheckResult(status="error")
    logger.info("ati_result uid=%s code=%s status=%s", uid, code, ati_result.status)

    if ati_result.status == "not_found":
        keyboard = kb_request_has_balance() if has_balance_flag else kb_request_no_balance()
        await _edit_message(spinner, texts.ati_invalid_code_text(code), keyboard)
        logger.info("ati_result not_found uid=%s code=%s", uid, code)
        return

    if ati_result.status == "error":
        keyboard = kb_request_has_balance() if has_balance_flag else kb_request_no_balance()
        await _edit_message(spinner, texts.ati_no_data_or_error_text(code), keyboard)
        logger.info("ati_result error uid=%s code=%s", uid, code)
        return

    try:
        if not is_admin and not recent:
            try:
                quota_state = await quota_service.consume(uid, now=now)
            except InsufficientQuotaError:
                await _edit_message(spinner, texts.request_limit_text(), kb_request_no_balance())
                return
            remaining_balance = quota_state.balance
        logger.info("checker.check uid=%s code=%s", uid, code)
        res = checker.check(code)
        logger.info("checker done uid=%s code=%s lin=%s exp=%s risk=%s", uid, code, res.lin_index, res.exp_index, res.risk)
        report_type = choose_report_type(res, _LIN_OK, _EXP_OK)
        await dal.append_history(
            uid,
            ati=res.ati,
            ts=now,
            lin=res.lin_index,
            exp=res.exp_index,
            risk=res.risk,
            report_type=report_type,
        )
        report = build_report_text(code, res, _LIN_OK, _EXP_OK)
        await _edit_message(spinner, report, None)
        has_balance = (remaining_balance is None) or (remaining_balance > 0) or recent
        actions_keyboard = kb_after_report(has_balance=has_balance)
        await message.answer(texts.report_actions_text(), reply_markup=actions_keyboard)
        await state.update_data({REPORT_HAS_BALANCE_KEY: has_balance})
        await _activate_report_screen(state)
        logger.info("on_ati_code success uid=%s code=%s", uid, code)
    except Exception:
        logger.exception("failed to process ati code %s for uid %s", code, uid)
        await _edit_message(spinner, "Не удалось выполнить проверку. Попробуйте ещё раз.", kb_menu())
