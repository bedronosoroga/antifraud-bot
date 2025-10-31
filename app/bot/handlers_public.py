from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable, Optional

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from app.config import PAYMENTS_ACTIVE_PROVIDER, cfg
from app.core import db as dal
from app.domain.payments import sandbox as sandbox_pay
from app.domain.subs import service as subs_service
from app.texts import (
    hint_send_code, err_need_digits_upto_7,
    plans_list,
    ref_header, ref_link_block, ref_level_block, ref_earnings_block,
    ref_spend_withdraw_block, ref_how_it_works, ref_levels_table,
    wallet_only_in_referral_notice, ref_balance_only_here_notice,
    company_ati_ask, company_ati_why, company_ati_saved, company_ati_later,
    history_header, history_item_line, history_no_more, history_empty, history_empty_hint,
    help_main, faq_text, support_pretext,
    DEMO_PAYMENT_HEADER, DEMO_PAYMENT_NOTE, DEMO_PAYMENT_CREATED,
    DEMO_PAYMENT_CONFIRMED, DEMO_PAYMENT_REJECTED,
    fmt_rub,
)
from app.keyboards import (
    kb_main, kb_after_report, kb_plans_buy, kb_payment_retry, kb_history, kb_help,
    kb_profile, kb_settings, kb_referral,
    kb_company_ati_ask, kb_company_ati_saved,
    kb_back_to_menu, kb_support_minimal,
    kb_sandbox_plans, kb_sandbox_checkout,
)

router = Router(name="public")


HISTORY_PAGE_SIZE = 10


class _OnboardingRuntime:
    free: object | None = None


_onb = _OnboardingRuntime()


def init_onboarding_runtime(*, free: object | None) -> None:
    """
    Вызывается из main при сборке зависимостей, чтобы /start мог выдать пакет.
    """

    _onb.free = free


class CompanyATIStates(StatesGroup):
    """FSM states for collecting company ATI code."""

    waiting_code = State()


def _is_digits_1_7(text: str) -> bool:
    """Return True if text consists of 1-7 digits."""

    t = (text or "").strip()
    return t.isdigit() and 1 <= len(t) <= 7


def _format_sub_status(status: subs_service.SubInfo) -> str:
    plan = status.get("plan") or "none"
    if plan == "none":
        return "Подписка не активна."

    parts = []
    expires_at_ts = status.get("expires_at_ts")
    if expires_at_ts:
        expires_dt = datetime.fromtimestamp(float(expires_at_ts), tz=timezone.utc)
        parts.append(f"Действует до {expires_dt.strftime('%d.%m.%Y')}")

    if plan in {"p20", "p50"}:
        checks_left = status.get("checks_left")
        if checks_left is not None:
            parts.append(f"Осталось проверок: {checks_left}")
    elif plan == "unlim":
        day_cap_left = status.get("day_cap_left")
        if day_cap_left is not None:
            parts.append(f"Остаток на сегодня: {day_cap_left}")

    if not parts:
        parts.append("Подписка активна.")
    return "\n".join(parts)


_REPORT_EMOJI = {
    "A": "🟢",
    "B": "🟡",
    "C": "🟠",
    "D": "🔴",
    "E": "⚪️",
}


def _plan_title(plan_code: Optional[str]) -> str:
    if not plan_code:
        return "Платёж"
    plan = cfg.plans.get(plan_code)
    if plan is None:
        return plan_code
    return plan.title


def _format_amount_kop(amount_kop: Optional[int]) -> str:
    if amount_kop is None:
        return ""
    amount_kop = int(amount_kop)
    rub, kop = divmod(amount_kop, 100)
    if kop == 0:
        return fmt_rub(rub)
    return f"{rub}.{kop:02d} ₽"


def _format_dt(ts: datetime) -> str:
    if not isinstance(ts, datetime):
        return str(ts)
    return ts.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M")


def _render_history(items: Iterable[dict], page: int) -> str:
    title = history_header()
    if page > 1:
        title = f"{title} (стр. {page})"
    lines = [title]
    for item in items:
        event_type = item.get("type")
        ts = item.get("ts")
        dt_str = _format_dt(ts) if ts is not None else ""
        if event_type == "payment":
            plan_code = item.get("plan")
            title_text = _plan_title(plan_code)
            amount_text = _format_amount_kop(item.get("amount_kop"))
            if amount_text:
                label = f"{title_text} ({amount_text})"
            else:
                label = title_text
            lines.append(history_item_line("💳", label, dt_str))
        else:
            report_type = item.get("report_type")
            emoji = _REPORT_EMOJI.get(report_type, "📄")
            label = item.get("ati") or "—"
            lines.append(history_item_line(emoji, label, dt_str))
    return "\n".join(lines)


@router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    """/start → показать подсказку и главное меню."""

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

    try:
        if _onb.free is not None:
            if from_user is not None:
                _onb.free.ensure_pack(from_user.id, datetime.now())
    except Exception:
        logging.exception("ensure_pack failed")

    await state.clear()
    await message.answer(hint_send_code())
    await message.answer(plans_list(), reply_markup=kb_main())


@router.callback_query(F.data == "m:menu")
async def on_menu(query: CallbackQuery, state: FSMContext) -> None:
    """m:menu → главное меню."""

    await query.answer()
    await query.message.edit_text(hint_send_code(), reply_markup=kb_main())


@router.callback_query(F.data == "chk:new")
async def on_check_new(query: CallbackQuery, state: FSMContext) -> None:
    """chk:new → подсказать пользователю прислать код АТИ."""

    await query.answer()
    await query.message.edit_text(hint_send_code(), reply_markup=kb_main())


@router.callback_query(F.data == "m:subs")
async def on_subs(query: CallbackQuery) -> None:
    """m:subs → показать список планов и кнопки покупки."""

    await query.answer()
    if PAYMENTS_ACTIVE_PROVIDER == "sandbox":
        await query.message.edit_text(plans_list(), reply_markup=kb_sandbox_plans())
        return
    await query.message.edit_text(plans_list(), reply_markup=kb_plans_buy())


@router.callback_query(F.data.in_({"pl:buy:20", "pl:buy:50", "pl:buy:unlim"}))
async def on_plan_buy(query: CallbackQuery) -> None:
    """pl:buy:* → заглушка создания счёта на оплату."""

    await query.answer()
    await query.message.edit_text(
        "Готовим счёт… Сейчас откроется окно оплаты. Если не открылось — воспользуйтесь кнопками ниже.",
        reply_markup=kb_payment_retry()
    )


@router.callback_query(F.data == "pay:repeat")
async def on_pay_repeat(query: CallbackQuery) -> None:
    """pay:repeat → повторная попытка оплаты (заглушка)."""

    await query.answer("Повторяем…")


@router.callback_query(F.data.startswith("pay:sbox:init:"))
async def on_sandbox_init(query: CallbackQuery) -> None:
    """pay:sbox:init:<plan> → запускаем демо-оплату."""

    await query.answer()
    if query.from_user is None:
        await query.message.edit_text("Не удалось создать заказ.", reply_markup=kb_back_to_menu())
        return
    plan = query.data.split(":")[-1]
    if plan not in {"p20", "p50", "unlim"}:
        await query.message.edit_text("Неизвестный план.", reply_markup=kb_back_to_menu())
        return
    payment = await sandbox_pay.start_demo_checkout(query.from_user.id, plan)
    note_parts = [
        DEMO_PAYMENT_HEADER,
        DEMO_PAYMENT_NOTE,
        DEMO_PAYMENT_CREATED,
    ]
    await query.message.edit_text(
        "\n\n".join(part for part in note_parts if part),
        reply_markup=kb_sandbox_checkout(payment["payment_id"]),
    )


@router.callback_query(F.data.startswith("pay:sbox:ok:"))
async def on_sandbox_ok(query: CallbackQuery) -> None:
    """pay:sbox:ok:<payment_id> → подтверждаем демо-оплату."""

    await query.answer()
    payment_id = query.data.split(":")[-1]
    result = await sandbox_pay.simulate_success(payment_id)
    if not result["ok"]:
        reason = result.get("reason") or "error"
        await query.message.edit_text(
            f"Не удалось подтвердить оплату: {reason}",
            reply_markup=kb_back_to_menu(),
        )
        return

    if query.from_user is None:
        await query.message.edit_text(
            DEMO_PAYMENT_CONFIRMED,
            reply_markup=kb_back_to_menu(),
        )
        return

    status = await subs_service.get_status(query.from_user.id)
    summary = _format_sub_status(status)

    parts = [DEMO_PAYMENT_CONFIRMED, summary]
    if result.get("need_company_ati_capture"):
        parts.append(company_ati_ask())

    await query.message.edit_text(
        "\n\n".join(parts),
        reply_markup=kb_back_to_menu(),
    )


@router.callback_query(F.data.startswith("pay:sbox:fail:"))
async def on_sandbox_fail(query: CallbackQuery) -> None:
    """pay:sbox:fail:<payment_id> → отменяем демо-оплату."""

    await query.answer()
    payment_id = query.data.split(":")[-1]
    result = await sandbox_pay.simulate_failure(payment_id, reason="demo")
    if not result["ok"]:
        reason = result.get("reason") or "error"
        await query.message.edit_text(
            f"Не удалось отменить оплату: {reason}",
            reply_markup=kb_back_to_menu(),
        )
        return

    await query.message.edit_text(
        DEMO_PAYMENT_REJECTED,
        reply_markup=kb_back_to_menu(),
    )


@router.callback_query(F.data == "pay:choose")
async def on_pay_choose(query: CallbackQuery) -> None:
    """pay:choose → вернуться к списку планов."""

    await query.answer()
    await query.message.edit_text(plans_list(), reply_markup=kb_plans_buy())


@router.callback_query(F.data == "pay:support")
async def on_pay_support(query: CallbackQuery) -> None:
    """pay:support → мини-клавиатура поддержки."""

    await query.answer()
    await query.message.edit_text("Нужна помощь по оплате?", reply_markup=kb_support_minimal())


@router.callback_query(F.data == "m:history")
async def on_history(query: CallbackQuery) -> None:
    """m:history → показать историю действий пользователя."""

    await query.answer()
    user = query.from_user
    if user is None:
        await query.message.edit_text(
            history_empty(),
            reply_markup=kb_back_to_menu(),
        )
        return

    uid = user.id
    total = await dal.count_history(uid)
    if total == 0:
        await query.message.edit_text(
            f"{history_empty()}\n{history_empty_hint()}",
            reply_markup=kb_back_to_menu(),
        )
        return

    items = await dal.get_history(uid, limit=HISTORY_PAGE_SIZE, offset=0)
    text = _render_history(items, page=1)
    await query.message.edit_text(
        text,
        reply_markup=kb_history(page=1, page_size=HISTORY_PAGE_SIZE, total=total),
    )


@router.callback_query(F.data.startswith("hist:more:"))
async def on_history_more(query: CallbackQuery) -> None:
    """hist:more:<page> → следующая страница истории."""

    user = query.from_user
    if user is None:
        await query.message.edit_text(history_no_more(), reply_markup=kb_back_to_menu())
        return

    try:
        page = int(query.data.split(":")[-1])
    except (ValueError, AttributeError):
        await query.message.edit_text(history_no_more(), reply_markup=kb_back_to_menu())
        return

    if page < 1:
        page = 1

    offset = (page - 1) * HISTORY_PAGE_SIZE
    total = await dal.count_history(user.id)
    if offset >= total:
        await query.answer(history_no_more(), show_alert=True)
        return

    items = await dal.get_history(user.id, limit=HISTORY_PAGE_SIZE, offset=offset)
    if not items:
        await query.answer(history_no_more(), show_alert=True)
        return

    await query.answer()
    text = _render_history(items, page=page)
    await query.message.edit_text(
        text,
        reply_markup=kb_history(page=page, page_size=HISTORY_PAGE_SIZE, total=total),
    )


@router.callback_query(F.data == "m:help")
async def on_help(query: CallbackQuery) -> None:
    """m:help → экран помощи."""

    await query.answer()
    await query.message.edit_text(help_main(), reply_markup=kb_help())


@router.callback_query(F.data == "sup:faq")
async def on_faq(query: CallbackQuery) -> None:
    """sup:faq → показать FAQ."""

    await query.answer()
    await query.message.edit_text(faq_text(), reply_markup=kb_back_to_menu())


@router.callback_query(F.data == "sup:contact")
async def on_support_contact(query: CallbackQuery) -> None:
    """sup:contact → написать в поддержку (заглушка)."""

    await query.answer("Открываем чат поддержки…")
    await query.message.edit_text(support_pretext(), reply_markup=kb_back_to_menu())


async def _render_settings(query: CallbackQuery, state: FSMContext) -> None:
    """Render settings screen based on FSM data."""

    data = await state.get_data()
    notif_pay = bool(data.get("notif_pay", True))
    notif_ref = bool(data.get("notif_ref", True))
    mask_hist = bool(data.get("mask_hist", False))
    post_action = str(data.get("post_action", "again"))
    await query.message.edit_text(
        "Настройки",
        reply_markup=kb_settings(
            notif_payments=notif_pay,
            notif_referrals=notif_ref,
            mask_history=mask_hist,
            post_action=post_action,
        )
    )


@router.callback_query(F.data == "m:settings")
async def on_settings(query: CallbackQuery, state: FSMContext) -> None:
    """m:settings → экран настроек."""

    await query.answer()
    await _render_settings(query, state)


@router.callback_query(F.data.in_({"set:notif:pay:toggle", "set:notif:ref:toggle", "set:history:mask:toggle"}))
async def on_settings_toggle(query: CallbackQuery, state: FSMContext) -> None:
    """Тогглы настроек notif_pay | notif_ref | mask_hist."""

    await query.answer()
    data = await state.get_data()
    if query.data == "set:notif:pay:toggle":
        data["notif_pay"] = not bool(data.get("notif_pay", True))
    elif query.data == "set:notif:ref:toggle":
        data["notif_ref"] = not bool(data.get("notif_ref", True))
    elif query.data == "set:history:mask:toggle":
        data["mask_hist"] = not bool(data.get("mask_hist", False))
    await state.update_data(**data)
    await _render_settings(query, state)


@router.callback_query(F.data.in_({"set:post:again", "set:post:menu"}))
async def on_settings_post_action(query: CallbackQuery, state: FSMContext) -> None:
    """set:post:* → выбор действия после отчёта."""

    await query.answer()
    await state.update_data(post_action="again" if query.data.endswith("again") else "menu")
    await _render_settings(query, state)


@router.callback_query(F.data == "m:ref")
async def on_ref_main(query: CallbackQuery) -> None:
    """m:ref → реферальный раздел (заглушка)."""

    await query.answer()
    link = "https://t.me/your_bot?start=ref_ABC"
    level, percent, to_next = 1, 10, 3
    accrued, pending = 0, 0
    can_spend, can_withdraw = False, False

    parts = [
        ref_header(),
        ref_link_block(link),
        ref_level_block(level, percent, to_next),
        ref_earnings_block(accrued, pending),
        ref_spend_withdraw_block(),
        ref_how_it_works(),
        ref_levels_table(),
        wallet_only_in_referral_notice(),
    ]
    await query.message.edit_text(
        "\n\n".join(parts),
        reply_markup=kb_referral(can_spend=can_spend, can_withdraw=can_withdraw)
    )


@router.callback_query(F.data.in_({"ref:link", "ref:copy", "ref:share"}))
async def on_ref_link_actions(query: CallbackQuery) -> None:
    """ref:link|copy|share → заглушки."""

    await query.answer("Готово.")


@router.callback_query(F.data.in_({"ref:spend:20", "ref:spend:50", "ref:spend:unlim"}))
async def on_ref_spend(query: CallbackQuery) -> None:
    """ref:spend:* → покупка из баланса (заглушка)."""

    await query.answer()
    await query.message.edit_text(ref_balance_only_here_notice(), reply_markup=kb_back_to_menu())


@router.callback_query(F.data == "ref:withdraw")
async def on_ref_withdraw(query: CallbackQuery) -> None:
    """ref:withdraw → заявка на вывод (заглушка)."""

    await query.answer("Заявка создана.")


@router.callback_query(F.data == "ref:how")
async def on_ref_how(query: CallbackQuery) -> None:
    """ref:how → подробности о работе рефералок."""

    await query.answer()
    await query.message.edit_text(ref_how_it_works(), reply_markup=kb_back_to_menu())


@router.callback_query(F.data == "ati:set")
async def on_company_ati_set(query: CallbackQuery, state: FSMContext) -> None:
    """ati:set → просим отправить код АТИ (до 7 цифр)."""

    await query.answer()
    await state.set_state(CompanyATIStates.waiting_code)
    await query.message.edit_text(company_ati_ask(), reply_markup=kb_company_ati_ask())


@router.callback_query(F.data == "ati:why")
async def on_company_ati_why(query: CallbackQuery) -> None:
    """ati:why → объясняем, зачем код компании."""

    await query.answer()
    await query.message.edit_text(company_ati_why(), reply_markup=kb_company_ati_ask())


@router.callback_query(F.data == "ati:later")
async def on_company_ati_later(query: CallbackQuery, state: FSMContext) -> None:
    """ati:later → указать код позже."""

    await query.answer("Ок")
    await state.clear()
    await query.message.edit_text(company_ati_later(), reply_markup=kb_back_to_menu())


@router.callback_query(F.data == "ati:change")
async def on_company_ati_change(query: CallbackQuery, state: FSMContext) -> None:
    """ati:change → смена сохранённого кода, включаем FSM."""

    await query.answer()
    await state.set_state(CompanyATIStates.waiting_code)
    await query.message.edit_text("Укажите новый код АТИ (до 7 цифр).", reply_markup=kb_company_ati_ask())


@router.message(CompanyATIStates.waiting_code)
async def on_company_ati_code_input(message: Message, state: FSMContext) -> None:
    """FSM: ждём код до 7 цифр, валидируем и сохраняем."""

    raw = (message.text or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits or len(digits) > 7:
        await message.answer(err_need_digits_upto_7())
        return

    user = message.from_user
    if user is None:
        await message.answer("Не удалось сохранить код. Попробуйте ещё раз.")
        return

    try:
        await dal.set_company_ati(user.id, digits)
    except Exception:
        logging.exception("failed to set company ATI for user %s", user.id)
        await message.answer("Не удалось сохранить код. Попробуйте ещё раз позже.")
        return

    await state.clear()
    await message.answer(company_ati_saved(digits), reply_markup=kb_company_ati_saved())


@router.callback_query(F.data == "ati:check")
async def on_company_ati_check(query: CallbackQuery, state: FSMContext) -> None:
    """ati:check → просим отправить код для проверки."""

    await query.answer()
    await query.message.edit_text(hint_send_code(), reply_markup=kb_after_report())


@router.callback_query(F.data == "m:profile")
async def on_profile(query: CallbackQuery) -> None:
    """m:profile → профиль (заглушка)."""

    await query.answer()
    await query.message.edit_text("Профиль", reply_markup=kb_profile())


@router.message(F.text & ~F.text.regexp(r"^\d{1,7}$"))
async def on_any_text(message: Message) -> None:
    """Любой текст → подсказка и главное меню."""

    await message.answer(hint_send_code(), reply_markup=kb_main())
