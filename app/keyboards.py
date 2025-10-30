from __future__ import annotations

from typing import Iterable, List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app import texts
from app.config import PAYMENTS_ACTIVE_PROVIDER


def _kb(rows: Iterable[Iterable[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(row) for row in rows])


def kb_main() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.ACTION_BTN_CHECK, callback_data="chk:new")],
            [InlineKeyboardButton(text="Подписка", callback_data="m:subs")],
            [InlineKeyboardButton(text=texts.ACTION_BTN_HISTORY, callback_data="m:history")],
            [InlineKeyboardButton(text="Профиль", callback_data="m:profile")],
            [InlineKeyboardButton(text="Помощь", callback_data="m:help")],
        ]
    )


def kb_after_report() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.ACTION_BTN_CHECK, callback_data="chk:new")],
            [InlineKeyboardButton(text=texts.ACTION_BTN_HISTORY, callback_data="m:history")],
            [InlineKeyboardButton(text=texts.ACTION_BTN_MENU, callback_data="m:menu")],
        ]
    )


def kb_plans_buy() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_BUY_P20, callback_data="pl:buy:20")],
            [InlineKeyboardButton(text=texts.BTN_BUY_P50, callback_data="pl:buy:50")],
            [InlineKeyboardButton(text=texts.BTN_BUY_UNLIM, callback_data="pl:buy:unlim")],
            [InlineKeyboardButton(text=texts.BTN_PAY_SUPPORT, callback_data="pay:support")],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def kb_payment_retry() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_REPEAT_PAYMENT, callback_data="pay:repeat")],
            [InlineKeyboardButton(text=texts.BTN_CHOOSE_ANOTHER_PLAN, callback_data="pay:choose")],
            [InlineKeyboardButton(text=texts.BTN_PAY_SUPPORT, callback_data="pay:support")],
        ]
    )


def kb_history(*, page: int = 1, page_size: int = 10, total: Optional[int] = None) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    if total is not None and page * page_size < total:
        rows.append(
            [
                InlineKeyboardButton(
                    text=texts.BTN_MORE,
                    callback_data=f"hist:more:{page + 1}",
                )
            ]
        )
    rows.append([InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")])
    return _kb(rows)


def kb_help() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_FAQ, callback_data="sup:faq")],
            [InlineKeyboardButton(text=texts.BTN_SUPPORT, callback_data="sup:contact")],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def kb_profile() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="Настройки", callback_data="m:settings")],
            [InlineKeyboardButton(text="Реферальная программа", callback_data="m:ref")],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def _switch_text(label: str, enabled: bool) -> str:
    return f"{label}: {'✅' if enabled else '❌'}"


def kb_settings(
    *,
    notif_payments: bool,
    notif_referrals: bool,
    mask_history: bool,
    post_action: str,
) -> InlineKeyboardMarkup:
    post_again = post_action == "again"
    post_menu = post_action == "menu"
    return _kb(
        [
            [
                InlineKeyboardButton(
                    text=_switch_text("Уведомления об оплате", notif_payments),
                    callback_data="set:notif:pay:toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text=_switch_text("Уведомления о рефералах", notif_referrals),
                    callback_data="set:notif:ref:toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text=_switch_text("Скрывать историю", mask_history),
                    callback_data="set:history:mask:toggle",
                )
            ],
            [
                InlineKeyboardButton(
                    text=_switch_text("После отчёта: снова", post_again),
                    callback_data="set:post:again",
                )
            ],
            [
                InlineKeyboardButton(
                    text=_switch_text("После отчёта: меню", post_menu),
                    callback_data="set:post:menu",
                )
            ],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def kb_referral(*, can_spend: bool, can_withdraw: bool) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=texts.BTN_MY_REF_LINK, callback_data="ref:link")],
        [
            InlineKeyboardButton(text=texts.BTN_REF_COPY, callback_data="ref:copy"),
            InlineKeyboardButton(text=texts.BTN_REF_SHARE, callback_data="ref:share"),
        ],
    ]
    if can_spend:
        rows.extend(
            [
                [InlineKeyboardButton(text=texts.BTN_REF_SPEND_20, callback_data="ref:spend:20")],
                [InlineKeyboardButton(text=texts.BTN_REF_SPEND_50, callback_data="ref:spend:50")],
                [InlineKeyboardButton(text=texts.BTN_REF_SPEND_UNLIM, callback_data="ref:spend:unlim")],
            ]
        )
    if can_withdraw:
        rows.append([InlineKeyboardButton(text=texts.BTN_REF_WITHDRAW, callback_data="ref:withdraw")])
    rows.append([InlineKeyboardButton(text=texts.BTN_HOW_IT_WORKS, callback_data="ref:how")])
    rows.append([InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")])
    return _kb(rows)


def kb_company_ati_ask() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_WHY_ASK, callback_data="ati:why")],
            [InlineKeyboardButton(text=texts.BTN_SET_LATER, callback_data="ati:later")],
        ]
    )


def kb_company_ati_saved() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_CHANGE_CODE, callback_data="ati:change")],
            [InlineKeyboardButton(text=texts.BTN_CHECK_THIS_CODE, callback_data="ati:check")],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def kb_back_to_menu() -> InlineKeyboardMarkup:
    return _kb([[InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")]])


def kb_support_minimal() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_SUPPORT, callback_data="sup:contact")],
            [InlineKeyboardButton(text=texts.BTN_FAQ, callback_data="sup:faq")],
        ]
    )


def kb_sandbox_plans() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=texts.BTN_BUY_P20, callback_data="pay:sbox:init:p20")],
            [InlineKeyboardButton(text=texts.BTN_BUY_P50, callback_data="pay:sbox:init:p50")],
            [InlineKeyboardButton(text=texts.BTN_BUY_UNLIM, callback_data="pay:sbox:init:unlim")],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def kb_sandbox_checkout(payment_id: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(
                    text="✅ Оплата прошла (демо)",
                    callback_data=f"pay:sbox:ok:{payment_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ Оплата не прошла (демо)",
                    callback_data=f"pay:sbox:fail:{payment_id}",
                )
            ],
            [InlineKeyboardButton(text=texts.BTN_MENU, callback_data="m:menu")],
        ]
    )


def plans_kb_for_provider() -> InlineKeyboardMarkup:
    if PAYMENTS_ACTIVE_PROVIDER == "sandbox":
        return kb_sandbox_plans()
    return kb_plans_buy()


__all__ = [
    "kb_main",
    "kb_after_report",
    "kb_plans_buy",
    "kb_payment_retry",
    "kb_history",
    "kb_help",
    "kb_profile",
    "kb_settings",
    "kb_referral",
    "kb_company_ati_ask",
    "kb_company_ati_saved",
    "kb_back_to_menu",
    "kb_support_minimal",
    "kb_sandbox_plans",
    "kb_sandbox_checkout",
    "plans_kb_for_provider",
]
