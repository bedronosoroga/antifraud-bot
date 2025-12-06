from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

Q4_OPTIONS = [
    ("1", "Ищу грузы"),
    ("2", "Ищу машины"),
    ("3", "Проверяю контрагентов"),
    ("4", "Другое"),
]


def render_q4_text(selected: list[str]) -> str:
    return (
        "4️⃣ <b>Что вы чаще всего делаете в АТИ?</b>\n"
        "Можно выбрать несколько пунктов, нажимая варианты. Когда закончите — нажмите «Готово»."
    )


def build_q4_kb(selected: list[str]) -> InlineKeyboardMarkup:
    rows = []
    for code, label in Q4_OPTIONS:
        mark = "✅" if code in selected else "⬜"
        rows.append([InlineKeyboardButton(text=f"{mark} {label}", callback_data=f"q4:{code}")])
    rows.append([InlineKeyboardButton(text="Готово", callback_data="q4:done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
