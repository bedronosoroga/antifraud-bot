from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from app.config import PAYMENTS_ACTIVE_PROVIDER
from app.domain.onboarding.free import FreeService
from app.domain.payments import sandbox as sandbox_pay
from app.domain.subs import service as subs_service
from app.texts import (
    hint_send_code, err_need_digits_3_7,
    plans_list,
    ref_header, ref_link_block, ref_level_block, ref_earnings_block,
    ref_spend_withdraw_block, ref_how_it_works, ref_levels_table,
    wallet_only_in_referral_notice, ref_balance_only_here_notice,
    company_ati_ask, company_ati_why, company_ati_saved, company_ati_later,
    history_header, history_item_line, history_no_more, history_empty, history_empty_hint,
    help_main, faq_text, support_pretext,
    DEMO_PAYMENT_HEADER, DEMO_PAYMENT_NOTE, DEMO_PAYMENT_CREATED,
    DEMO_PAYMENT_CONFIRMED, DEMO_PAYMENT_REJECTED,
)
from app.keyboards import (
    kb_main, kb_after_report, kb_plans_buy, kb_payment_retry, kb_history, kb_help,
    kb_profile, kb_settings, kb_referral,
    kb_company_ati_ask, kb_company_ati_saved,
    kb_back_to_menu, kb_support_minimal,
    kb_sandbox_plans, kb_sandbox_checkout,
)

public_router = Router(name="public")


class _OnboardingRuntime:
    free: FreeService | None = None


_onb = _OnboardingRuntime()


def init_onboarding_runtime(*, free: FreeService | None) -> None:
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


@public_router.message(CommandStart())
async def on_start(message: Message, state: FSMContext) -> None:
    """/start → показать подсказку и главное меню."""

    try:
        if _onb.free is not None:
            from_user = message.from_user
            if from_user is not None:
                _onb.free.ensure_pack(from_user.id, datetime.now())
    except Exception:
        logging.exception("ensure_pack failed")

    await state.clear()
    await message.answer(hint_send_code())
    await message.answer(plans_list(), reply_markup=kb_main())


@public_router.callback_query(F.data == "m:menu")
async def on_menu(query: CallbackQuery, state: FSMContext) -> None:
    """m:menu → главное меню."""

    await query.answer()
    await query.message.edit_text(hint_send_code(), reply_markup=kb_main())


@public_router.callback_query(F.data == "chk:new")
async def on_check_new(query: CallbackQuery, state: FSMContext) -> None:
    """chk:new → подсказать пользователю прислать код АТИ."""

    await query.answer()
    await query.message.edit_text(hint_send_code(), reply_markup=kb_main())


@public_router.callback_query(F.data == "m:subs")
async def on_subs(query: CallbackQuery) -> None:
    """m:subs → показать список планов и кнопки покупки."""

    await query.answer()
    if PAYMENTS_ACTIVE_PROVIDER == "sandbox":
        await query.message.edit_text(plans_list(), reply_markup=kb_sandbox_plans())
        return
    await query.message.edit_text(plans_list(), reply_markup=kb_plans_buy())


@public_router.callback_query(F.data.in_({"pl:buy:20", "pl:buy:50", "pl:buy:unlim"}))
async def on_plan_buy(query: CallbackQuery) -> None:
    """pl:buy:* → заглушка создания счёта на оплату."""

    await query.answer()
    await query.message.edit_text(
        "Готовим счёт… Сейчас откроется окно оплаты. Если не открылось — воспользуйтесь кнопками ниже.",
        reply_markup=kb_payment_retry()
    )


@public_router.callback_query(F.data == "pay:repeat")
async def on_pay_repeat(query: CallbackQuery) -> None:
    """pay:repeat → повторная попытка оплаты (заглушка)."""

    await query.answer("Повторяем…")


@public_router.callback_query(F.data.startswith("pay:sbox:init:"))
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


@public_router.callback_query(F.data.startswith("pay:sbox:ok:"))
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


@public_router.callback_query(F.data.startswith("pay:sbox:fail:"))
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


@public_router.callback_query(F.data == "pay:choose")
async def on_pay_choose(query: CallbackQuery) -> None:
    """pay:choose → вернуться к списку планов."""

    await query.answer()
    await query.message.edit_text(plans_list(), reply_markup=kb_plans_buy())


@public_router.callback_query(F.data == "pay:support")
async def on_pay_support(query: CallbackQuery) -> None:
    """pay:support → мини-клавиатура поддержки."""

    await query.answer()
    await query.message.edit_text("Нужна помощь по оплате?", reply_markup=kb_support_minimal())


@public_router.callback_query(F.data == "m:history")
async def on_history(query: CallbackQuery) -> None:
    """m:history → список последних проверок (заглушка)."""

    await query.answer()
    items: list[tuple[str, str, str]] = []
    if not items:
        await query.message.edit_text(
            f"{history_empty()}\n{history_empty_hint()}",
            reply_markup=kb_back_to_menu()
        )
        return
    lines = [history_header()] + [history_item_line(e, a, d) for (e, a, d) in items]
    await query.message.edit_text("\n".join(lines), reply_markup=kb_history(paginated=True))


@public_router.callback_query(F.data == "hist:more")
async def on_history_more(query: CallbackQuery) -> None:
    """hist:more → следующая страница истории (заглушка)."""

    await query.answer()
    more: list[tuple[str, str, str]] = []
    if not more:
        await query.message.edit_text(history_no_more(), reply_markup=kb_back_to_menu())
        return
    lines = [history_item_line(e, a, d) for (e, a, d) in more]
    await query.message.edit_text("\n".join(lines), reply_markup=kb_history(paginated=True))


@public_router.callback_query(F.data == "m:help")
async def on_help(query: CallbackQuery) -> None:
    """m:help → экран помощи."""

    await query.answer()
    await query.message.edit_text(help_main(), reply_markup=kb_help())


@public_router.callback_query(F.data == "sup:faq")
async def on_faq(query: CallbackQuery) -> None:
    """sup:faq → показать FAQ."""

    await query.answer()
    await query.message.edit_text(faq_text(), reply_markup=kb_back_to_menu())


@public_router.callback_query(F.data == "sup:contact")
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
            notif_ref=notif_ref,
            mask_history=mask_hist,
            post_report_action=post_action,
        )
    )


@public_router.callback_query(F.data == "m:settings")
async def on_settings(query: CallbackQuery, state: FSMContext) -> None:
    """m:settings → экран настроек."""

    await query.answer()
    await _render_settings(query, state)


@public_router.callback_query(F.data.in_({"set:notif:pay:toggle", "set:notif:ref:toggle", "set:history:mask:toggle"}))
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


@public_router.callback_query(F.data.in_({"set:post:again", "set:post:menu"}))
async def on_settings_post_action(query: CallbackQuery, state: FSMContext) -> None:
    """set:post:* → выбор действия после отчёта."""

    await query.answer()
    await state.update_data(post_action="again" if query.data.endswith("again") else "menu")
    await _render_settings(query, state)


@public_router.callback_query(F.data == "m:ref")
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


@public_router.callback_query(F.data.in_({"ref:link", "ref:copy", "ref:share"}))
async def on_ref_link_actions(query: CallbackQuery) -> None:
    """ref:link|copy|share → заглушки."""

    await query.answer("Готово.")


@public_router.callback_query(F.data.in_({"ref:spend:20", "ref:spend:50", "ref:spend:unlim"}))
async def on_ref_spend(query: CallbackQuery) -> None:
    """ref:spend:* → покупка из баланса (заглушка)."""

    await query.answer()
    await query.message.edit_text(ref_balance_only_here_notice(), reply_markup=kb_back_to_menu())


@public_router.callback_query(F.data == "ref:withdraw")
async def on_ref_withdraw(query: CallbackQuery) -> None:
    """ref:withdraw → заявка на вывод (заглушка)."""

    await query.answer("Заявка создана.")


@public_router.callback_query(F.data == "ref:how")
async def on_ref_how(query: CallbackQuery) -> None:
    """ref:how → подробности о работе рефералок."""

    await query.answer()
    await query.message.edit_text(ref_how_it_works(), reply_markup=kb_back_to_menu())


@public_router.callback_query(F.data == "ati:set")
async def on_company_ati_set(query: CallbackQuery, state: FSMContext) -> None:
    """ati:set → просим отправить код АТИ (до 7 цифр)."""

    await query.answer()
    await state.set_state(CompanyATIStates.waiting_code)
    await query.message.edit_text(company_ati_ask(), reply_markup=kb_company_ati_ask())


@public_router.callback_query(F.data == "ati:why")
async def on_company_ati_why(query: CallbackQuery) -> None:
    """ati:why → объясняем, зачем код компании."""

    await query.answer()
    await query.message.edit_text(company_ati_why(), reply_markup=kb_company_ati_ask())


@public_router.callback_query(F.data == "ati:later")
async def on_company_ati_later(query: CallbackQuery, state: FSMContext) -> None:
    """ati:later → указать код позже."""

    await query.answer("Ок")
    await state.clear()
    await query.message.edit_text(company_ati_later(), reply_markup=kb_back_to_menu())


@public_router.callback_query(F.data == "ati:change")
async def on_company_ati_change(query: CallbackQuery, state: FSMContext) -> None:
    """ati:change → смена сохранённого кода, включаем FSM."""

    await query.answer()
    await state.set_state(CompanyATIStates.waiting_code)
    await query.message.edit_text("Укажите новый код АТИ (до 7 цифр).", reply_markup=kb_company_ati_ask())


@public_router.message(CompanyATIStates.waiting_code)
async def on_company_ati_code_input(message: Message, state: FSMContext) -> None:
    """FSM: ждём код до 7 цифр, валидируем и сохраняем."""

    code = (message.text or "").strip()
    if not _is_digits_1_7(code):
        await message.answer(err_need_digits_3_7())
        return
    await state.update_data(company_ati_code=code)
    await state.clear()
    await message.answer(company_ati_saved(code), reply_markup=kb_company_ati_saved())


@public_router.callback_query(F.data == "ati:check")
async def on_company_ati_check(query: CallbackQuery, state: FSMContext) -> None:
    """ati:check → просим отправить код для проверки."""

    await query.answer()
    await query.message.edit_text(hint_send_code(), reply_markup=kb_after_report())


@public_router.callback_query(F.data == "m:profile")
async def on_profile(query: CallbackQuery) -> None:
    """m:profile → профиль (заглушка)."""

    await query.answer()
    await query.message.edit_text("Профиль", reply_markup=kb_profile())


@public_router.message(F.text & ~F.text.regexp(r"^\d{1,7}$"))
async def on_any_text(message: Message) -> None:
    """Любой текст → подсказка и главное меню."""

    await message.answer(hint_send_code(), reply_markup=kb_main())
