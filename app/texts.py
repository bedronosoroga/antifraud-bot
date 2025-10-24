from __future__ import annotations

from app.config import cfg

_FILLED_BLOCK = "▰"
_EMPTY_BLOCK = "▱"


def progress_bar(current: int, total: int, blocks: int = 5) -> str:
    """Draw a progress bar using filled and empty square blocks."""

    if blocks <= 0:
        return ""
    if total <= 0:
        return _EMPTY_BLOCK * blocks

    capped_total = total
    clamped_current = max(0, min(current, capped_total))

    if clamped_current == 0:
        filled_blocks = 0
    else:
        numerator = clamped_current * blocks
        filled_blocks = (numerator + capped_total - 1) // capped_total
        filled_blocks = max(1, filled_blocks)
    filled_blocks = min(filled_blocks, blocks)
    return _FILLED_BLOCK * filled_blocks + _EMPTY_BLOCK * (blocks - filled_blocks)


def fmt_percent(numerator: int, denominator: int) -> str:
    """
    Возвращает '0%'..'100%'. Деление с защитой от 0, округление до целых.
    Примеры:
    >>> fmt_percent(0, 20)
    '0%'
    >>> fmt_percent(3, 20)
    '15%'
    >>> fmt_percent(20, 20)
    '100%'
    """

    safe_denominator = max(denominator, 1)
    pct = round(max(0, numerator) * 100 / safe_denominator)
    pct = max(0, min(100, pct))
    return f"{pct}%"


def hint_send_code() -> str:
    """Return the main screen prompt."""

    return "🔎 Пришлите код АТИ (3–7 цифр) — ответим сразу."


def history_empty() -> str:
    """Return the empty history message."""

    return "Пока нет проверок."


def unlim_cap_reached() -> str:
    """
    Return a message for reaching the unlimited plan daily cap.

    >>> isinstance(unlim_cap_reached(), str)
    True
    """

    cap = getattr(cfg.plans.get("unlim", None), "daily_cap", None)
    if cap:
        return f"Дневной лимит {cap}/сутки достигнут. Можно снова завтра после 00:00."
    return "Дневной лимит на сегодня достигнут. Можно снова завтра после 00:00."


def _heuristic_metered_bar(left: int, blocks: int) -> str:
    """
    DEPRECATED: не использовать. Каноничная визуализация — только по used/total.

    Рисуем бар по остаточному принципу.

    >>> _heuristic_metered_bar(0, 5)
    '▱▱▱▱▱'
    >>> _heuristic_metered_bar(100, 5)
    '▰▰▰▰▰'
    """

    blocks = max(1, blocks)
    if left <= 0:
        filled = 0
    else:
        pct = max(0, min(left, 100)) / 100.0
        filled = max(1, min(blocks, int(round(pct * blocks))))
    return _FILLED_BLOCK * filled + _EMPTY_BLOCK * (blocks - filled)


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    """
    Русские склонения по числу.
    forms = ("секунду", "секунды", "секунд") / ("день", "дня", "дней")
    """

    n = abs(int(n)) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        return forms[2]
    if n1 == 1:
        return forms[0]
    if 2 <= n1 <= 4:
        return forms[1]
    return forms[2]


def status_line_metered_exact(
    plan_title: str,
    used: int,
    total: int,
    expires_date: str,
    bar_blocks: int = 5,
) -> str:
    """
    Каноничная версия статуса для пакетных планов на основе used/total.

    >>> s = status_line_metered_exact("50", used=10, total=50, expires_date="24.11")
    >>> "Осталось: 40/50" in s and "(" in s and "%)" in s
    True
    """

    total_int = int(total)
    used_int = int(used)

    total_clamped = max(total_int, 1)
    used_upper_bound = total_int if total_int > 0 else 1
    used_clamped = min(max(used_int, 0), used_upper_bound)

    left_raw = total_int - used_int
    left = max(0, left_raw)
    if total_int > 0:
        left = min(left, total_int)
    else:
        left = 0

    left_for_percent = max(0, total_clamped - used_clamped)
    pct_left = fmt_percent(left_for_percent, total_clamped)
    bar = progress_bar(used_clamped, total_clamped, bar_blocks)

    total_display = max(total_int, 0)
    left_display = left if total_display > 0 else 0

    return (
        "Подписка: "
        f"{plan_title} • Осталось: {left_display}/{total_display} ({pct_left}) • Действует до: {expires_date}\n{bar}"
    )


def status_line_metered(
    plan_title: str,
    left: int,
    expires_date: str,
    bar_blocks: int = 5,
    total: int | None = None,
) -> str:
    """
    DEPRECATED: используйте status_line_metered_exact(..., used, total, ...).
    Если total передан: считаем used = max(0, total - left) и делегируем в status_line_metered_exact.
    Если total не передан: делаем безопасный фоллбэк — считаем total=left, used=0 (весь объём впереди),
    бар и проценты будут корректны (100% осталось), без эвристик.
    """

    left_int = max(0, int(left))
    if total is not None:
        total_int = int(total)
        used = max(0, total_int - left_int)
        return status_line_metered_exact(
            plan_title=plan_title,
            used=used,
            total=total_int,
            expires_date=expires_date,
            bar_blocks=bar_blocks,
        )

    total_int = left_int
    return status_line_metered_exact(
        plan_title=plan_title,
        used=0,
        total=total_int,
        expires_date=expires_date,
        bar_blocks=bar_blocks,
    )


def status_line_unlim(today_used: int, cap: int, expires_date: str, bar_blocks: int = 5) -> str:
    """
    >>> a = status_line_unlim(10, 50, "24.11")
    >>> "Сегодня: 10/50 (20%)" in a
    True
    >>> b = status_line_unlim(10, 0, "24.11")
    >>> "0/сутки" in b
    False
    """

    safe_today = max(0, today_used)
    if cap and cap > 0:
        cap_int = int(cap)
        today_clamped = min(safe_today, cap_int)
        bar = progress_bar(today_clamped, cap_int, bar_blocks)
        pct = fmt_percent(safe_today, cap_int)
        return (
            "Безлимит: "
            f"до {cap_int}/сутки • Сегодня: {safe_today}/{cap_int} ({pct}) • Действует до: {expires_date}\n{bar}"
        )
    bar = progress_bar(safe_today, 1, bar_blocks)
    return f"Безлимит • Сегодня: {safe_today} • Действует до: {expires_date}\n{bar}"


def fmt_rub(amount: int) -> str:
    """Format an integer amount of rubles."""

    return f"{amount} ₽"


def bullet_list(items: list[str]) -> str:
    """Join items into a bullet list string."""

    filtered = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"• {item}" for item in filtered)


def plans_list() -> str:
    """Return a short list of subscription plans."""

    lines = ["Месячные планы:"]
    plan_p20 = cfg.plans.get("p20")
    plan_p50 = cfg.plans.get("p50")
    plan_unlim = cfg.plans.get("unlim")

    if plan_p20 and plan_p20.checks_in_pack:
        lines.append(f"• {plan_p20.checks_in_pack} — {fmt_rub(plan_p20.price_rub)}")
    if plan_p50 and plan_p50.checks_in_pack:
        lines.append(f"• {plan_p50.checks_in_pack} — {fmt_rub(plan_p50.price_rub)}")
    if plan_unlim:
        caption = f"• {plan_unlim.title} — {fmt_rub(plan_unlim.price_rub)}"
        if plan_unlim.daily_cap:
            caption += f" (до {plan_unlim.daily_cap}/сутки)"
        lines.append(caption)

    return "\n".join(lines)


def paywall_no_checks() -> str:
    """Return the paywall text when no checks remain."""

    return "Проверок не осталось.\n\n" + plans_list()


def payment_success(expires_date: str, extra_tail: str = "") -> str:
    """Return the payment success message."""

    base = f"Оплата прошла ✔ Подписка до: {expires_date}. Остаток обновлён."
    if extra_tail:
        base = f"{base}\n{extra_tail}"
    return base


def payment_incomplete() -> str:
    """Return the payment incomplete message."""

    return "Платёж не завершён. Что делаем?"


def payment_timeout() -> str:
    """Return the payment timeout message."""

    return "Платёж не подтверждён."


def free_pack_status(left: int, until: str) -> str:
    """Return the free pack status line."""

    return f"Бесплатно осталось: {left} • До: {until}"


def ref_promo_short() -> str:
    """Return a short referral promo block."""

    return (
        "Хотите платить меньше? Пригласите друга — получите до 50% от его подписок.\n"
        "[Моя ссылка]  [Как это работает]"
    )


def company_ati_ask() -> str:
    """Ask the user to provide their company ATI code."""

    return (
        "Оплата прошла ✔\n\n"
        "Укажите код АТИ вашей компании (3–7 цифр).\n"
        "Это нужно один раз, чтобы ускорить поддержку."
    )


def company_ati_why() -> str:
    """Explain why the ATI code is requested."""

    return (
        "Чтобы быстрее помогать вам по вопросам компании и подписки. Код АТИ видим только мы. "
        "Вы можете изменить его в настройках в любой момент."
    )


def company_ati_saved(ati: str) -> str:
    """Confirm that the company ATI code has been saved."""

    return (
        f"Готово, код АТИ компании сохранён: {ati}. Изменить можно в Профиль → Настройки."
    )


def company_ati_later() -> str:
    """Acknowledge that the user will provide the ATI code later."""

    return "Хорошо, напомним позже. Указать можно в Профиль → Настройки."


def err_need_digits_3_7() -> str:
    """Return an error message when the ATI code length is invalid."""

    return "Нужно от 3 до 7 цифр. Попробуйте ещё раз."


def report_a(ati: str, lin: int, exp: int, tail: str) -> str:
    """Return the green report variant."""

    return (
        f"🟢 Код АТИ {ati} успешно прошёл проверку.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: риск не выявлен\n\n"
        f"{tail}"
    )


def report_b(ati: str, lin: int, exp: int) -> str:
    """Return the yellow report with elevated risk."""

    return (
        f"🟡 Код АТИ {ati} обнаружен в нашем реестре проверок.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: ⁉️ Повышенный риск\n\n"
        "По данным нашей аналитики, есть риски. Оценка субъективна и может быть изменена при появлении "
        "благоприятных признаков."
    )


def report_c(ati: str, lin: int, exp: int) -> str:
    """Return the yellow report variant with scarce data."""

    return (
        f"🟡 Код АТИ {ati} проверен.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: не выявлен риск\n\n"
        "Подтверждений по реестрам мало — это не негатив, но истории нет."
    )


def report_d(ati: str, lin: int, exp: int) -> str:
    """Return the red report variant with critical risk."""

    return (
        f"🔴 Код АТИ {ati} не прошёл проверку.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: ⛔️ Критический риск\n\n"
        "По данным нашей аналитики, есть риски. Оценка субъективна и может быть изменена при появлении "
        "благоприятных признаков."
    )


def report_e(ati: str) -> str:
    """Return the yellow report variant for unknown codes."""

    return (
        f"🟡 Код АТИ {ati} не обнаружен в наших реестрах.\n\n"
        "📈 Индекс перевозчика: 0\n"
        "📈 Индекс экспедитора: 0\n\n"
        "🛡 Чёрные списки: не выявлен риск\n\n"
        "Подтверждений по реестрам не обнаружено — это не негатив, но истории нет."
    )


ACTION_BTN_CHECK = "Ещё проверка"
ACTION_BTN_HISTORY = "История"
ACTION_BTN_MENU = "В меню"

BTN_BUY_P20 = "Купить 20"
BTN_BUY_P50 = "Купить 50"
BTN_BUY_UNLIM = "Купить Безлимит"

BTN_SUPPORT = "Написать нам"
BTN_PAY_SUPPORT = "В поддержку"
BTN_REPEAT_PAYMENT = "Повторить оплату"
BTN_CHOOSE_ANOTHER_PLAN = "Выбрать другой план"

BTN_MY_REF_LINK = "Моя ссылка"
BTN_HOW_IT_WORKS = "Как это работает"

BTN_BACK = "Назад"
# алиас для обратной совместимости
BTN_MENU = ACTION_BTN_MENU
BTN_MORE = "Дальше"

BTN_REF_COPY = "Скопировать"
BTN_REF_SHARE = "Поделиться"
BTN_REF_SPEND_20 = "Купить 20 из баланса"
BTN_REF_SPEND_50 = "Купить 50 из баланса"
BTN_REF_SPEND_UNLIM = "Купить Безлимит из баланса"
BTN_REF_WITHDRAW = "Вывод"

BTN_FAQ = "FAQ"

BTN_WHY_ASK = "Почему спрашиваем?"
BTN_SET_LATER = "Указать позже"
BTN_SET_NOW = "Указать"
BTN_CHANGE_CODE = "Изменить код"
BTN_CHECK_THIS_CODE = "Проверить этот код"


def ref_header() -> str:
    """Return the referral section header."""

    return "Пригласить и заработать"


def ref_link_block(link: str) -> str:
    """Return the referral link block."""

    return f"Ваша ссылка:\n{link}\n\nСкопируйте и отправьте друзьям."


def ref_level_block(level: int, percent: int, to_next: int | None) -> str:
    """Return the referral level block."""

    base = f"Ваш уровень: {level} • Вознаграждение: {percent}%"
    if to_next is not None:
        base = f"{base}\nДо следующего уровня осталось: {to_next} оплат"
    return base


def ref_earnings_block(accrued_rub: int, pending_rub: int) -> str:
    """Return the referral earnings block."""

    return f"Зачислено: {fmt_rub(accrued_rub)} • Ожидает: {fmt_rub(pending_rub)}"


def ref_spend_withdraw_block() -> str:
    """Return the referral spend/withdraw block."""

    return (
        "Куда потратить:\n"
        "— Купить 20 из баланса\n"
        "— Купить 50 из баланса\n"
        "— Купить Безлимит из баланса\n\n"
        "Вывод средств"
    )


def ref_how_it_works() -> str:
    """Return the referral how-it-works explanation."""

    steps = [
        "Делитесь вашей ссылкой.",
        "Друг оплачивает подписку.",
        "Мы начисляем % на ваш баланс.",
        "Начисления становятся доступными через 3 дня (если не было возврата).",
        "Процент растёт по мере количества оплат ваших приглашённых.",
    ]
    return "Как это работает:\n" + bullet_list(steps)


def ref_levels_table() -> str:
    """Return the referral levels table."""

    levels = [
        "0–2 оплат — 10%",
        "3–9 — 20%",
        "10–24 — 30%",
        "25–49 — 40%",
        "≥50 — 50%",
    ]
    return "Уровни:\n" + bullet_list(levels)


def ref_balance_only_here_notice() -> str:
    """Алиас для notice об оплате из баланса в реферальном разделе."""

    return wallet_only_in_referral_notice()


def history_header() -> str:
    """Return the history section header."""

    return "История проверок"


def history_item_line(status_emoji: str, ati: str, dt: str) -> str:
    """Return a formatted history item line."""

    return f"{status_emoji} {ati} • {dt}"


def history_no_more() -> str:
    """Return the history end marker."""

    return "Это всё на сейчас."


def history_empty_hint() -> str:
    """Return the empty history hint message."""

    return "Пока нет проверок.\nПришлите код АТИ (3–7 цифр) — проверим сразу."


def help_main() -> str:
    """Return the help section header."""

    return "Помощь"


def faq_text() -> str:
    """
    Return the FAQ text.

    >>> t = faq_text()
    >>> "(" in t and ")" in t  # в тексте должен быть скобочный TZ из cfg.tz
    True
    """

    qa_items = [
        "Как сделать проверку? — Пришлите код АТИ (3–7 цифр) в чат, и мы сразу дадим отчёт.",
        "Что делать, если проверок не осталось? — Выберите и оплатите план. Всё занимает минуту.",
        "Как работают бесплатные проверки? — Новым пользователям выдаётся 5 проверок на 3 дня.",
        f"Как работает безлимит? — До 50 проверок в сутки, счётчик обнуляется в 00:00 ({cfg.tz}).",
        "Как оплатить из баланса? — Это возможно только в разделе «Пригласить и заработать».",
        "Как изменить код АТИ компании? — Профиль → Настройки.",
    ]
    return "Вопросы и ответы:\n" + bullet_list(qa_items)


def support_pretext() -> str:
    """Return the pre-support message."""

    return "Если остались вопросы — напишите нам."


def nudge_enter_code() -> str:
    """Return a simple reminder to enter an ATI code."""

    return "Просто пришлите номер АТИ — проверим сразу."


def free_expiring_24h(left: int, until: str) -> str:
    """Return a reminder about expiring free checks."""

    return f"Ещё есть бесплатные: {left}. До завершения: {until}. Пришлите код — проверим сейчас."


def free_low_left(left: int) -> str:
    """Return a reminder when few free checks remain."""

    return f"Бесплатных осталось: {left}. Успейте использовать."


def payment_abandoned() -> str:
    """Return a reminder about an unfinished payment."""

    return "Платёж не завершён. Вернуться и закончить?"


def inactive_with_active_subscription(days: int) -> str:
    """Return a reminder about inactivity with an active subscription."""

    return (
        "У вас активная подписка, но "
        f"{days} {_plural(days, ('день', 'дня', 'дней'))} без проверок. Пришлите код — проверим."
    )


def winback_no_activity(days: int) -> str:
    """Return a winback message when there is no activity."""

    head = (
        "Давно не заходили ("
        f"{days} {_plural(days, ('день', 'дня', 'дней'))}). Напомнить планы?"
    )
    return head + "\n" + plans_list()


def unlim_cap_hit_today(cap: int) -> str:
    """Return a notice about hitting the unlimited cap today."""

    return f"Лимит {cap}/сутки достигнут. Можно снова завтра после 00:00."


def profile_overview_metered_exact(plan_title: str, used: int, total: int, expires_date: str) -> str:
    """
    >>> s = profile_overview_metered_exact("20", used=5, total=20, expires_date="24.11")
    >>> "Осталось: 15/20" in s and "%" in s
    True
    """

    total_int = int(total)
    used_int = int(used)

    total_clamped = max(total_int, 1)
    used_clamped = min(max(used_int, 0), total_int if total_int > 0 else 1)
    left_raw = total_int - used_int
    left = max(0, left_raw)
    if total_int > 0:
        left = min(left, total_int)
    else:
        left = 0

    left_for_percent = max(0, total_clamped - used_clamped)
    total_display = max(total_int, 0)
    left_display = left if total_display > 0 else 0
    pct_left = fmt_percent(left_for_percent, total_clamped)

    return (
        "Подписка: "
        f"{plan_title}\nОсталось: {left_display}/{total_display} ({pct_left})\nДействует до: {expires_date}"
    )


def profile_overview_metered(
    plan_title: str,
    left: int,
    expires_date: str,
    total: int | None = None,
) -> str:
    """
    DEPRECATED: используйте profile_overview_metered_exact(..., used, total, ...).
    Если total передан: used = max(0, total - left) и делегируем.
    Если total не передан: total=left, used=0 (весь объём впереди).
    """

    left_int = max(0, int(left))
    if total is not None:
        total_int = int(total)
        used = max(0, total_int - left_int)
        return profile_overview_metered_exact(
            plan_title=plan_title,
            used=used,
            total=total_int,
            expires_date=expires_date,
        )

    total_int = left_int
    return profile_overview_metered_exact(
        plan_title=plan_title,
        used=0,
        total=total_int,
        expires_date=expires_date,
    )


def profile_overview_unlim(today_used: int, cap: int, expires_date: str) -> str:
    """
    Return the profile overview for unlimited plans.

    >>> "Действует до:" in profile_overview_unlim(today_used=5, cap=50, expires_date="24.11")
    True
    """

    cap_suffix = f" (до {cap}/сутки)" if cap and cap > 0 else ""
    today_denominator = f"/{cap}" if cap and cap > 0 else ""
    safe_today = max(0, today_used)
    return (
        f"Подписка: Безлимит{cap_suffix}\n"
        f"Сегодня: {safe_today}{today_denominator}\n"
        f"Действует до: {expires_date}"
    )


def settings_menu(
    notif_payments: bool,
    notif_ref: bool,
    mask_history: bool,
    post_report_action: str,
) -> str:
    """Return the settings menu description."""

    def _on_off(value: bool) -> str:
        return "вкл" if value else "выкл"

    action_map = {
        "check": "Ещё проверка",
        "menu": "В меню",
        ACTION_BTN_CHECK: "Ещё проверка",
        ACTION_BTN_MENU: "В меню",
    }
    action = action_map.get(post_report_action, post_report_action)

    items = [
        f"Уведомления об оплатах: {_on_off(notif_payments)}",
        f"Уведомления о реферальных начислениях: {_on_off(notif_ref)}",
        f"Маскировать коды в истории: {_on_off(mask_history)}",
        f"После отчёта по умолчанию: {action}",
    ]
    return "Настройки:\n" + bullet_list(items)


def settings_changed_ok() -> str:
    """Return the confirmation for updated settings."""

    return "Готово, настройки обновлены."


def company_ati_banner_not_set() -> str:
    """Return the banner shown when company ATI code is missing."""

    return "Код АТИ компании не указан. [Указать]"


def company_ati_change_confirm(new_code: str) -> str:
    """Return the confirmation prompt for changing the ATI code."""

    return f"Уверены, что хотите изменить код на {new_code}?"


def invalid_input_non_digits() -> str:
    """Return an error when the input is not digits."""

    return "Похоже, это не цифры. Отправьте только номер."


def too_many_requests() -> str:
    """Return a rate limiting warning."""

    return "Слишком часто. Попробуйте чуть позже."


def throttle_msg(seconds: int) -> str:
    """
    Return a throttling message with seconds to wait.

    >>> throttle_msg(1).startswith("Подождите 1")
    True
    """

    return (
        "Подождите "
        f"{seconds} {_plural(seconds, ('секунду', 'секунды', 'секунд'))} перед следующей проверкой."
    )


def payment_failed_try_again() -> str:
    """Return a payment failure message."""

    return "Оплата не прошла. Попробуйте ещё раз или выберите другой способ."


def refund_processed() -> str:
    """Return the refund processed message."""

    return "Возврат оформлен. Срок и остаток скорректированы."


def wallet_only_in_referral_notice() -> str:
    """Return the notice about wallet payments availability."""

    return "Оплата из баланса доступна только в разделе «Пригласить и заработать»."


__all__ = [
    "progress_bar",
    "fmt_percent",
    "hint_send_code",
    "history_empty",
    "unlim_cap_reached",
    "status_line_metered_exact",
    "status_line_metered",
    "status_line_unlim",
    "fmt_rub",
    "bullet_list",
    "plans_list",
    "paywall_no_checks",
    "payment_success",
    "payment_incomplete",
    "payment_timeout",
    "free_pack_status",
    "ref_promo_short",
    "company_ati_ask",
    "company_ati_why",
    "company_ati_saved",
    "company_ati_later",
    "err_need_digits_3_7",
    "report_a",
    "report_b",
    "report_c",
    "report_d",
    "report_e",
    "ACTION_BTN_CHECK",
    "ACTION_BTN_HISTORY",
    "ACTION_BTN_MENU",
    "BTN_BUY_P20",
    "BTN_BUY_P50",
    "BTN_BUY_UNLIM",
    "BTN_SUPPORT",
    "BTN_PAY_SUPPORT",
    "BTN_REPEAT_PAYMENT",
    "BTN_CHOOSE_ANOTHER_PLAN",
    "BTN_MY_REF_LINK",
    "BTN_HOW_IT_WORKS",
    "BTN_BACK",
    "BTN_MENU",
    "BTN_MORE",
    "BTN_REF_COPY",
    "BTN_REF_SHARE",
    "BTN_REF_SPEND_20",
    "BTN_REF_SPEND_50",
    "BTN_REF_SPEND_UNLIM",
    "BTN_REF_WITHDRAW",
    "BTN_FAQ",
    "BTN_WHY_ASK",
    "BTN_SET_LATER",
    "BTN_SET_NOW",
    "BTN_CHANGE_CODE",
    "BTN_CHECK_THIS_CODE",
    "ref_header",
    "ref_link_block",
    "ref_level_block",
    "ref_earnings_block",
    "ref_spend_withdraw_block",
    "ref_how_it_works",
    "ref_levels_table",
    "ref_balance_only_here_notice",
    "history_header",
    "history_item_line",
    "history_no_more",
    "history_empty_hint",
    "help_main",
    "faq_text",
    "support_pretext",
    "nudge_enter_code",
    "free_expiring_24h",
    "free_low_left",
    "payment_abandoned",
    "inactive_with_active_subscription",
    "winback_no_activity",
    "unlim_cap_hit_today",
    "profile_overview_metered_exact",
    "profile_overview_metered",
    "profile_overview_unlim",
    "settings_menu",
    "settings_changed_ok",
    "company_ati_banner_not_set",
    "company_ati_change_confirm",
    "invalid_input_non_digits",
    "too_many_requests",
    "throttle_msg",
    "payment_failed_try_again",
    "refund_processed",
    "wallet_only_in_referral_notice",
]
# Экспорт для импортов уровня модуля и авто-подсказок IDE.
