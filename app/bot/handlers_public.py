from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart, Filter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app import texts
from app.bot import runtime as bot_runtime
from app.config import REQUEST_PACKAGES, RequestPackage, cfg
from app.core import db as dal
from app.domain.payments import sandbox as sandbox_pay
from app.domain.referrals import service as referral_service
from app.domain.onboarding.free import FreeService
from app.domain.quotas.service import InsufficientQuotaError
from app.keyboards import (
    kb_free_info,
    kb_history,
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
)

router = Router(name="public")
MSK_TZ = ZoneInfo(cfg.tz or "Europe/Moscow")


class _OnboardingRuntime:
    free: FreeService | None = None


_onboarding = _OnboardingRuntime()

NAV_STACK_KEY = "nav_stack"
INPUT_MODE_KEY = "input_mode"
HISTORY_PAGE_KEY = "hist_page"
HISTORY_MASK_KEY = "hist_mask"
HISTORY_ORIGIN_KEY = "hist_origin"
WITHDRAW_DATA_KEY = "withdraw_data"

INPUT_NONE = "none"
INPUT_PROFILE_ATI = "profile:code:edit"
INPUT_REF_TAG = "ref:tag:create"
INPUT_WITHDRAW_AMOUNT = "ref:withdraw:amount"
INPUT_WITHDRAW_DETAILS = "ref:withdraw:details"

PACKAGE_MAP = {f"pkg{pkg.qty}": pkg for pkg in REQUEST_PACKAGES}
PACKAGE_BY_QTY = {pkg.qty: pkg for pkg in REQUEST_PACKAGES}


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
            [InlineKeyboardButton(text="🔎 показать все возможные команды", callback_data="menu:open")]
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
    if from_user is not None:
        try:
            await dal.ensure_user(
                from_user.id,
                from_user.username,
                from_user.first_name,
                from_user.last_name,
            )
        except Exception:
            logging.exception("ensure_user failed for /start")
        uid = from_user.id
        await _handle_start_referral(uid, message.text or "")
        await _ensure_free_pack(uid)

    await state.clear()
    await _reset_nav(state)
    await _set_input_mode(state, INPUT_NONE)

    hero_msg = await message.answer(texts.hero_banner())
    try:
        await hero_msg.pin(disable_notification=True)
    except TelegramBadRequest:
        pass
    except Exception:
        logging.exception("failed to pin hero message")

    await message.answer(texts.start_onboarding_message(), reply_markup=_start_keyboard())


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
    if screen == "buy":
        await _show_payment_packages(target, state, replace=replace)
        return
    if screen == "free-info":
        await _show_free_info(target, state)
        return
    if screen == "support":
        await _show_support(target, state)
        return
    if screen == "history":
        await show_history(target, state, replace=replace)
        return
    if screen == "referral":
        await show_referral(target, state, replace=replace)
        return
    await _show_menu(target, state, replace=True)


# Additional handlers for request, history, profile, payments, referrals, support will follow...


@router.callback_query(F.data == "req:open")
async def on_request_open(query: CallbackQuery, state: FSMContext) -> None:
    await _show_request(query, state, replace=False)


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
    masked = data.get(HISTORY_MASK_KEY, True)
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


@router.callback_query(F.data == "profile:refresh")
async def on_profile_refresh(query: CallbackQuery, state: FSMContext) -> None:
    await _show_profile(query, state, replace=True)


@router.callback_query(F.data == "profile:code:edit")
async def on_profile_code_edit(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    user = await dal.get_user(query.from_user.id) if query.from_user else None
    current = user.get("company_ati") if user else None
    await _set_input_mode(state, INPUT_PROFILE_ATI)
    await _answer(query, texts.profile_code_prompt(current), kb_single_back())


@router.callback_query(F.data == "ref:freeinfo")
async def on_free_info(query: CallbackQuery, state: FSMContext) -> None:
    await _show_free_info(query, state)


@router.callback_query(F.data == "support:open")
async def on_support(query: CallbackQuery, state: FSMContext) -> None:
    await _show_support(query, state)


@router.callback_query(F.data == "ref:open")
async def on_referral_open(query: CallbackQuery, state: FSMContext) -> None:
    await show_referral(query, state, replace=False)


@router.callback_query(F.data == "ref:copy")
async def on_referral_copy(query: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    link = data.get("ref_link")
    if not link:
        await show_referral(query, state, replace=True)
        data = await state.get_data()
        link = data.get("ref_link")
    if link:
        await query.message.answer(f"Ваша ссылка:\n{link}")
        await query.answer("Отправили ссылку в чат.")
    else:
        await query.answer("Ссылка недоступна", show_alert=True)


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
    await state.update_data({WITHDRAW_DATA_KEY: {}})
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
    await state.update_data({"ref_link": link})
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
    await _answer(target, text, kb_referral_main())


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
    await state.update_data({"ref_link": link})
    await message.answer(f"Готово. Ваша ссылка: {link}")
    await show_referral(message, state, replace=True)


async def _handle_withdraw_amount_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
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
    await state.update_data({WITHDRAW_DATA_KEY: {"amount_kop": amount_kop}})
    await _set_input_mode(state, INPUT_WITHDRAW_DETAILS)
    await message.answer(
        "Укажите реквизиты (Telegram Stars или USDT + сеть). Пример: \"USDT TON, адрес ...\"",
        reply_markup=kb_single_back("ref:open"),
    )


async def _handle_withdraw_details_input(message: Message, state: FSMContext) -> None:
    uid = _user_id(message)
    if uid is None:
        return
    data = await state.get_data()
    payload = data.get(WITHDRAW_DATA_KEY) or {}
    amount_kop = payload.get("amount_kop")
    if not amount_kop:
        await message.answer("Сначала укажите сумму.")
        await _set_input_mode(state, INPUT_WITHDRAW_AMOUNT)
        return
    requisites = (message.text or "").strip()
    result = await referral_service.request_payout(
        uid,
        amount_kop=amount_kop,
        details={"requisites": requisites},
    )
    if not result["accepted"]:
        reason = result.get("reason") or "error"
        if reason == "too_small":
            await message.answer("Сумма меньше минимума на вывод.")
        elif reason == "insufficient_funds":
            await message.answer("Недостаточно средств для вывода.")
        else:
            await message.answer("Не удалось создать заявку. Попробуйте позже.")
        return
    await _set_input_mode(state, INPUT_NONE)
    amount_text = texts.fmt_rub_from_kop(amount_kop)
    await message.answer(f"Заявка на вывод {amount_text} принята. Мы сообщим, когда будет выполнено.")
    await show_referral(message, state, replace=True)


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
