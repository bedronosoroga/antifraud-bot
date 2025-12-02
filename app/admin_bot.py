from __future__ import annotations

import asyncio
import csv
import io
import logging
import os
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import text

from app.config import ADMINS, cfg
from app.core import db as dal

logging.basicConfig(level=logging.INFO)

ADMIN_BOT_TOKEN = os.getenv("ADMIN_BOT_TOKEN")
ADMIN_PIN = os.getenv("ADMIN_PIN", "").strip()

if not ADMIN_BOT_TOKEN:
    raise RuntimeError("ADMIN_BOT_TOKEN is required for admin bot")


class AuthStates(StatesGroup):
    wait_pin = State()
    wait_user_query = State()
    wait_grant_amount = State()
    wait_spend_amount = State()


router = Router(name="admin")


def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Дашборд", callback_data="adm:dash")],
            [InlineKeyboardButton(text="🧑 Пользователи", callback_data="adm:users")],
            [InlineKeyboardButton(text="💳 Оплаты", callback_data="adm:payments")],
            [InlineKeyboardButton(text="🤝 Рефералы", callback_data="adm:refs")],
            [InlineKeyboardButton(text="📥 Экспорт оплат (7д)", callback_data="adm:export:payments")],
            [InlineKeyboardButton(text="📈 Активность", callback_data="adm:activity")],
        ]
    )


def kb_user_actions(uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="➕ Начислить", callback_data=f"adm:user:grant:{uid}"),
                InlineKeyboardButton(text="➖ Списать", callback_data=f"adm:user:spend:{uid}"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="adm:menu")],
        ]
    )


def kb_back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="⬅️ В меню", callback_data="adm:menu")]]
    )


def _kb_confirm(kind: str, uid: int, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да", callback_data=f"adm:confirm:{kind}:{uid}:{amount}"),
                InlineKeyboardButton(text="❌ Нет", callback_data="adm:menu"),
            ]
        ]
    )

async def _ensure_admin(query: CallbackQuery | Message, state: FSMContext) -> bool:
    uid = query.from_user.id if query.from_user else None
    if uid is None:
        return False
    data = await state.get_data()
    if uid in ADMINS and data.get("adm_authed"):
        return True
    return False


@router.message(Command("start"))
async def on_start(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if uid is None:
        return
    if uid in ADMINS and not ADMIN_PIN:
        await state.update_data({"adm_authed": True})
        await message.answer("Админ-панель", reply_markup=kb_main_menu())
        return
    await state.set_state(AuthStates.wait_pin)
    await message.answer("Введите пин-код для входа в админ-панель.")


@router.message(AuthStates.wait_pin)
async def on_pin(message: Message, state: FSMContext) -> None:
    uid = message.from_user.id if message.from_user else None
    if uid is None:
        return
    if message.text and message.text.strip() == ADMIN_PIN and uid in ADMINS:
        await state.clear()
        await state.update_data({"adm_authed": True})
        await message.answer("Готово. Админ-панель открыта.", reply_markup=kb_main_menu())
    else:
        await message.answer("Неверный пин или нет доступа.")


@router.callback_query(F.data == "adm:menu")
async def on_menu(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    await query.message.edit_text("Админ-панель", reply_markup=kb_main_menu())


@router.callback_query(F.data == "adm:dash")
async def on_dash(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    msg = await _build_dashboard_text()
    await query.message.edit_text(msg, reply_markup=kb_back_menu())


async def _build_dashboard_text() -> str:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=1)
    week = now - timedelta(days=7)
    async with dal.Session() as session:
        users_count = await session.scalar(text("select count(*) from users"))
        users_new_24h = await session.scalar(
            text("select count(*) from users where created_at>=:since"), {"since": since}
        )
        payments_total = await session.scalar(
            text("select count(*) from yk_payments where status='succeeded' and created_at>=:since"),
            {"since": since},
        )
        payments_sum = await session.scalar(
            text(
                "select coalesce(sum(package_price_rub),0) from yk_payments "
                "where status='succeeded' and created_at>=:since"
            ),
            {"since": since},
        )
        pending = await session.scalar(
            text("select count(*) from yk_payments where status in ('pending','waiting_for_capture')")
        )
        stars_success = await session.scalar(
            text(
                "select count(*) from yk_payments where provider='stars' and status='succeeded' and created_at>=:week"
            ),
            {"week": week},
        )
        ref_hold = await session.scalar(text("select coalesce(sum(amount_kop),0) from ref_locks where refunded=false"))
        ref_balance = await session.scalar(text("select coalesce(sum(balance_kop),0) from referrals"))
    return (
        "<b>Дашборд (24ч)</b>\n"
        f"Пользователей: <b>{users_count or 0}</b> (+{users_new_24h or 0} за 24ч)\n"
        f"Оплат (YK) успешно: <b>{payments_total or 0}</b>, сумма: <b>{payments_sum or 0} ₽</b>\n"
        f"Pending платежей (YK): <b>{pending or 0}</b>\n"
        f"Stars успехов (7д): <b>{stars_success or 0}</b>\n"
        f"Ref баланс: <b>{ref_balance or 0} коп</b>, hold: <b>{ref_hold or 0} коп</b>"
    )


@router.callback_query(F.data == "adm:users")
async def on_users(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    await state.set_state(AuthStates.wait_user_query)
    await query.message.edit_text(
        "Введите uid / username / email / ATI код для поиска пользователя.",
        reply_markup=kb_back_menu(),
    )


@router.message(AuthStates.wait_user_query)
async def on_user_query(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message, state):
        return
    query = (message.text or "").strip()
    if not query:
        await message.answer("Пустой запрос.", reply_markup=kb_back_menu())
        return
    user = await _find_user(query)
    if not user:
        await message.answer("Не найдено.", reply_markup=kb_back_menu())
        return
    msg = await _format_user_card(user)
    await state.update_data({"adm_selected_uid": user["id"]})
    await message.answer(msg, reply_markup=kb_user_actions(user["id"]))
    await state.set_state(None)


async def _find_user(query: str) -> Optional[dict[str, Any]]:
    async with dal.Session() as session:
        if query.isdigit():
            # сначала пробуем uid
            res = await session.execute(text("select * from users where id=:id"), {"id": int(query)})
            row = res.mappings().first()
            if row:
                return dict(row)
            # если похоже на ATI (<=7 цифр), пробуем по company_ati
            if len(query) <= 7:
                res = await session.execute(text("select * from users where company_ati=:ati"), {"ati": query})
                row = res.mappings().first()
                if row:
                    return dict(row)
            return None
        elif "@" in query:
            res = await session.execute(text("select * from users where email ilike :q"), {"q": query})
        else:
            res = await session.execute(text("select * from users where username ilike :q"), {"q": query.lstrip('@')})
        row = res.mappings().first()
        return dict(row) if row else None


async def _format_user_card(user: dict[str, Any]) -> str:
    uid = user["id"]
    quota = await dal.get_quota_account(uid)
    ref = await _get_ref_info(uid)
    balance = quota["balance"] if quota else 0
    last_payments = await _get_last_payments(uid, limit=3)
    last_checks = await _get_last_checks(uid, limit=3)
    lines = [
        f"<b>User</b> {uid} @{user.get('username') or '—'}",
        f"Email: {user.get('email') or '—'}",
        f"Регистрация: {user.get('created_at')}",
        f"Баланс запросов: {balance}",
        f"ATI: {user.get('company_ati') or '—'}",
        f"Ref: баланс {ref.get('balance_kop',0)} коп, hold {ref.get('hold_kop',0)} коп, tier {ref.get('percent',0)}%",
    ]
    if last_payments:
        lines.append("Последние оплаты:")
        for p in last_payments:
            lines.append(
                f"• {p['created_at']}: {p['provider']} {p['package_price_rub']} ₽, {p['status']}, id {p['id']}"
            )
    if last_checks:
        lines.append("Последние проверки:")
        for h in last_checks:
            lines.append(f"• {h['ts']}: АТИ {h['ati']}, отчёт {h['report_type']}")
    return "\n".join(lines)


async def _get_ref_info(uid: int) -> dict[str, Any]:
    async with dal.Session() as session:
        res = await session.execute(
            text("select balance_kop, total_earned_kop, percent from referrals where uid=:uid"),
            {"uid": uid},
        )
        row = res.mappings().first()
        data = dict(row) if row else {}
        hold_res = await session.execute(
            text("select coalesce(sum(amount_kop),0) as hold from ref_locks where uid=:uid and refunded=false"),
            {"uid": uid},
        )
        data["hold_kop"] = hold_res.scalar_one_or_none() or 0
    return data


@router.callback_query(F.data.startswith("adm:user:grant:"))
async def on_user_grant(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    uid = int(query.data.split(":")[-1])
    await state.update_data({"adm_selected_uid": uid})
    await state.set_state(AuthStates.wait_grant_amount)
    await query.message.answer("Сколько запросов начислить? Введите число.", reply_markup=kb_back_menu())


@router.callback_query(F.data.startswith("adm:user:spend:"))
async def on_user_spend(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    uid = int(query.data.split(":")[-1])
    await state.update_data({"adm_selected_uid": uid})
    await state.set_state(AuthStates.wait_spend_amount)
    await query.message.answer("Сколько запросов списать? Введите число.", reply_markup=kb_back_menu())


@router.message(AuthStates.wait_grant_amount)
async def on_grant_amount(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message, state):
        return
    try:
        amt = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно число.", reply_markup=kb_back_menu())
        return
    data = await state.get_data()
    uid = data.get("adm_selected_uid")
    if not uid:
        await message.answer("Нет пользователя.", reply_markup=kb_back_menu())
        return
    await message.answer(
        f"Начислить {amt} запросов пользователю {uid}? Подтвердите.", reply_markup=_kb_confirm("grant", uid, amt)
    )
    await state.update_data({"pending_confirm": {"type": "grant", "uid": uid, "amount": amt}})
    await state.set_state(None)


@router.message(AuthStates.wait_spend_amount)
async def on_spend_amount(message: Message, state: FSMContext) -> None:
    if not await _ensure_admin(message, state):
        return
    try:
        amt = int((message.text or "").strip())
    except ValueError:
        await message.answer("Нужно число.", reply_markup=kb_back_menu())
        return
    data = await state.get_data()
    uid = data.get("adm_selected_uid")
    if not uid:
        await message.answer("Нет пользователя.", reply_markup=kb_back_menu())
        return
    await message.answer(
        f"Списать {amt} запросов у пользователя {uid}? Подтвердите.", reply_markup=_kb_confirm("spend", uid, amt)
    )
    await state.update_data({"pending_confirm": {"type": "spend", "uid": uid, "amount": amt}})
    await state.set_state(None)


@router.callback_query(F.data.startswith("adm:confirm:"))
async def on_confirm(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    parts = query.data.split(":")
    if len(parts) != 5:
        await query.answer("Некорректные данные", show_alert=True)
        return
    _, _, kind, uid_raw, amount_raw = parts
    try:
        uid = int(uid_raw)
        amount = int(amount_raw)
    except ValueError:
        await query.answer("Некорректные данные", show_alert=True)
        return
    if kind == "grant":
        await dal.change_quota_balance(uid, amount, source="admin_grant", metadata={"by": query.from_user.id})
        with suppress(Exception):
            await dal.admin_audit_log(query.from_user.id, "grant", {"uid": uid, "amount": amount})
        await query.message.edit_text(f"Начислено {amount} запросов пользователю {uid}.", reply_markup=kb_back_menu())
    elif kind == "spend":
        await dal.change_quota_balance(uid, -abs(amount), source="admin_spend", metadata={"by": query.from_user.id}, allow_negative=False)
        with suppress(Exception):
            await dal.admin_audit_log(query.from_user.id, "spend", {"uid": uid, "amount": amount})
        await query.message.edit_text(f"Списано {amount} запросов у пользователя {uid}.", reply_markup=kb_back_menu())
    else:
        await query.answer("Некорректный тип операции", show_alert=True)
        return


@router.callback_query(F.data == "adm:payments")
async def on_payments(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    msg = await _short_payments()
    await query.message.edit_text(msg, reply_markup=kb_back_menu())


async def _short_payments() -> str:
    async with dal.Session() as session:
        yk_success = await session.scalar(
            text("select count(*) from yk_payments where provider='yookassa' and status='succeeded'")
        )
        yk_pending = await session.scalar(
            text("select count(*) from yk_payments where provider='yookassa' and status in ('pending','waiting_for_capture')")
        )
        yk_failed = await session.scalar(
            text("select count(*) from yk_payments where provider='yookassa' and status in ('canceled','expired','failed')")
        )
        stars_success = await session.scalar(
            text("select count(*) from yk_payments where provider='stars' and status='succeeded'")
        )
        stars_pending = await session.scalar(
            text("select count(*) from yk_payments where provider='stars' and status in ('pending','waiting_for_capture')")
        )
        stars_failed = await session.scalar(
            text("select count(*) from yk_payments where provider='stars' and status in ('canceled','expired','failed')")
        )
        last = await session.execute(
            text(
                "select id, uid, provider, package_price_rub, status, created_at "
                "from yk_payments order by created_at desc limit 5"
            )
        )
        last_rows = last.mappings().all()
    msg = (
        "<b>Оплаты</b>\n"
        f"YK: success {yk_success or 0} | pending {yk_pending or 0} | canceled/expired {yk_failed or 0}\n"
        f"Stars: success {stars_success or 0} | pending {stars_pending or 0} | canceled/expired {stars_failed or 0}"
    )
    if last_rows:
        msg += "\nПоследние 5:\n"
        for row in last_rows:
            msg += f"• {row['created_at']}: {row['provider']} {row['package_price_rub']} ₽, {row['status']}, uid {row['uid']}\n"
    return msg


async def _get_last_payments(uid: int, limit: int = 3) -> list[dict[str, Any]]:
    async with dal.Session() as session:
        res = await session.execute(
            text(
                "select id, provider, package_price_rub, status, created_at "
                "from yk_payments where uid=:uid order by created_at desc limit :lim"
            ),
            {"uid": uid, "lim": limit},
        )
        return [dict(r) for r in res.mappings().all()]


async def _get_last_checks(uid: int, limit: int = 3) -> list[dict[str, Any]]:
    async with dal.Session() as session:
        res = await session.execute(
            text(
                "select ati, report_type, ts from history where uid=:uid order by ts desc limit :lim"
            ),
            {"uid": uid, "lim": limit},
        )
        return [dict(r) for r in res.mappings().all()]


@router.callback_query(F.data == "adm:refs")
async def on_refs(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    async with dal.Session() as session:
        hold = await session.scalar(text("select coalesce(sum(amount_kop),0) from ref_locks where refunded=false"))
        balance = await session.scalar(text("select coalesce(sum(balance_kop),0) from referrals"))
        paid = await session.scalar(text("select coalesce(sum(total_earned_kop),0) from referrals"))
    msg = (
        "<b>Рефералы</b>\n"
        f"Баланс доступен: {balance or 0} коп\n"
        f"На холде: {hold or 0} коп\n"
        f"Всего начислено: {paid or 0} коп"
    )
    await query.message.edit_text(msg, reply_markup=kb_back_menu())


@router.callback_query(F.data == "adm:activity")
async def on_activity(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    week = now - timedelta(days=7)
    async with dal.Session() as session:
        checks_week = await session.scalar(text("select count(*) from history where ts>=:week"), {"week": week})
        users_week = await session.scalar(
            text("select count(distinct uid) from history where ts>=:week"), {"week": week}
        )
        ati_invalid = await session.scalar(
            text("select count(*) from history where ts>=:week and report_type='E'"), {"week": week}
        )
        payments_week = await session.scalar(
            text("select count(*) from yk_payments where status='succeeded' and created_at>=:week"), {"week": week}
        )
    msg = (
        "<b>Активность (7д)</b>\n"
        f"Проверок: {checks_week or 0}\n"
        f"Уникальных пользователей: {users_week or 0}\n"
        f"Отчётов без данных (E): {ati_invalid or 0}\n"
        f"Оплат (успешных): {payments_week or 0}"
    )
    await query.message.edit_text(msg, reply_markup=kb_back_menu())


@router.callback_query(F.data == "adm:export:payments")
async def on_export_payments(query: CallbackQuery, state: FSMContext) -> None:
    if not await _ensure_admin(query, state):
        await query.answer("Нет доступа", show_alert=True)
        return
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["id", "uid", "provider", "qty", "price_rub", "status", "created_at", "refunded", "refunded_at", "charge_id"]
    )
    since = datetime.now(timezone.utc) - timedelta(days=7)
    async with dal.Session() as session:
        res = await session.execute(
            text(
                "select id, uid, provider, package_qty, package_price_rub, status, created_at "
                " , refunded, refunded_at, telegram_charge_id "
                "from yk_payments where created_at>=:since order by created_at desc limit 500"
            ),
            {"since": since},
        )
        for row in res:
            writer.writerow(row)
    buf.seek(0)
    await query.message.answer_document(
        document=("payments_7d.csv", buf.getvalue().encode("utf-8")),
        caption="Экспорт оплат за 7 дней",
        reply_markup=kb_back_menu(),
    )


async def main() -> None:
    bot = Bot(token=ADMIN_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
