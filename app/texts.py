from __future__ import annotations

from app.config import cfg

_FILLED_BLOCK = "▰"
_EMPTY_BLOCK = "▱"


# === helpers =================================================================

def progress_bar(width: int, filled: int) -> str:
    """Return a square progress bar.

    >>> progress_bar(5, 2)
    '▰▰▱▱▱'
    """

    if width <= 0:
        return ""
    clamped = max(0, min(filled, width))
    empty = width - clamped
    return _FILLED_BLOCK * clamped + _EMPTY_BLOCK * empty


def fmt_percent(used: int, total: int) -> str:
    """Return a safe integer percentage.

    >>> fmt_percent(3, 20)
    '15%'
    """

    safe_total = max(1, total)
    pct = round(max(0, used) * 100 / safe_total)
    pct = max(0, min(100, pct))
    return f"{pct}%"


def fmt_rub(amount: int) -> str:
    """Format rubles with currency sign."""

    return f"{amount} ₽"


def bullet_list(items: list[str]) -> str:
    """Join items into a bullet list.

    >>> bullet_list(['a', 'b'])
    '• a\n• b'
    """

    cleaned = [item.strip() for item in items if item and item.strip()]
    return "\n".join(f"• {item}" for item in cleaned)


def _plural(n: int, forms: tuple[str, str, str]) -> str:
    """Return russian plural form."""

    n = abs(int(n)) % 100
    n1 = n % 10
    if 11 <= n <= 19:
        return forms[2]
    if n1 == 1:
        return forms[0]
    if 2 <= n1 <= 4:
        return forms[1]
    return forms[2]


def _plan_caption(total: int) -> str:
    """Return plan caption by total checks."""

    for plan in cfg.plans.values():
        if getattr(plan, "checks_in_pack", None) == total:
            title = getattr(plan, "title", None)
            if title:
                return str(title)
    if total > 0:
        return f"{total} проверок"
    return "пакет"


# === buttons =================================================================

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


# === generic =================================================================

def invalid_input_non_digits() -> str:
    """Error when digits are expected."""

    return "Похоже, это не цифры. Отправьте только номер."


def err_need_digits_3_7() -> str:
    """ATI code length error."""

    return "Нужно от 3 до 7 цифр. Попробуйте ещё раз."


def too_many_requests() -> str:
    """Rate limiting warning."""

    return "Слишком часто. Попробуйте чуть позже."


def throttle_msg(seconds: int) -> str:
    """Tell user to wait before next check."""

    return (
        "Подождите "
        f"{seconds} {_plural(seconds, ('секунду', 'секунды', 'секунд'))} перед следующей проверкой."
    )


def nudge_enter_code() -> str:
    """Reminder to send the ATI code."""

    return "Просто пришлите номер АТИ — проверим сразу."


# === plans & payments =========================================================

def plans_list() -> str:
    """List current subscription plans."""

    lines: list[str] = ["Месячные планы:"]
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
    """Paywall text when checks are gone."""

    return "Проверок не осталось.\n\n" + plans_list()


def payment_success(expires_date: str, extra_tail: str = "") -> str:
    """Payment success message."""

    base = f"Оплата прошла ✔ Подписка действует до: {expires_date}. Остаток обновлён."
    if extra_tail:
        base = f"{base}\n{extra_tail}"
    return base


def payment_incomplete() -> str:
    """Incomplete payment warning."""

    return "Оплата не прошла. Попробуйте ещё раз — платёж не завершён."


def payment_timeout() -> str:
    """Payment timeout warning."""

    return "Оплата не прошла. Попробуйте ещё раз — платёж не подтвердился вовремя."


def payment_failed_try_again() -> str:
    """Generic payment failure message."""

    return "Оплата не прошла. Попробуйте ещё раз или выберите другой способ."


def payment_abandoned() -> str:
    """Reminder about unfinished payment."""

    return "Оплата не прошла. Попробуйте ещё раз — платёж не завершён."


def refund_processed() -> str:
    """Refund confirmation."""

    return "Возврат оформлен. Срок и остаток скорректированы."


# === free & reactivation ======================================================

def free_pack_status(left: int, expires_date: str) -> str:
    """Show free pack status."""

    return f"Бесплатно осталось: {left} • Действует до: {expires_date}"


def free_expiring_24h(left: int, expires_date: str) -> str:
    """Warn about free checks expiring."""

    return (
        "Ещё есть бесплатные проверки: "
        f"{left}. Действуют до: {expires_date}. Пришлите код — проверим сейчас."
    )


def free_low_left(left: int) -> str:
    """Warn when few free checks remain."""

    return f"Бесплатных осталось: {left}. Успейте использовать."


def inactive_with_active_subscription(days: int) -> str:
    """Notify about inactivity."""

    return (
        "У вас активная подписка, но "
        f"{days} {_plural(days, ('день', 'дня', 'дней'))} без проверок. Пришлите код — проверим."
    )


def winback_no_activity(days: int) -> str:
    """Winback sequence message."""

    head = (
        "Давно не заходили ("
        f"{days} {_plural(days, ('день', 'дня', 'дней'))}). Напомнить планы?"
    )
    return head + "\n" + plans_list()


# === profile & status =========================================================

def _progress_blocks_used(used: int, total: int, width: int) -> int:
    """Return filled blocks for usage bar."""

    safe_total = max(1, total)
    safe_used = max(0, min(used, safe_total))
    if safe_used == 0:
        return 0
    ratio = safe_used / safe_total
    return max(1, min(width, round(ratio * width)))


def status_line_metered_exact(used: int, total: int, expires_date: str) -> str:
    """Return status line for metered plan.

    >>> "Осталось: 5/20" in status_line_metered_exact(used=15, total=20, expires_date="24.11")
    True
    """

    safe_total = max(0, total)
    safe_used = max(0, min(used, safe_total)) if safe_total else 0
    left = max(0, safe_total - safe_used)
    pct_left = fmt_percent(safe_total - safe_used, max(1, safe_total))
    filled = _progress_blocks_used(safe_used, max(1, safe_total), 5)
    bar = progress_bar(5, filled)
    return (
        f"Подписка: {_plan_caption(safe_total)} • Осталось: {left}/{safe_total} ({pct_left})"
        f" • Действует до: {expires_date}\n{bar}"
    )


def status_line_unlim(today_used: int, cap: int | None, expires_date: str) -> str:
    """Return status line for unlimited plan.

    >>> "Безлимит" in status_line_unlim(today_used=5, cap=50, expires_date="24.11")
    True
    """

    safe_today = max(0, today_used)
    if cap and cap > 0:
        safe_cap = max(1, cap)
        pct = fmt_percent(safe_today, safe_cap)
        filled = _progress_blocks_used(safe_today, safe_cap, 5)
        bar = progress_bar(5, filled)
        return (
            "Подписка: Безлимит\n"
            f"Сегодня: {safe_today}/{safe_cap} ({pct})\n"
            f"Действует до: {expires_date}\n"
            f"{bar}"
        )
    bar = progress_bar(5, 5 if safe_today else 0)
    return (
        "Подписка: Безлимит\n"
        f"Сегодня: {safe_today}\n"
        f"Действует до: {expires_date}\n"
        f"{bar}"
    )


def unlim_cap_hit_today(max_daily: int) -> str:
    """Notice about hitting unlimited cap."""

    return f"Лимит {max_daily}/сутки достигнут. Можно снова завтра после 00:00."


def profile_overview_metered_exact(used: int, total: int, expires_date: str) -> str:
    """Return profile overview for metered plan.

    >>> "Осталось: 10/20" in profile_overview_metered_exact(used=10, total=20, expires_date="24.11")
    True
    """

    safe_total = max(0, total)
    safe_used = max(0, min(used, safe_total)) if safe_total else 0
    left = max(0, safe_total - safe_used)
    pct_left = fmt_percent(safe_total - safe_used, max(1, safe_total))
    return (
        f"Подписка: {_plan_caption(safe_total)}\n"
        f"Осталось: {left}/{safe_total} ({pct_left})\n"
        f"Действует до: {expires_date}"
    )


def profile_overview_unlim(expires_date: str) -> str:
    """Return profile overview for unlimited plan."""

    return f"Подписка: Безлимит\nДействует до: {expires_date}"


# === settings within profile ==================================================

def settings_menu(
    notif_payments: bool,
    notif_ref: bool,
    mask_history: bool,
    post_report_action: str,
) -> str:
    """Describe current settings."""

    def _on_off(value: bool) -> str:
        return "вкл" if value else "выкл"

    action_map = {
        "check": ACTION_BTN_CHECK,
        "menu": ACTION_BTN_MENU,
        ACTION_BTN_CHECK: ACTION_BTN_CHECK,
        ACTION_BTN_MENU: ACTION_BTN_MENU,
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
    """Confirm settings update."""

    return "Готово, настройки обновлены."


# === referral =================================================================

def ref_header() -> str:
    """Referral header."""

    return "Пригласить и заработать"


def ref_link_block(link: str) -> str:
    """Referral link block."""

    return f"Ваша ссылка:\n{link}\n\nСкопируйте и отправьте друзьям."


def ref_level_block(level: int, percent: int, to_next: int | None) -> str:
    """Referral level description."""

    base = f"Ваш уровень: {level} • Вознаграждение: {percent}%"
    if to_next is not None:
        base += f"\nДо следующего уровня осталось: {to_next} оплат"
    return base


def ref_earnings_block(accrued_rub: int, pending_rub: int) -> str:
    """Referral earnings block."""

    return f"Зачислено: {fmt_rub(accrued_rub)} • Ожидает: {fmt_rub(pending_rub)}"


def ref_spend_withdraw_block() -> str:
    """Referral spend/withdraw block."""

    return (
        "Куда потратить:\n"
        "— Купить 20 из баланса\n"
        "— Купить 50 из баланса\n"
        "— Купить Безлимит из баланса\n\n"
        "Вывод средств"
    )


def ref_how_it_works() -> str:
    """Explain referral mechanics."""

    steps = [
        "Делитесь вашей ссылкой.",
        "Друг оплачивает подписку.",
        "Мы начисляем % на ваш баланс.",
        "Начисления становятся доступными через 3 дня (если не было возврата).",
        "Процент растёт по мере количества оплат ваших приглашённых.",
    ]
    return "Как это работает:\n" + bullet_list(steps)


def ref_levels_table() -> str:
    """Referral levels overview."""

    levels = [
        "0–2 оплат — 10%",
        "3–9 — 20%",
        "10–24 — 30%",
        "25–49 — 40%",
        "≥50 — 50%",
    ]
    return "Уровни:\n" + bullet_list(levels)


def wallet_only_in_referral_notice() -> str:
    """Explain wallet payments scope."""

    return "Оплата из баланса доступна только в разделе «Пригласить и заработать»."


def ref_balance_only_here_notice() -> str:
    """Alias for wallet notice inside referral screens."""

    return wallet_only_in_referral_notice()


def ref_promo_short() -> str:
    """Short referral promo block."""

    return (
        "Хотите платить меньше? Пригласите друга — получите до 50% от его подписок.\n"
        "[Моя ссылка]  [Как это работает]"
    )


# === company ati ==============================================================

def company_ati_ask() -> str:
    """Ask for ATI code."""

    return (
        "Оплата прошла ✔\n\n"
        "Укажите код АТИ вашей компании (3–7 цифр).\n"
        "Это нужно один раз, чтобы ускорить поддержку."
    )


def company_ati_why() -> str:
    """Explain ATI request."""

    return (
        "Чтобы быстрее помогать вам по вопросам компании и подписки. Код АТИ видим только мы. "
        "Вы можете изменить его в настройках в любой момент."
    )


def company_ati_saved(ati: str) -> str:
    """Confirm ATI saved."""

    return f"Готово, код АТИ компании сохранён: {ati}. Изменить можно в Профиль → Настройки."


def company_ati_later() -> str:
    """Acknowledge postponing ATI."""

    return "Хорошо, напомним позже. Указать можно в Профиль → Настройки."


def company_ati_banner_not_set() -> str:
    """Banner when ATI not set."""

    return "Код АТИ компании не указан. [Указать]"


def company_ati_change_confirm(new_code: str) -> str:
    """Confirm ATI change."""

    return f"Уверены, что хотите изменить код на {new_code}?"


# === history & help ===========================================================

def hint_send_code() -> str:
    """Prompt for ATI code."""

    return "🔎 Пришлите код АТИ (3–7 цифр) — ответим сразу."


def history_empty() -> str:
    """Blank history note."""

    return "Пока нет проверок."


def history_header() -> str:
    """History heading."""

    return "История проверок"


def history_item_line(status_emoji: str, ati: str, dt: str) -> str:
    """Return a line for history list."""

    return f"{status_emoji} {ati} • {dt}"


def history_no_more() -> str:
    """Footer for history feed."""

    return "Это всё на сейчас."


def history_empty_hint() -> str:
    """History hint when list is empty."""

    return "Пока нет проверок.\nПришлите код АТИ (3–7 цифр) — проверим сразу."


def help_main() -> str:
    """Help section title."""

    return "Помощь"


def faq_text() -> str:
    """FAQ content."""

    questions = [
        "Как сделать проверку? — Пришлите код АТИ (3–7 цифр) в чат, и мы сразу дадим отчёт.",
        "Что делать, если проверок не осталось? — Выберите и оплатите план. Всё занимает минуту.",
        "Как работают бесплатные проверки? — Новым пользователям выдаётся 5 проверок на 3 дня.",
        f"Как работает безлимит? — До 50 проверок в сутки, счётчик обнуляется в 00:00 ({cfg.tz}).",
        "Как оплатить из баланса? — Это возможно только в разделе «Пригласить и заработать».",
        "Как изменить код АТИ компании? — Профиль → Настройки.",
    ]
    return "Вопросы и ответы:\n" + bullet_list(questions)


def support_pretext() -> str:
    """Support prompt."""

    return "Если остались вопросы — напишите нам."


# === reports ==================================================================

def report_a(ati: str, lin: int, exp: int, tail: str) -> str:
    """Green report text."""

    return (
        f"🟢 Код АТИ {ati} успешно прошёл проверку.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: риск не выявлен\n\n"
        f"{tail}"
    )


def report_b(ati: str, lin: int, exp: int) -> str:
    """Yellow report text with risk."""

    return (
        f"🟡 Код АТИ {ati} обнаружен в нашем реестре проверок.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: ⁉️ Повышенный риск\n\n"
        "По данным нашей аналитики, есть риски. Оценка субъективна и может быть изменена при "
        "появлении благоприятных признаков."
    )


def report_c(ati: str, lin: int, exp: int) -> str:
    """Yellow report text with scarce data."""

    return (
        f"🟡 Код АТИ {ati} проверен.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: не выявлен риск\n\n"
        "Подтверждений по реестрам мало — это не негатив, но истории нет."
    )


def report_d(ati: str, lin: int, exp: int) -> str:
    """Red report text."""

    return (
        f"🔴 Код АТИ {ati} не прошёл проверку.\n\n"
        f"📈 Индекс перевозчика: {lin}\n"
        f"📈 Индекс экспедитора: {exp}\n\n"
        "🛡 Чёрные списки: ⛔️ Критический риск\n\n"
        "По данным нашей аналитики, есть риски. Оценка субъективна и может быть изменена при "
        "появлении благоприятных признаков."
    )


def report_e(ati: str) -> str:
    """Yellow report text for unknown code."""

    return (
        f"🟡 Код АТИ {ati} не обнаружен в наших реестрах.\n\n"
        "📈 Индекс перевозчика: 0\n"
        "📈 Индекс экспедитора: 0\n\n"
        "🛡 Чёрные списки: не выявлен риск\n\n"
        "Подтверждений по реестрам не обнаружено — это не негатив, но истории нет."
    )


__all__ = [
    "progress_bar",
    "fmt_percent",
    "fmt_rub",
    "bullet_list",
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
    "invalid_input_non_digits",
    "err_need_digits_3_7",
    "too_many_requests",
    "throttle_msg",
    "nudge_enter_code",
    "plans_list",
    "paywall_no_checks",
    "payment_success",
    "payment_incomplete",
    "payment_timeout",
    "payment_failed_try_again",
    "payment_abandoned",
    "refund_processed",
    "free_pack_status",
    "free_expiring_24h",
    "free_low_left",
    "inactive_with_active_subscription",
    "winback_no_activity",
    "status_line_metered_exact",
    "status_line_unlim",
    "unlim_cap_hit_today",
    "profile_overview_metered_exact",
    "profile_overview_unlim",
    "ref_header",
    "ref_link_block",
    "ref_level_block",
    "ref_earnings_block",
    "ref_spend_withdraw_block",
    "ref_how_it_works",
    "ref_levels_table",
    "wallet_only_in_referral_notice",
    "ref_balance_only_here_notice",
    "ref_promo_short",
    "company_ati_ask",
    "company_ati_why",
    "company_ati_saved",
    "company_ati_later",
    "company_ati_banner_not_set",
    "company_ati_change_confirm",
    "hint_send_code",
    "history_empty",
    "history_header",
    "history_item_line",
    "history_no_more",
    "history_empty_hint",
    "help_main",
    "faq_text",
    "support_pretext",
    "report_a",
    "report_b",
    "report_c",
    "report_d",
    "report_e",
    "settings_menu",
    "settings_changed_ok",
]
