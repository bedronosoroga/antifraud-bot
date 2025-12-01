from __future__ import annotations

from typing import Iterable, List

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton

from app.config import REQUEST_PACKAGES, RequestPackage

SUPPORT_URL = "https://t.me/antifraud_support"


def _kb(rows: Iterable[Iterable[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[list(row) for row in rows])


def kb_menu() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(text="🔎 Запрос", callback_data="req:open"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile:open"),
            ],
            [
                InlineKeyboardButton(text="🧾 История", callback_data="hist:open"),
                InlineKeyboardButton(text="🆘 Поддержка", callback_data="support:open"),
            ],
        ]
    )


def kb_request_no_balance() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="💳 Купить запросы", callback_data="buy:open")],
            [InlineKeyboardButton(text="🆘 Как получить запросы бесплатно", callback_data="ref:freeinfo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )

def kb_request_has_balance() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(text="🧾 История", callback_data="hist:open"),
                InlineKeyboardButton(text="ℹ️ О методике", callback_data="method:open"),
            ],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )

def kb_free_info() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="🤝 Партнёрская программа", callback_data="ref:open")],
            [InlineKeyboardButton(text="⬅️ Вернуться в меню", callback_data="nav:menu")],
        ]
    )


def kb_history(*, page: int, has_prev: bool, has_next: bool, masked: bool) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    nav_row: List[InlineKeyboardButton] = []
    if has_prev:
        nav_row.append(InlineKeyboardButton(text="◀️ Назад", callback_data=f"hist:page:{page - 1}"))
    if has_next:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶️", callback_data=f"hist:page:{page + 1}"))
    if nav_row:
        rows.append(nav_row)

    mask_btn = (
        InlineKeyboardButton(text="👁 Показать коды", callback_data="hist:mask:off")
        if masked
        else InlineKeyboardButton(text="🙈 Скрыть коды", callback_data="hist:mask:on")
    )
    rows.append([mask_btn])
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="hist:menu")])
    return _kb(rows)


def kb_profile() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(text="💳 Купить запросы", callback_data="buy:open"),
                InlineKeyboardButton(text="🧾 История", callback_data="hist:open"),
            ],
            [
                InlineKeyboardButton(text="ℹ️ О методике", callback_data="method:open"),
                InlineKeyboardButton(text="✏️ Мой код АТИ", callback_data="profile:code:edit"),
            ],
            [InlineKeyboardButton(text="🧩 Антифрод в АТИ для компаний", callback_data="b2b:ati:open")],
            [InlineKeyboardButton(text="🎁 Как получить запросы бесплатно?", callback_data="ref:freeinfo")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:menu")],
        ]
    )


def kb_single_back(callback: str = "nav:back") -> InlineKeyboardMarkup:
    return _kb([[InlineKeyboardButton(text="⬅️ Назад", callback_data=callback)]])


def _package_button_label(pkg: RequestPackage) -> str:
    return f"{pkg.qty} — {pkg.price_rub} ₽ ({pkg.discount_hint})"


def kb_packages() -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for pkg in REQUEST_PACKAGES:
        rows.append(
            [InlineKeyboardButton(text=_package_button_label(pkg), callback_data=f"buy:pkg:{pkg.qty}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")])
    return _kb(rows)


def plans_kb_for_provider() -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for pkg in REQUEST_PACKAGES:
        rows.append(
            [InlineKeyboardButton(text=_package_button_label(pkg), callback_data=f"buy:pkg:{pkg.qty}")]
        )
    rows.append([InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:menu")])
    return _kb(rows)


def kb_payment_confirm(qty: int, price_rub: int) -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text=f"Оплатить {price_rub} ₽", callback_data=f"buy:pay:{qty}:{price_rub}")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )


def kb_payment_methods() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="Картой", callback_data="buy:method:card")],
            [InlineKeyboardButton(text="Telegram Stars", callback_data="buy:method:stars")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )


def kb_payment_pending(payment_id: str, confirmation_url: str | None = None, price_rub: int | None = None) -> InlineKeyboardMarkup:
    rows = []
    if confirmation_url:
        label_price = f" {price_rub} ₽" if price_rub else ""
        rows.append([InlineKeyboardButton(text=f"🧾 Оплатить{label_price}", url=confirmation_url)])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")])
    return _kb(rows)


def kb_payment_success() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="🔎 Сделать запрос", callback_data="req:open")],
            [InlineKeyboardButton(text="🧾 История", callback_data="hist:open")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )


def kb_payment_error(payment_id: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="Повторить оплату", callback_data=f"buy:retry:{payment_id}")],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support:open")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )


def kb_payment_email_cancel() -> InlineKeyboardMarkup:
    return _kb([[InlineKeyboardButton(text="❌ Отменить оплату", callback_data="buy:email:cancel")]])


def kb_referral_main(link: str) -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(
                    text="🔗 Скопировать ссылку",
                    copy_text=CopyTextButton(text=link),
                )
            ],
            [InlineKeyboardButton(text="✏️ Создать свою ссылку", callback_data="ref:tag")],
            [InlineKeyboardButton(text="👥 Мои рефералы", callback_data="ref:list")],
            [InlineKeyboardButton(text="💸 Вывод средств", callback_data="ref:withdraw")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="profile:open")],
        ]
    )


def kb_support() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="💬 Написать в поддержку", url=SUPPORT_URL)],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )


def kb_b2b_ati_intro() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="📱 Отправить номер", callback_data="b2b:ati:send_phone")],
            [InlineKeyboardButton(text="⬅️ Назад", callback_data="nav:back")],
        ]
    )


def kb_b2b_ati_request_contact() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер", request_contact=True)],
            [KeyboardButton(text="⬅️ Отмена")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def kb_after_report(has_balance: bool) -> InlineKeyboardMarkup:
    if has_balance:
        return _kb(
            [
                [InlineKeyboardButton(text="🔎 Новый запрос", callback_data="req:open")],
                [
                    InlineKeyboardButton(text="🧾 История", callback_data="hist:open"),
                    InlineKeyboardButton(text="ℹ️ О методике", callback_data="method:open"),
                ],
                [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:back")],
            ]
        )
    return kb_request_no_balance()


def kb_method_page1() -> InlineKeyboardMarkup:
    return _kb(
        [
            [InlineKeyboardButton(text="Вперёд ▶️", callback_data="meth:page:2")],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:back")],
        ]
    )


def kb_method_page2() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="meth:page:1"),
                InlineKeyboardButton(text="Вперёд ▶️", callback_data="meth:page:3"),
            ],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:back")],
        ]
    )


def kb_method_page3() -> InlineKeyboardMarkup:
    return _kb(
        [
            [
                InlineKeyboardButton(text="⬅️ Назад", callback_data="meth:page:2"),
            ],
            [InlineKeyboardButton(text="⬅️ В меню", callback_data="nav:back")],
        ]
    )


__all__ = [
    "kb_menu",
    "kb_request_has_balance",
    "kb_request_no_balance",
    "kb_free_info",
    "kb_history",
    "kb_profile",
    "kb_single_back",
    "kb_packages",
    "plans_kb_for_provider",
    "kb_payment_confirm",
    "kb_payment_methods",
    "kb_payment_pending",
    "kb_payment_success",
    "kb_payment_error",
    "kb_payment_email_cancel",
    "kb_referral_main",
    "kb_support",
    "kb_b2b_ati_intro",
    "kb_b2b_ati_request_contact",
    "kb_after_report",
    "kb_method_page1",
    "kb_method_page2",
    "kb_method_page3",
]
