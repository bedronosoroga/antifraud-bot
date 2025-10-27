from __future__ import annotations

from app.config import cfg


def _plural(n: int, one: str, few: str, many: str) -> str:
    """
    Русские склонения: "1 день / 2 дня / 5 дней", работает для любых слов.
    """

    n_abs = abs(n)
    if 11 <= n_abs % 100 <= 14:
        return many
    tail = n_abs % 10
    if tail == 1:
        return one
    if tail in {2, 3, 4}:
        return few
    return many


def fmt_rub(amount: int) -> str:
    """
    Возвращает '299 ₽' без разделителей тысяч.
    """

    return f"{amount} ₽"


def bullet_list(items: list[str]) -> str:
    """
    Склеивает список строк в маркированный список с '• '. Пустые элементы игнорируются.
    """

    filtered = [item for item in items if item and item.strip()]
    return "\n".join(f"• {line}" for line in filtered)


def fmt_percent(numerator: int, denominator: int) -> str:
    """
    Безопасное деление, округление до целых.
    Примеры:
    >>> fmt_percent(0, 20)
    '0%'
    >>> fmt_percent(3, 20)
    '15%'
    >>> fmt_percent(20, 20)
    '100%'
    """

    if denominator <= 0:
        return "0%"
    numerator = max(numerator, 0)
    if numerator == 0:
        return "0%"
    percent = round(100 * numerator / denominator)
    return f"{percent}%"


def progress_bar(used: int, total: int, blocks: int = 5) -> str:
    """
    Рисует бар ▰/▱ по факту used/total.
    - total <= 0 -> считаем total = 1, used = min(used, 1)
    - used < 0 -> 0; used > total -> total
    Всегда 0..blocks заполненных ▰.
    Примеры:
    >>> progress_bar(0, 20, 5)
    '▱▱▱▱▱'
    >>> progress_bar(10, 20, 5)
    '▰▰▰▱▱'
    >>> progress_bar(20, 20, 5)
    '▰▰▰▰▰'
    """

    if blocks <= 0:
        raise ValueError("blocks must be positive")
    if total <= 0:
        total = 1
        used = min(used, 1)
    used = max(0, min(used, total))
    if used == 0:
        filled = 0
    else:
        filled = -(-used * blocks // total)
    filled = min(filled, blocks)
    empty = blocks - filled
    return "▰" * filled + "▱" * empty


# Действия
ACTION_BTN_CHECK = "Ещё проверка"
ACTION_BTN_HISTORY = "История"
ACTION_BTN_MENU = "В меню"

# Навигация
BTN_BACK = "Назад"
BTN_MENU = ACTION_BTN_MENU
BTN_MORE = "Дальше"

# Покупка/оплата
BTN_BUY_P20 = "Купить 20"
BTN_BUY_P50 = "Купить 50"
BTN_BUY_UNLIM = "Купить Безлимит"
BTN_REPEAT_PAYMENT = "Повторить оплату"
BTN_CHOOSE_ANOTHER_PLAN = "Выбрать другой план"
BTN_PAY_SUPPORT = "В поддержку"

# Поддержка/FAQ
BTN_SUPPORT = "Написать нам"
BTN_FAQ = "FAQ"

# Рефералка
BTN_MY_REF_LINK = "Моя ссылка"
BTN_HOW_IT_WORKS = "Как это работает"
BTN_REF_COPY = "Скопировать"
BTN_REF_SHARE = "Поделиться"
BTN_REF_SPEND_20 = "Купить 20 из баланса"
BTN_REF_SPEND_50 = "Купить 50 из баланса"
BTN_REF_SPEND_UNLIM = "Купить Безлимит из баланса"
BTN_REF_WITHDRAW = "Вывод"

# Компания АТИ
BTN_WHY_ASK = "Почему спрашиваем?"
BTN_SET_LATER = "Указать позже"
BTN_SET_NOW = "Указать"
BTN_CHANGE_CODE = "Изменить код"
BTN_CHECK_THIS_CODE = "Проверить этот код"


def hint_send_code() -> str:
    """Главная подсказка."""

    return "🔎 Пришлите код АТИ (до 7 цифр) — ответим сразу."


def invalid_input_non_digits() -> str:
    """Сообщает о необходимости прислать только цифры."""

    return "Похоже, это не цифры. Отправьте только номер."


def err_need_digits_3_7() -> str:
    """Сообщает о неверной длине кода."""

    return "Нужно до 7 цифр. Попробуйте ещё раз."


def too_many_requests() -> str:
    """Сообщение о превышении частоты запросов."""

    return "Слишком часто. Попробуйте чуть позже."


def throttle_msg(seconds: int) -> str:
    """С учётом склонения."""

    unit = _plural(seconds, "секунду", "секунды", "секунд")
    return f"Подождите {seconds} {unit} перед следующей проверкой."


def plans_list() -> str:
    """
    Список планов по cfg.plans: p20(299), p50(469), unlim(799, cap).
    Формат: 'Доступные планы:\n• 20 проверок — 299 ₽/мес\n...'
    """

    plan_p20 = cfg.plans.get("p20")
    plan_p50 = cfg.plans.get("p50")
    plan_unlim = cfg.plans.get("unlim")

    lines: list[str] = []
    if plan_p20 is not None:
        lines.append(f"20 проверок — {fmt_rub(plan_p20.price_rub)}/мес")
    if plan_p50 is not None:
        lines.append(f"50 проверок — {fmt_rub(plan_p50.price_rub)}/мес")
    if plan_unlim is not None:
        cap_suffix = f" (до {plan_unlim.daily_cap} в сутки)" if plan_unlim.daily_cap else ""
        lines.append(f"Безлимит — {fmt_rub(plan_unlim.price_rub)}/мес{cap_suffix}")

    body = bullet_list(lines)
    return f"Доступные планы:\n{body}" if body else "Доступные планы:"


def paywall_no_checks() -> str:
    """Сообщение о нулевом остатке проверок."""

    return "Проверок не осталось.\n\n" + plans_list()


def payment_success(expires_date: str, extra_tail: str = "") -> str:
    """
    'Оплата прошла ✔ Подписка действует до: {expires_date}. Остаток обновлён.'
    Если extra_tail не пуст — добавить новой строкой.
    """

    base = f"Оплата прошла ✔ Подписка действует до: {expires_date}. Остаток обновлён."
    if extra_tail:
        return base + "\n" + extra_tail
    return base


def payment_incomplete() -> str:
    """Сообщение о незавершённом платеже."""

    return "Платёж не завершён. Что делаем?"


def payment_timeout() -> str:
    """Сообщение о неподтверждённом платеже."""

    return "Платёж не подтверждён."


def payment_failed_try_again() -> str:
    """Сообщение о неудачной оплате."""

    return "Оплата не прошла. Попробуйте ещё раз или выберите другой способ."


def refund_processed() -> str:
    """Сообщение о завершённом возврате."""

    return "Возврат оформлен. Срок и остаток скорректированы."


def free_pack_status(left: int, until: str) -> str:
    """'Бесплатно осталось: {left} • До: {until}'."""

    return f"Бесплатно осталось: {left} • До: {until}"


def nudge_enter_code() -> str:
    """Напоминание отправить код АТИ."""

    return "Просто пришлите номер АТИ — проверим сразу."


def free_expiring_24h(left: int, until: str) -> str:
    """Сообщение о скором завершении бесплатных проверок."""

    return f"Ещё есть бесплатные: {left}. До завершения: {until}. Пришлите код — проверим сейчас."


def free_low_left(left: int) -> str:
    """Сообщение о малом остатке бесплатных проверок."""

    word = _plural(left, "бесплатная проверка", "бесплатные проверки", "бесплатных проверок")
    return f"Осталось: {left} {word}. Успейте использовать."


def payment_abandoned() -> str:
    """Напоминание о брошенном платеже."""

    return "Платёж не завершён. Вернуться и закончить?"


def inactive_with_active_subscription(days: int) -> str:
    """Сообщение о неактивности при активной подписке."""

    unit = _plural(days, "день", "дня", "дней")
    return f"У вас активная подписка, но {days} {unit} без проверок. Пришлите код — проверим."


def winback_no_activity(days: int) -> str:
    """Возврат пользователей после простоя."""

    unit = _plural(days, "день", "дня", "дней")
    return f"Давно не заходили ({days} {unit}). Напомнить планы?\n" + plans_list()


def unlim_cap_hit_today(cap: int) -> str:
    """
    Сообщение об исчерпании суточного лимита безлимита.
    cap <= 0 -> универсальная фраза без '0/сутки'.
    """

    if cap > 0:
        return f"Дневной лимит {cap} в сутки исчерпан. Счётчик обновится завтра."
    return "Безлимит на сегодня исчерпан. Счётчик обновится завтра."


def status_line_metered_exact(
    plan_title: str,
    used: int,
    total: int,
    expires_date: str,
    bar_blocks: int = 5,
) -> str:
    """
    'Подписка: {plan_title} • Осталось: {left}/{total} ({pct_left}) • Действует до: {expires_date}\n{bar}'
    где left = max(0, total - used); pct_left = fmt_percent(left, total);
    bar = progress_bar(used_clamped, total_clamped, bar_blocks).
    Doctest:
    >>> s = status_line_metered_exact("50", used=10, total=50, expires_date="24.11")
    >>> "Осталось: 40/50" in s and "(80%)" in s
    True
    """

    left = max(0, total - used)
    pct_left = fmt_percent(left, total)
    total_clamped = total if total > 0 else 0
    if total_clamped > 0:
        used_clamped = max(0, min(used, total_clamped))
    else:
        used_clamped = max(0, used)
    bar = progress_bar(used_clamped, total_clamped, bar_blocks)
    return (
        f"Подписка: {plan_title} • Осталось: {left}/{total} ({pct_left}) • "
        f"Действует до: {expires_date}\n{bar}"
    )


def profile_overview_metered_exact(plan_title: str, used: int, total: int, expires_date: str) -> str:
    """
    'Подписка: {plan_title}\nОсталось: {left}/{total} ({pct_left})\nДействует до: {expires_date}'
    """

    left = max(0, total - used)
    pct_left = fmt_percent(left, total)
    return (
        f"Подписка: {plan_title}\n"
        f"Осталось: {left}/{total} ({pct_left})\n"
        f"Действует до: {expires_date}"
    )


def status_line_unlim(today_used: int, cap: int | None, expires_date: str, bar_blocks: int = 5) -> str:
    """
    При cap>0: 'Безлимит: до {cap}/сутки • Сегодня: {today_used}/{cap} ({pct}) • Действует до: {expires_date}\n{bar}'
    При cap<=0/None: 'Безлимит • Сегодня: {today_used} • Действует до: {expires_date}\n{bar}' (bar по 1).
    Doctest:
    >>> "Сегодня: 10/50 (20%)" in status_line_unlim(10, 50, "24.11")
    True
    >>> "0/сутки" in status_line_unlim(10, 0, "24.11")
    False
    """

    if cap and cap > 0:
        used_clamped = max(0, min(today_used, cap))
        pct = fmt_percent(used_clamped, cap)
        bar = progress_bar(used_clamped, cap, bar_blocks)
        return (
            f"Безлимит: до {cap}/сутки • Сегодня: {used_clamped}/{cap} ({pct}) • "
            f"Действует до: {expires_date}\n{bar}"
        )
    used_clamped = max(0, today_used)
    bar = progress_bar(used_clamped, 1, bar_blocks)
    return f"Безлимит • Сегодня: {used_clamped} • Действует до: {expires_date}\n{bar}"


def profile_overview_unlim(today_used: int, cap: int | None, expires_date: str) -> str:
    """
    'Подписка: Безлимит{cap_suffix}\nСегодня: {today_used}{den}\nДействует до: {expires_date}'
    где cap_suffix = ' (до {cap}/сутки)' при cap>0, иначе пусто; den = '/{cap}' при cap>0, иначе пусто.
    """

    if cap and cap > 0:
        cap_suffix = f" (до {cap}/сутки)"
        denominator = f"/{cap}"
    else:
        cap_suffix = ""
        denominator = ""
    return (
        f"Подписка: Безлимит{cap_suffix}\n"
        f"Сегодня: {today_used}{denominator}\n"
        f"Действует до: {expires_date}"
    )


def ref_header() -> str:
    """Заголовок реферального раздела."""

    return "Пригласить и заработать"


def ref_link_block(link: str) -> str:
    """Блок с реферальной ссылкой."""

    return f"Ваша ссылка:\n{link}\n\nСкопируйте и отправьте друзьям."


def ref_level_block(level: int, percent: int, to_next: int | None) -> str:
    """
    'Ваш уровень: {level} • Вознаграждение: {percent}%'
    Если to_next задан: 'До следующего уровня осталось: {to_next} оплата/оплаты/оплат'
    """

    base = f"Ваш уровень: {level} • Вознаграждение: {percent}%"
    if to_next is None:
        return base
    word = _plural(to_next, "оплата", "оплаты", "оплат")
    return f"{base}\nДо следующего уровня осталось: {to_next} {word}"


def ref_earnings_block(accrued_rub: int, pending_rub: int) -> str:
    """Возвращает строку с балансом реферальных начислений."""

    return f"Зачислено: {fmt_rub(accrued_rub)} • Ожидает: {fmt_rub(pending_rub)}"


def ref_spend_withdraw_block() -> str:
    """Подсказка, куда потратить или вывести средства."""

    return (
        "Куда потратить:\n"
        "— Купить 20 из баланса\n"
        "— Купить 50 из баланса\n"
        "— Купить Безлимит из баланса\n\n"
        "Вывод средств"
    )


def ref_how_it_works() -> str:
    """Описание механики реферальной программы."""

    hold = getattr(cfg, "ref_hold_days", 3)
    return (
        "Как это работает:\n"
        "• Делитесь вашей ссылкой.\n"
        "• Друг оплачивает подписку.\n"
        f"• Мы начисляем % на ваш баланс (доступно через {hold} дн.).\n"
        "• Процент растёт по мере количества оплат ваших приглашённых."
    )


def ref_levels_table() -> str:
    """Таблица уровней и процентов."""

    return (
        "Уровни:\n"
        "• 0–2 оплат — 10%\n"
        "• 3–9 — 20%\n"
        "• 10–24 — 30%\n"
        "• 25–49 — 40%\n"
        "• ≥50 — 50%"
    )


def wallet_only_in_referral_notice() -> str:
    """Напоминание, что оплата из баланса доступна только в рефералке."""

    return "Оплата из баланса доступна только в разделе «Пригласить и заработать»."


def ref_balance_only_here_notice() -> str:
    """Алиас для совместимости."""

    return wallet_only_in_referral_notice()


def company_ati_ask() -> str:
    """Запрос указать код АТИ компании."""

    return (
        "Оплата прошла ✔\n\n"
        "Укажите код АТИ вашей компании (до 7 цифр).\n"
        "Это нужно один раз, чтобы ускорить поддержку."
    )


def company_ati_why() -> str:
    """Объяснение, зачем нужен код компании."""

    return (
        "Чтобы быстрее помогать вам по вопросам компании и подписки. Код АТИ видим только мы. "
        "Вы можете изменить его в настройках в любой момент."
    )


def company_ati_saved(ati: str) -> str:
    """Подтверждение сохранения кода компании."""

    return f"Готово, код АТИ компании сохранён: {ati}. Изменить можно в Профиль → Настройки."


def company_ati_later() -> str:
    """Сообщение, что код можно указать позже."""

    return "Хорошо, напомним позже. Указать можно в Профиль → Настройки."


def company_ati_banner_not_set() -> str:
    """Баннер о том, что код не указан."""

    return "Код АТИ компании не указан. [Указать]"


def company_ati_change_confirm(new_code: str) -> str:
    """Подтверждение изменения кода компании."""

    return f"Уверены, что хотите изменить код на {new_code}?"


def history_header() -> str:
    """Заголовок истории проверок."""

    return "История проверок"


def history_item_line(status_emoji: str, ati: str, dt: str) -> str:
    """Возвращает строку для записи истории."""

    return f"{status_emoji} {ati} • {dt}"


def history_no_more() -> str:
    """Сообщение об отсутствии дополнительных записей."""

    return "Это всё на сейчас."


def history_empty() -> str:
    """Сообщение о пустой истории."""

    return "Пока нет проверок."


def history_empty_hint() -> str:
    """Подсказка при пустой истории."""

    return "Пока нет проверок.\nПришлите код АТИ (до 7 цифр) — проверим сразу."


def help_main() -> str:
    """Заголовок раздела помощи."""

    return "Помощь"


def faq_text() -> str:
    """Ответы на часто задаваемые вопросы."""

    tz = getattr(cfg, "tz", "Europe/Moscow")
    return (
        "Вопросы и ответы:\n"
        "• Как сделать проверку? — Пришлите код АТИ (до 7 цифр) в чат, и мы сразу дадим отчёт.\n"
        "• Что делать, если проверок не осталось? — Выберите и оплатите план. Всё занимает минуту.\n"
        "• Как работают бесплатные проверки? — Новым пользователям выдаётся 5 проверок на 3 дня.\n"
        f"• Как работает безлимит? — До 50 проверок в сутки, счётчик обнуляется в 00:00 ({tz}).\n"
        "• Как оплатить из баланса? — Это возможно только в разделе «Пригласить и заработать».\n"
        "• Как изменить код АТИ компании? — Профиль → Настройки."
    )


def support_pretext() -> str:
    """Подсказка обратиться в поддержку."""

    return "Если остались вопросы — напишите нам."


def report_a(ati: str, lin: int, exp: int, tail: str) -> str:
    """Общий отчёт с позитивным результатом."""

    return (
        f"🟢 Код АТИ {ati} успешно прошёл проверку.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: риск не выявлен \n\n"
        f"{tail}"
    )


def report_b(ati: str, lin: int, exp: int) -> str:
    """Общий отчёт с повышенным риском."""

    return (
        f"🟡 Код АТИ {ati} обнаружен в нашем реестре проверок.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: ⁉️ Повышенный риск\n\n"
        "По данным нашей аналитики, есть риски. Оценка субъективна и может быть изменена при появлении благоприятных признаков."
    )


def report_c(ati: str, lin: int, exp: int) -> str:
    """Общий отчёт с нейтральным результатом."""

    return (
        f"🟡 Код АТИ {ati} проверен.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: не выявлен риск\n\n"
        "Подтверждений по реестрам мало — это не негатив, но истории нет."
    )


def report_d(ati: str, lin: int, exp: int) -> str:
    """Общий отчёт с критическим риском."""

    return (
        f"🔴 Код АТИ {ati} не прошёл проверку.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: ⛔️ Критический риск \n\n"
        "По данным нашей аналитики, есть риски. Оценка субъективна и может быть изменена при появлении благоприятных признаков."
    )


def report_e(ati: str) -> str:
    """Общий отчёт об отсутствии данных."""

    return (
        f"🟡 Код АТИ {ati} не обнаружен в наших реестрах.\n\n"
        "📈 Индекс перевозчика: 0\n"
        "📈 Индекс экспедитора: 0\n\n"
        "🛡 Чёрные списки: не выявлен риск\n\n"
        "Подтверждений по реестрам не обнаружено — это не негатив, но истории нет."
    )


__all__ = [
    # helpers
    "progress_bar", "fmt_rub", "bullet_list", "fmt_percent",
    # buttons
    "ACTION_BTN_CHECK", "ACTION_BTN_HISTORY", "ACTION_BTN_MENU",
    "BTN_BACK", "BTN_MENU", "BTN_MORE",
    "BTN_BUY_P20", "BTN_BUY_P50", "BTN_BUY_UNLIM",
    "BTN_REPEAT_PAYMENT", "BTN_CHOOSE_ANOTHER_PLAN",
    "BTN_PAY_SUPPORT", "BTN_SUPPORT", "BTN_FAQ",
    "BTN_MY_REF_LINK", "BTN_HOW_IT_WORKS",
    "BTN_REF_COPY", "BTN_REF_SHARE",
    "BTN_REF_SPEND_20", "BTN_REF_SPEND_50", "BTN_REF_SPEND_UNLIM", "BTN_REF_WITHDRAW",
    "BTN_WHY_ASK", "BTN_SET_LATER", "BTN_SET_NOW", "BTN_CHANGE_CODE", "BTN_CHECK_THIS_CODE",
    # basics/errors
    "hint_send_code", "invalid_input_non_digits", "err_need_digits_3_7",
    "too_many_requests", "throttle_msg",
    # plans/payments
    "plans_list", "paywall_no_checks", "payment_success",
    "payment_incomplete", "payment_timeout", "payment_failed_try_again", "refund_processed",
    # free/reactivation
    "free_pack_status", "nudge_enter_code", "free_expiring_24h",
    "free_low_left", "payment_abandoned", "inactive_with_active_subscription",
    "winback_no_activity", "unlim_cap_hit_today",
    # status/profile
    "status_line_metered_exact", "profile_overview_metered_exact",
    "status_line_unlim", "profile_overview_unlim",
    # referral
    "ref_header", "ref_link_block", "ref_level_block", "ref_earnings_block",
    "ref_spend_withdraw_block", "ref_how_it_works", "ref_levels_table",
    "wallet_only_in_referral_notice", "ref_balance_only_here_notice",
    # company ati
    "company_ati_ask", "company_ati_why", "company_ati_saved",
    "company_ati_later", "company_ati_banner_not_set", "company_ati_change_confirm",
    # history/help
    "history_header", "history_item_line", "history_no_more", "history_empty", "history_empty_hint",
    "help_main", "faq_text", "support_pretext",
    # reports
    "report_a", "report_b", "report_c", "report_d", "report_e",
]
