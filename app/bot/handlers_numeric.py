from __future__ import annotations

from aiogram import Router, F
from aiogram.types import Message

from app.bot.keyboards import kb_after_report, kb_main
from app.domain.checks.service import CheckerService
from app.domain.checks.formatter import build_report_text


numeric_router = Router(name="numeric")


class _Runtime:
    checker: CheckerService | None = None
    lin_ok: int = 2
    exp_ok: int = 5


_runtime = _Runtime()


def init_checks_runtime(checker: CheckerService, lin_ok: int = 2, exp_ok: int = 5) -> None:
    """
    Вызывается при старте бота (в main.py) после загрузки каталога.
    Делает модуль готовым к обработке кодов.
    """
    _runtime.checker = checker
    _runtime.lin_ok = int(lin_ok)
    _runtime.exp_ok = int(exp_ok)


async def _not_ready_reply(message: Message) -> None:
    """Отправляет пользователю сообщение о недоступности сервиса."""
    # Используем простую подсказку и клавиатуру меню
    await message.answer(
        "Сервис проверок сейчас недоступен. Попробуйте чуть позже.",
        reply_markup=kb_main(),
    )


@numeric_router.message(F.text.regexp(r"^\d{1,7}$"))
async def on_ati_code(message: Message) -> None:
    """
    Ловим любой текст из 1–7 цифр: это код АТИ.
    Пайплайн:
      1) Проверяем, что runtime инициализирован.
      2) normalize_code -> check (service)
      3) build_report_text (formatter) c порогами из runtime
      4) ответ с kb_after_report()
    При ошибках — мягкий фолбэк на kb_main().
    """
    if _runtime.checker is None:
        await _not_ready_reply(message)
        return

    try:
        raw = (message.text or "").strip()
        code = _runtime.checker.normalize_code(raw)
        res = _runtime.checker.check(code)
        report = build_report_text(code, res, _runtime.lin_ok, _runtime.exp_ok)
        await message.answer(report, reply_markup=kb_after_report())
    except Exception:
        # не раскрываем деталей пользователю
        await message.answer(
            "Не удалось выполнить проверку. Попробуйте ещё раз.",
            reply_markup=kb_main(),
        )
