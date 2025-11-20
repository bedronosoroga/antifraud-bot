from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from zoneinfo import ZoneInfo
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import texts
from app.bot import runtime as bot_runtime
from app.config import REQUEST_PACKAGES, RequestPackage, REF_WITHDRAW_MIN_USD, cfg
from app.core import db as dal
from app.domain.payments import sandbox as sandbox_pay
from app.domain.referrals import service as referral_service
from app.domain.rates import service as rates_service
from app.domain.onboarding.free import FreeService
from app.domain.quotas.service import InsufficientQuotaError
from app.domain.b2b import service as b2b_service
from app.keyboards import (
    kb_free_info,
    kb_history,
    kb_after_report,
    kb_method_page1,
    kb_method_page2,
    kb_method_page3,
    kb_menu,
    kb_payment_confirm,
    kb_payment_error,
    kb_payment_methods,
    kb_payment_pending,
    kb_payment_success,
    kb_packages,
    kb_profile,
    kb_request_has_balance,
    kb_request_no_balance,
    kb_referral_main,
    kb_single_back,
    kb_support,
    kb_b2b_ati_main,
    kb_b2b_ati_lead_back,
    kb_b2b_ati_after_lead,
)
from app.bot.state import NAV_STACK_KEY, REPORT_HAS_BALANCE_KEY

router = Router(name="public")
MSK_TZ = ZoneInfo(cfg.tz or "Europe/Moscow")


class _OnboardingRuntime:
    free: FreeService | None = None


_onboarding = _OnboardingRuntime()

INPUT_MODE_KEY = "input_mode"
HISTORY_PAGE_KEY = "hist_page"
HISTORY_MASK_KEY = "hist_mask"
HISTORY_ORIGIN_KEY = "hist_origin"
WITHDRAW_DATA_KEY = "withdraw_data"
METHOD_PAGE_KEY = "method_page"

INPUT_NONE = "none"
INPUT_PROFILE_ATI = "profile:code:edit"
INPUT_REF_TAG = "ref:tag:create"
INPUT_WITHDRAW_AMOUNT = "ref:withdraw:amount"
INPUT_WITHDRAW_DETAILS = "ref:withdraw:details"
INPUT_B2B_ATI_LEAD = "b2b:ati:lead"

PACKAGE_MAP = {f"pkg{pkg.qty}": pkg for pkg in REQUEST_PACKAGES}
PACKAGE_BY_QTY = {pkg.qty: pkg for pkg in REQUEST_PACKAGES}
B2B_LEAD_SOURCE = "profile_b2b_button"


def _get_quota_service():
    return bot_runtime.get_quota_service()


def init_onboarding_runtime(*, free: FreeService | None) -> None:
    _onboarding.free = free


class _InputModeActive(Filter):
    def __init__(self, active: bool = True) -> None:
        self.active = active

    async def __call__(self, message: Message, state: FSMContext) -> bool:  # type: ignore[override]
        data = await state.get_data()
        mode = data.get(INPUT_MODE_KEY, INPUT_NONE)
        is_active = mode not in (None, INPUT_NONE)
        return is_active if self.active else not is_active


async def _answer(target: Message | CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    if isinstance(target, CallbackQuery):
        await target.answer()
        try:
            await target.message.edit_text(text, reply_markup=keyboard)
        except TelegramBadRequest:
            await target.message.answer(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)


async def _get_nav_stack(state: FSMContext) -> list[str]:
    data = await state.get_data()
    stack = data.get(NAV_STACK_KEY)
    if not stack:
        stack = ["menu"]
    return stack


async def _set_nav_stack(state: FSMContext, stack: list[str]) -> None:
    await state.update_data({NAV_STACK_KEY: stack})


async def _push_screen(state: FSMContext, screen: str) -> None:
    stack = await _get_nav_stack(state)
    if stack[-1] != screen:
        stack.append(screen)
        await _set_nav_stack(state, stack)


async def _replace_screen(state: FSMContext, screen: str) -> None:
    stack = await _get_nav_stack(state)
    stack[-1] = screen
    await _set_nav_stack(state, stack)


async def _pop_screen(state: FSMContext) -> str:
    stack = await _get_nav_stack(state)
    if len(stack) > 1:
        stack.pop()
        await _set_nav_stack(state, stack)
        return stack[-1]
    await _reset_nav(state)
    return "menu"


async def _reset_nav(state: FSMContext) -> None:
    await _set_nav_stack(state, ["menu"])


async def _set_input_mode(state: FSMContext, mode: str) -> None:
    await state.update_data({INPUT_MODE_KEY: mode})


async def _get_input_mode(state: FSMContext) -> str:
    data = await state.get_data()
    return data.get(INPUT_MODE_KEY, INPUT_NONE)


async def _current_screen(state: FSMContext) -> str:
    stack = await _get_nav_stack(state)
    return stack[-1]


def _format_msk(dt: datetime) -> str:
    aware = dt.astimezone(MSK_TZ)
    return aware.strftime("%d.%m.%y %H:%M")


def _start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 Показать все возможные команды", callback_data="menu:open")]
        ]
    )


def _get_package(code: str) -> RequestPackage:
    pkg = PACKAGE_MAP.get(code)
    if pkg is None:
        raise ValueError(f"unknown package '{code}'")
    return pkg


def _get_package_by_qty(qty: int) -> RequestPackage:
    pkg = PACKAGE_BY_QTY.get(qty)
    if pkg is None:
        raise ValueError(f"unknown package qty '{qty}'")
    return pkg


def _package_code_from_qty(qty: int) -> str:
    return f"pkg{qty}"


async def _get_bot_username(target: Message | CallbackQuery, state: FSMContext) -> str:
    data = await state.get_data()
    cached = data.get("bot_username")
    if cached:
        return cached
    bot = target.bot if isinstance(target, (Message, CallbackQuery)) else None
    if bot is None:
        return "antifraud_bot"
    me = await bot.me()
    username = me.username or "antifraud_bot"
    await state.update_data({"bot_username": username})
    return username


async def _show_menu(target: Message | CallbackQuery, state: FSMContext, *, replace: bool = False) -> None:
    text = texts.menu_help_text()
    keyboard = kb_menu()
    if replace:
        await _replace_screen(state, "menu")
    else:
        await _push_screen(state, "menu")
    await _answer(target, text, keyboard)


def _user_id(target: Message | CallbackQuery) -> Optional[int]:
    user = target.from_user
    return user.id if user else None


async def _show_request(target: Message | CallbackQuery, state: FSMContext, *, replace: bool = False) -> None:
    uid = _user_id(target)
    if uid is None:
        return
    quota_service = _get_quota_service()
    quota = await quota_service.get_state(uid)
    if replace:
        await _replace_screen(state, "request")
    else:
        await _push_screen(state, "request")

    if quota.balance > 0:
        text = texts.request_prompt_text(quota.balance)
        keyboard = kb_request_has_balance()
    else:
        text = texts.request_limit_text()
        keyboard = kb_request_no_balance()
    await _answer(target, text, keyboard)


async def _show_free_info(target: Message | CallbackQuery, state: FSMContext) -> None:
    await _push_screen(state, "free-info")
    await _answer(target, texts.free_requests_info(), kb_free_info())


async def _show_support(target: Message | CallbackQuery, state: FSMContext) -> None:
    await _push_screen(state, "support")
    await _answer(target, texts.support_text(), kb_support())


def _method_page_content(page: int) -> tuple[str, InlineKeyboardMarkup]:
    if page == 1:
        return texts.method_page1_text(), kb_method_page1()
    if page == 2:
        return texts.method_page2_text(), kb_method_page2()
    if page == 3:
        return texts.method_page3_text(), kb_method_page3()
    raise ValueError("invalid method page")


async def _show_method_page(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    page: int,
    replace: bool = False,
) -> None:
    text, keyboard = _method_page_content(page)
    if replace:
        await _replace_screen(state, "method")
    else:
        await _push_screen(state, "method")
    await state.update_data({METHOD_PAGE_KEY: page})
    await _answer(target, text, keyboard)


async def _show_report_actions(target: Message | CallbackQuery, state: FSMContext, *, replace: bool = False) -> None:
    data = await state.get_data()
    has_balance = bool(data.get(REPORT_HAS_BALANCE_KEY, True))
    keyboard = kb_after_report(has_balance=has_balance)
    if replace:
        await _replace_screen(state, "report")
    else:
        await _push_screen(state, "report")
    await _answer(target, texts.report_actions_text(), keyboard)


async def _show_b2b_ati(target: Message | CallbackQuery, state: FSMContext, *, replace: bool = False) -> None:
    await _set_input_mode(state, INPUT_NONE)
    if replace:
        await _replace_screen(state, "b2b")
    else:
        await _push_screen(state, "b2b")
    await _answer(target, texts.b2b_ati_intro_text(), kb_b2b_ati_main())


async def _show_payment_packages(target: Message | CallbackQuery, state: FSMContext, *, replace: bool = False) -> None:
    uid = _user_id(target)
    if uid is None:
        return
    quota = await _get_quota_service().get_state(uid)
    if replace:
        await _replace_screen(state, "buy")
    else:
        await _push_screen(state, "buy")
    await state.update_data(
        {
            "buy_package_qty": None,
            "buy_package_code": None,
            "buy_package_price": None,
            "buy_payment_id": None,
        }
    )
    await _answer(target, texts.payment_packages_intro(quota.balance), kb_packages())


async def _show_payment_methods_screen(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    replace: bool,
) -> bool:
    data = await state.get_data()
    if not data.get("buy_package_code"):
        return False
    if replace:
        await _replace_screen(state, "buy")
    else:
        await _push_screen(state, "buy")
    await _answer(target, texts.payment_method_text(), kb_payment_methods())
    return True


async def _show_payment_pending(target: Message | CallbackQuery, state: FSMContext, payment_id: str) -> None:
    await state.update_data({"buy_payment_id": payment_id})
    await _replace_screen(state, "buy-pending")
    await _answer(target, texts.payment_pending_text(), kb_payment_pending(payment_id))


async def _handle_payment_cancel(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    payment_id = data.get("buy_payment_id")
    if payment_id:
        try:
            await sandbox_pay.simulate_failure(payment_id, reason="cancel")
        except Exception:
            logging.exception("failed to mark payment %s as cancelled", payment_id)
    await state.update_data({"buy_payment_id": None})
    await _replace_screen(state, "buy-failure")
    text = texts.payment_error_text("cancel")
    await _answer(query, text, kb_payment_error(payment_id or "0"))


async def _show_profile(target: Message | CallbackQuery, state: FSMContext, *, replace: bool = False) -> None:
    uid = _user_id(target)
    if uid is None:
        return
    user = await dal.get_user(uid)
    quota = await _get_quota_service().get_state(uid)
    history_total = await dal.count_history(uid)
    created_at = user.get("created_at") if user else None
    registered = _format_msk(created_at) if isinstance(created_at, datetime) else "—"
    since_phrase = _since_phrase(created_at) if isinstance(created_at, datetime) else "—"
    company_ati = user.get("company_ati") if user else None
    text = texts.profile_text(
        tg_id=uid,
        registered_at=registered,
        since_phrase=since_phrase,
        balance=quota.balance,
        company_ati=company_ati,
        has_history=history_total > 0,
    )
    if replace:
        await _replace_screen(state, "profile")
    else:
        await _push_screen(state, "profile")
    await _answer(target, text, kb_profile())


def _since_phrase(created_at: datetime) -> str:
    now = datetime.now(timezone.utc)
    delta = now - created_at
    days = delta.days
    months = days // 30
    rem_days = days % 30
    parts = []
    if months > 0:
        parts.append(f"{months} мес.")
    if rem_days > 0:
        parts.append(f"{rem_days} дн.")
    return "с нами: " + (" " .join(parts) if parts else "меньше дня")


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    from_user = message.from_user
    is_new_user = False
    if from_user is not None:
        uid = from_user.id
        try:
            record = await dal.get_user(uid)
            is_new_user = record is None
        except Exception:
            logging.exception("failed to read user before /start for %s", uid)
            is_new_user = False
        try:
            await dal.ensure_user(
                from_user.id,
                from_user.username,
                from_user.first_name,
                from_user.last_name,
            )
        except Exception:
            logging.exception("ensure_user failed for /start")
        await _handle_start_referral(uid, message.text or "")
        await _ensure_free_pack(uid)

    await state.clear()
    await _reset_nav(state)
    await _set_input_mode(state, INPUT_NONE)

    if is_new_user:
        hero_msg = await message.answer(texts.hero_banner())
        try:
            await hero_msg.pin(disable_notification=True)
        except TelegramBadRequest:
            pass
        except Exception:
            logging.exception("failed to pin hero message")
        await message.answer(texts.start_onboarding_message(), reply_markup=_start_keyboard())
        return

    await _show_menu(message, state, replace=True)


async def _handle_start_referral(uid: int, payload: str) -> None:
    if not payload:
        return
    parts = payload.split(maxsplit=1)
    arg = parts[1] if len(parts) > 1 else ""
    if not arg:
        return
    code = arg
    if code.lower().startswith("ref_"):
        code = code[4:]
    try:
        attached = await referral_service.attach_referrer_by_code(uid, code)
        if attached:
            sponsor = await referral_service.maybe_grant_invite_bonus(uid)
            if sponsor:
                await _get_quota_service().add(sponsor, 1, source="referral-invite", metadata={"invited": uid})
    except Exception:
        logging.exception("failed to handle referral start for user %s", uid)


async def _ensure_free_pack(uid: int) -> None:
    if _onboarding.free is None:
        return
    now = datetime.now(timezone.utc)
    try:
        existing = await dal.get_free_grant(uid)
    except Exception:
        existing = None
    try:
        await _onboarding.free.ensure_pack(uid, now)
    except Exception:
        logging.exception("failed to ensure free grant for user %s", uid)
        return
    if existing is None:
        await _grant_signup_bonus(uid)


async def _grant_signup_bonus(uid: int) -> None:
    quota_service = _get_quota_service()
    try:
        account = await dal.get_quota_account(uid)
    except Exception:
        logging.exception("failed to read quota account for user %s", uid)
        return
    if account is not None:
        return
    try:
        await quota_service.add(uid, 3, source="signup")
    except Exception:
        logging.exception("failed to grant signup bonus for user %s", uid)


@router.callback_query(F.data == "menu:open")
async def on_menu(query: CallbackQuery, state: FSMContext) -> None:
    await _show_menu(query, state, replace=True)


@router.callback_query(F.data == "nav:back")
async def on_nav_back(query: CallbackQuery, state: FSMContext) -> None:
    current = await _current_screen(state)
    if current == "buy-pending":
        await _handle_payment_cancel(query, state)
        return
    if current == "buy-failure":
        await _set_input_mode(state, INPUT_NONE)
        restored = await _show_payment_methods_screen(query, state, replace=True)
        if not restored:
            await _show_payment_packages(query, state, replace=True)
        return
    await _set_input_mode(state, INPUT_NONE)
    screen = await _pop_screen(state)
    await _show_screen_by_id(query, state, screen, replace=True)


@router.callback_query(F.data == "nav:menu")
async def on_nav_menu(query: CallbackQuery, state: FSMContext) -> None:
    await _reset_nav(state)
    await _set_input_mode(state, INPUT_NONE)
    await _show_menu(query, state, replace=True)


async def _show_screen_by_id(
    target: Message | CallbackQuery,
    state: FSMContext,
    screen: str,
    *,
    replace: bool = False,
) -> None:
    if screen == "menu":
        await _show_menu(target, state, replace=replace)
        return
    if screen == "request":
        await _show_request(target, state, replace=replace)
        return
    if screen == "profile":
        await _show_profile(target, state, replace=replace)
        return
    if screen == "b2b":
        await _show_b2b_ati(target, state, replace=replace)
        return
    if screen == "buy":
        await _show_payment_packages(target, state, replace=replace)
        return
    if screen in {"buy-success", "buy-failure", "buy-pending"}:
        await _show_menu(target, state, replace=True)
        return
    if screen == "free-info":
        await _show_free_info(target, state)
        return
    if screen == "support":
        await _show_support(target, state)
        return
    if screen == "method":
        data = await state.get_data()
        page = int(data.get(METHOD_PAGE_KEY, 1) or 1)
        await _show_method_page(target, state, page=page, replace=replace)
        return
    if screen == "history":
        data = await state.get_data()
        page = data.get(HISTORY_PAGE_KEY, 1)
        await show_history(target, state, page=page, replace=replace)
        return
    if screen == "referral":
        await show_referral(target, state, replace=replace)
        return
    if screen == "report":
        await _show_report_actions(target, state, replace=replace)
        return
    await _show_menu(target, state, replace=True)


# Additional handlers for request, history, profile, payments, referrals, support will follow...


@router.callback_query(F.data == "req:open")
async def on_request_open(query: CallbackQuery, state: FSMContext) -> None:
    replace = await _current_screen(state) == "report"
    await _show_request(query, state, replace=replace)


@router.callback_query(F.data == "hist:open")
async def on_history_open(query: CallbackQuery, state: FSMContext) -> None:
    stack = await _get_nav_stack(state)
    origin = stack[-1] if stack else "menu"
    await state.update_data({HISTORY_ORIGIN_KEY: origin})
    await show_history(query, state, page=1, replace=True)


@router.callback_query(F.data.startswith("hist:page:"))
async def on_history_page(query: CallbackQuery, state: FSMContext) -> None:
    try:
        page = int(query.data.split(":")[-1])
    except ValueError:
        page = 1
    if page < 1:
        page = 1
    await show_history(query, state, page=page, replace=True)


@router.callback_query(F.data.in_({"hist:mask:on", "hist:mask:off"}))
async def on_history_mask(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    page = data.get(HISTORY_PAGE_KEY, 1)
    masked = query.data.endswith("on")
    await state.update_data({HISTORY_MASK_KEY: masked})
    await show_history(query, state, page=page, replace=True)


@router.callback_query(F.data == "hist:menu")
async def on_history_menu(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    origin = data.get(HISTORY_ORIGIN_KEY, "menu")
    await _set_nav_stack(state, [origin])
    await _show_screen_by_id(query, state, origin, replace=True)


async def show_history(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    page: int,
    replace: bool,
) -> None:
    uid = _user_id(target)
    if uid is None:
        return
    limit = 5
    total = await dal.count_history(uid)
    data = await state.get_data()
    masked = data.get(HISTORY_MASK_KEY, False)
    if total == 0:
        if replace:
            await _replace_screen(state, "history")
        else:
            await _push_screen(state, "history")
        await state.update_data({HISTORY_PAGE_KEY: 1})
        await _answer(target, texts.history_empty_text(), kb_single_back("hist:menu"))
        return

    max_page = max(1, (total + limit - 1) // limit)
    page = min(page, max_page)
    offset = (page - 1) * limit
    rows = await dal.get_history(uid, limit=limit, offset=offset)
    entries: list[str] = []
    for row in rows:
        ts = row.get("ts")
        ts_str = _format_msk(ts) if isinstance(ts, datetime) else ""
        entries.append(
            texts.format_history_entry(
                ati=row.get("ati", ""),
                ts_str=ts_str,
                lin=int(row.get("lin", 0)),
                exp=int(row.get("exp", 0)),
                risk=row.get("risk", "none"),
                report_type=row.get("report_type", "C"),
                masked=masked,
            )
        )
    body = texts.history_title(page) + "\n\n" + "\n\n".join(entries)
    has_prev = page > 1
    has_next = page * limit < total
    keyboard = kb_history(page=page, has_prev=has_prev, has_next=has_next, masked=masked)
    if replace:
        await _replace_screen(state, "history")
    else:
        await _push_screen(state, "history")
    await state.update_data({HISTORY_PAGE_KEY: page, HISTORY_MASK_KEY: masked})
    await _answer(target, body, keyboard)


@router.callback_query(F.data == "profile:open")
async def on_profile_open(query: CallbackQuery, state: FSMContext) -> None:
    await _show_profile(query, state, replace=False)


@router.callback_query(F.data == "profile:code:edit")
async def on_profile_code_edit(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    user = await dal.get_user(query.from_user.id) if query.from_user else None
    current = user.get("company_ati") if user else None
    await _set_input_mode(state, INPUT_PROFILE_ATI)
    await _answer(query, texts.profile_code_prompt(current), kb_single_back())


@router.callback_query(F.data == "method:open")
async def on_method_open(query: CallbackQuery, state: FSMContext) -> None:
    await _show_method_page(query, state, page=1, replace=False)


@router.callback_query(F.data.startswith("meth:page:"))
async def on_method_page(query: CallbackQuery, state: FSMContext) -> None:
    token = query.data.split(":")[-1]
    try:
        page = int(token)
        text, keyboard = _method_page_content(page)
    except (ValueError, TypeError):
        await query.answer("Неверная страница", show_alert=True)
        return
    await state.update_data({METHOD_PAGE_KEY: page})
    try:
        await query.message.edit_text(text, reply_markup=keyboard)
    except TelegramBadRequest:
        await query.message.answer(text, reply_markup=keyboard)
    await query.answer()


@router.callback_query(F.data == "ref:freeinfo")
async def on_free_info(query: CallbackQuery, state: FSMContext) -> None:
    await _show_free_info(query, state)


@router.callback_query(F.data == "support:open")
async def on_support(query: CallbackQuery, state: FSMContext) -> None:
    await _show_support(query, state)


@router.callback_query(F.data == "ref:open")
async def on_referral_open(query: CallbackQuery, state: FSMContext) -> None:
    await show_referral(query, state, replace=False)


@router.callback_query(F.data == "ref:list")
async def on_referral_list(query: CallbackQuery, state: FSMContext) -> None:
    uid = _user_id(query)
    if uid is None:
        return
    entries = await referral_service.list_recent_referrals(uid, limit=10)
    await _push_screen(state, "referral:list")
    await _answer(query, texts.referrals_list_text(entries), kb_single_back())


@router.callback_query(F.data == "ref:tag")
async def on_referral_tag(query: CallbackQuery, state: FSMContext) -> None:
    await _push_screen(state, "referral:tag")
    await _set_input_mode(state, INPUT_REF_TAG)
    await _answer(query, texts.ref_create_tag_text(), kb_single_back("ref:open"))


@router.callback_query(F.data == "ref:withdraw")
async def on_referral_withdraw(query: CallbackQuery, state: FSMContext) -> None:
    uid = _user_id(query)
    if uid is None:
        return
    info = await referral_service.get_info(uid)
    await _push_screen(state, "referral:withdraw")
    await _set_input_mode(state, INPUT_WITHDRAW_AMOUNT)
    payload: dict[str, Any] = {}
    try:
        rate = await rates_service.get_usdt_rub_rate()
    except Exception:
        logging.exception("failed to fetch usdt/rub rate")
    else:
        payload["rate"] = rate
        payload["rate_ts"] = datetime.now(timezone.utc).timestamp()
    await state.update_data({WITHDRAW_DATA_KEY: payload})
    await _answer(
        query,
        texts.ref_withdraw_text(balance_kop=info["balance_kop"]),
        kb_single_back("ref:open"),
    )


async def show_referral(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    replace: bool,
) -> None:
    uid = _user_id(target)
    if uid is None:
        return
    dashboard = await referral_service.get_dashboard(uid, now=datetime.now(timezone.utc))
    info = dashboard["info"]
    slug = info.get("custom_tag") or info.get("code")
    bot_username = await _get_bot_username(target, state)
    link = f"https://t.me/{bot_username}?start={slug}"
    text = texts.ref_program_text(
        link=link,
        balance_kop=info.get("balance_kop", 0),
        total_earned_kop=info.get("total_earned_kop", 0),
        direct_total=dashboard["direct_total"],
        direct_paid=dashboard["direct_paid"],
        second_total=dashboard["second_total"],
        second_paid=dashboard["second_paid"],
        today_direct=dashboard["today_direct"],
        percent=info.get("percent", 0),
        next_tier_at=info.get("next_tier_at"),
    )
    if replace:
        await _replace_screen(state, "referral")
    else:
        await _push_screen(state, "referral")
    await _answer(target, text, kb_referral_main(link))


@router.callback_query(F.data == "b2b:open")
async def on_b2b_open(query: CallbackQuery, state: FSMContext) -> None:
    await _show_b2b_ati(query, state, replace=False)


@router.callback_query(F.data == "b2b:lead")
async def on_b2b_lead(query: CallbackQuery, state: FSMContext) -> None:
    await _set_input_mode(state, INPUT_B2B_ATI_LEAD)
    await _answer(query, texts.b2b_ati_lead_prompt_text(), kb_b2b_ati_lead_back())


@router.message(_InputModeActive())
async def on_text_input(message: Message, state: FSMContext) -> None:
    mode = await _get_input_mode(state)
    if mode == INPUT_PROFILE_ATI:
        await _handle_profile_code_input(message, state)
        return
    if mode == INPUT_REF_TAG:
        await _handle_ref_tag_input(message, state)
        return
    if mode == INPUT_WITHDRAW_AMOUNT:
        await _handle_withdraw_amount_input(message, state)
        return
    if mode == INPUT_WITHDRAW_DETAILS:
        await _handle_withdraw_details_input(message, state)
        return
    if mode == INPUT_B2B_ATI_LEAD:
        await _handle_b2b_lead_input(message, state)
        return


@router.message(CommandStart())
async def _noop_start_forward(_: Message, state: FSMContext) -> None:
    # /start обрабатывается отдельным хэндлером, этот нужен чтобы не падал generic
    await state.update_data({})


@router.message(
    _InputModeActive(active=False),
    F.text,
    ~F.text.startswith("/"),
    ~F.text.regexp(r"^\d{1,7}$"),
)
async def on_text_generic(message: Message, state: FSMContext) -> None:
    await message.answer(texts.err_need_digits_upto_7(), reply_markup=kb_menu())


async def _handle_profile_code_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    raw = (message.text or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits or len(digits) > 7:
        await message.answer(texts.err_need_digits_upto_7())
        return
    try:
        await dal.set_company_ati(uid, digits)
    except Exception:
        logging.exception("failed to set company ATI for user %s", uid)
        await message.answer("Не удалось сохранить код. Попробуйте позже.")
        return
    await _set_input_mode(state, INPUT_NONE)
    await message.answer(texts.profile_code_saved(digits))
    await _show_profile(message, state, replace=True)


async def _handle_ref_tag_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    tag = (message.text or "").strip().lower()
    try:
        new_tag = await referral_service.create_custom_tag(uid, tag)
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await _set_input_mode(state, INPUT_NONE)
    bot_username = await _get_bot_username(message, state)
    link = f"https://t.me/{bot_username}?start={new_tag}"
    await message.answer(f"Готово. Ваша ссылка: {link}")
    await show_referral(message, state, replace=True)


async def _handle_withdraw_amount_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    data = await state.get_data()
    payload: dict[str, Any] = dict(data.get(WITHDRAW_DATA_KEY) or {})
    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = Decimal(raw)
    except InvalidOperation:
        await message.answer("Введите сумму числом, например 1000 или 12.5")
        return
    amount_kop = int((value * 100).to_integral_value())
    if amount_kop <= 0:
        await message.answer("Сумма должна быть положительной.")
        return
    now_ts = datetime.now(timezone.utc).timestamp()
    rate = None
    stored_rate = payload.get("rate")
    stored_ts = payload.get("rate_ts")
    if isinstance(stored_rate, (int, float)) and isinstance(stored_ts, (int, float)):
        if now_ts - float(stored_ts) <= 5 * 60:
            rate = float(stored_rate)
    if rate is None:
        try:
            rate = await rates_service.get_usdt_rub_rate()
        except Exception:
            logging.exception("failed to fetch usdt/rub rate")
            await message.answer("Сейчас не удалось получить курс USDT. Попробуйте ещё раз чуть позже.")
            return
        payload["rate"] = rate
        payload["rate_ts"] = now_ts
    if rate <= 0:
        await message.answer("Сейчас не удалось получить курс USDT. Попробуйте ещё раз чуть позже.")
        return
    amount_rub = amount_kop // 100
    amount_usdt = (amount_kop / 100) / rate
    if amount_usdt < REF_WITHDRAW_MIN_USD:
        await message.answer(
            (
                "Сумма слишком мала.\n\n"
                f"Курс 1 USDT ≈ {rate:.2f} ₽.\n"
                f"Ваши {amount_rub} ₽ ≈ {amount_usdt:.2f} USDT.\n"
                f"Минимальная сумма для вывода — {REF_WITHDRAW_MIN_USD} USDT. Попробуйте указать большую сумму."
            ),
            reply_markup=kb_single_back("ref:open"),
        )
        return
    payload.update(
        {
            "amount_kop": amount_kop,
            "amount_rub": amount_rub,
            "amount_usdt": amount_usdt,
        }
    )
    await state.update_data({WITHDRAW_DATA_KEY: payload})
    await _set_input_mode(state, INPUT_WITHDRAW_DETAILS)
    await message.answer(
        texts.ref_withdraw_details_prompt(amount_rub=amount_rub, amount_usdt=amount_usdt),
        reply_markup=kb_single_back("ref:open"),
    )


async def _handle_withdraw_details_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    data = await state.get_data()
    payload = dict(data.get(WITHDRAW_DATA_KEY) or {})
    amount_kop = payload.get("amount_kop")
    amount_usdt = payload.get("amount_usdt")
    if not amount_kop:
        await message.answer("Сначала укажите сумму.")
        await _set_input_mode(state, INPUT_WITHDRAW_AMOUNT)
        return
    requisites = (message.text or "").strip()
    details_payload: dict[str, Any] = {"requisites": requisites}
    if amount_usdt is not None:
        details_payload["amount_usdt"] = float(amount_usdt)
    result = await referral_service.request_payout(
        uid,
        amount_kop=amount_kop,
        details=details_payload,
    )
    if not result["accepted"]:
        reason = result.get("reason") or "error"
        if reason == "too_small":
            await message.answer("Сумма меньше минимума на вывод.", reply_markup=kb_single_back("ref:open"))
        elif reason == "insufficient_funds":
            await message.answer("Недостаточно средств для вывода.", reply_markup=kb_single_back("ref:open"))
        else:
            await message.answer("Не удалось создать заявку. Попробуйте позже.", reply_markup=kb_single_back("ref:open"))
        return
    await _set_input_mode(state, INPUT_NONE)
    rate_snapshot = {}
    if "rate" in payload and "rate_ts" in payload:
        rate_snapshot = {"rate": payload.get("rate"), "rate_ts": payload.get("rate_ts")}
    await state.update_data({WITHDRAW_DATA_KEY: rate_snapshot})
    amount_text = texts.fmt_rub_from_kop(amount_kop)
    await message.answer(
        f"Заявка на вывод {amount_text} принята. Мы сообщим, когда будет выполнено.",
        reply_markup=kb_single_back("ref:open"),
    )
    await show_referral(message, state, replace=True)


async def _handle_b2b_lead_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    payload = (message.text or "").strip()
    if not payload:
        await message.answer(
            "Сообщение пустое. Напишите заявку одним сообщением.",
            reply_markup=kb_b2b_ati_lead_back(),
        )
        return
    from_user = message.from_user
    username = from_user.username if from_user else None
    first_name = from_user.first_name if from_user else None
    last_name = from_user.last_name if from_user else None
    try:
        await b2b_service.add_ati_lead(
            uid,
            username=username,
            first_name=first_name,
            last_name=last_name,
            payload=payload,
            source=B2B_LEAD_SOURCE,
        )
    except Exception:
        logging.exception("failed to save b2b lead for user %s", uid)
        await message.answer(
            "Не удалось отправить заявку. Попробуйте ещё раз позже.",
            reply_markup=kb_b2b_ati_lead_back(),
        )
        return
    await _set_input_mode(state, INPUT_NONE)
    await message.answer(texts.b2b_ati_lead_ok_text(), reply_markup=kb_b2b_ati_after_lead())
    await _notify_b2b_lead(message, payload, source=B2B_LEAD_SOURCE)


async def _notify_b2b_lead(message: Message, payload: str, *, source: str) -> None:
    chat_id = cfg.b2b_leads_chat_id
    if not chat_id:
        return
    uid = _user_id(message)
    if uid is None:
        return
    from_user = message.from_user
    username = ""
    full_name = ""
    if from_user is not None:
        if from_user.username:
            username = f"@{from_user.username}"
        full_name = f"{from_user.first_name or ''} {from_user.last_name or ''}".strip()
    username_display = escape(username) if username else "—"
    full_name_display = escape(full_name) if full_name else "—"
    text = (
        "🔔 <b>Новая заявка «Антифрод в АТИ»</b>\n\n"
        f"User ID: <code>{uid}</code> ({username_display})\n"
        f"Имя: {full_name_display}\n"
        f"Источник: {escape(source)}\n\n"
        "Текст:\n"
        f"<pre>{escape(payload)}</pre>"
    )
    try:
        await message.bot.send_message(chat_id, text)
    except Exception:
        logging.exception("failed to notify admin chat about b2b lead from user %s", uid)


@router.callback_query(F.data == "buy:open")
async def on_buy_open(query: CallbackQuery, state: FSMContext) -> None:
    await _show_payment_packages(query, state, replace=False)


@router.callback_query(F.data.startswith("buy:pkg:"))
async def on_buy_package(query: CallbackQuery, state: FSMContext) -> None:
    try:
        qty = int(query.data.split(":")[-1])
    except ValueError:
        await query.answer("Пакет недоступен", show_alert=True)
        return
    try:
        pkg = _get_package_by_qty(qty)
    except ValueError:
        await query.answer("Пакет недоступен", show_alert=True)
        return
    await state.update_data(
        {
            "buy_package_qty": qty,
            "buy_package_code": _package_code_from_qty(qty),
            "buy_package_price": pkg.price_rub,
        }
    )
    text = texts.payment_confirm_text(pkg.qty, pkg.price_rub)
    await _replace_screen(state, "buy")
    await _answer(query, text, kb_payment_confirm(pkg.qty, pkg.price_rub))


@router.callback_query(F.data.startswith("buy:pay:"))
async def on_buy_confirm(query: CallbackQuery, state: FSMContext) -> None:
    try:
        _, _, qty_str, price_str = query.data.split(":", 3)
        qty = int(qty_str)
        price = int(price_str)
    except (ValueError, IndexError):
        await query.answer("Пакет недоступен", show_alert=True)
        return
    try:
        pkg = _get_package_by_qty(qty)
    except ValueError:
        await query.answer("Пакет недоступен", show_alert=True)
        return
    if pkg.price_rub != price:
        await query.answer("Пакет недоступен", show_alert=True)
        return
    await state.update_data(
        {
            "buy_package_qty": qty,
            "buy_package_code": _package_code_from_qty(qty),
            "buy_package_price": price,
        }
    )
    await _replace_screen(state, "buy")
    await _answer(query, texts.payment_method_text(), kb_payment_methods())


@router.callback_query(F.data.startswith("buy:method:"))
async def on_buy_method(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    code = data.get("buy_package_code")
    if not code:
        await query.answer("Сначала выберите пакет", show_alert=True)
        return
    uid = _user_id(query)
    if uid is None:
        return
    method = query.data.split(":")[-1]
    try:
        payment = await sandbox_pay.start_demo_checkout(uid, code)
    except Exception:
        logging.exception("failed to start demo checkout")
        await query.answer("Не удалось создать заказ", show_alert=True)
        return

    if method == "stars":
        await sandbox_pay.simulate_failure(payment["payment_id"], reason="stars")
        await state.update_data({"buy_payment_id": None})
        await _replace_screen(state, "buy-failure")
        await _answer(query, texts.payment_error_text("stars"), kb_payment_error(payment["payment_id"]))
        return

    await _show_payment_pending(query, state, payment["payment_id"])


@router.callback_query(F.data.startswith("buy:check:"))
async def on_buy_check(query: CallbackQuery, state: FSMContext) -> None:
    uid = _user_id(query)
    if uid is None:
        return
    payment_id = query.data.split(":")[-1]
    result = await sandbox_pay.simulate_success(payment_id)
    if not result["ok"]:
        reason = result.get("reason") or "error"
        key = "timeout" if reason == "not-found" else "error"
        await state.update_data({"buy_payment_id": None})
        await _replace_screen(state, "buy-failure")
        await _answer(query, texts.payment_error_text(key), kb_payment_error(payment_id))
        return
    if result["status_was"] == "confirmed" and result.get("granted_requests", 0) == 0:
        await state.update_data({"buy_payment_id": None})
        await _replace_screen(state, "buy-failure")
        await _answer(query, texts.payment_error_text("duplicate"), kb_payment_error(payment_id))
        return
    quota = await _get_quota_service().get_state(uid)
    text = texts.payment_success_text(result.get("granted_requests", 0), quota.balance)
    if result.get("need_company_ati_capture"):
        text += "\n\n" + texts.company_ati_ask()
    await state.update_data({"buy_payment_id": None})
    await _replace_screen(state, "buy-success")
    await _answer(query, text, kb_payment_success())


@router.callback_query(F.data.startswith("buy:retry:"))
async def on_buy_retry(query: CallbackQuery, state: FSMContext) -> None:
    await query.answer("Повторяем…")
    await _show_payment_packages(query, state, replace=True)
