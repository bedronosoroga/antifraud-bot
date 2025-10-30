from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from app.core import db as dal
from app.keyboards import plans_kb_for_provider
from app.texts import (
    SUB_EXPIRY_D3,
    SUB_EXPIRY_D1,
    SUB_EXPIRED,
    TRIAL_EXPIRY_D1,
    TRIAL_EXPIRY_3H,
)

logger = logging.getLogger(__name__)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    _register_jobs(scheduler, bot)
    return scheduler


def create(bot: Bot) -> AsyncIOScheduler:
    return build_scheduler(bot)


async def job_sub_expiry_d3(bot: Bot) -> None:
    await _notify_subscribers(
        bot,
        kind="sub:d3",
        message=SUB_EXPIRY_D3,
        day_offset=3,
    )


async def job_sub_expiry_d1(bot: Bot) -> None:
    await _notify_subscribers(
        bot,
        kind="sub:d1",
        message=SUB_EXPIRY_D1,
        day_offset=1,
    )


async def job_sub_expiry_d0(bot: Bot) -> None:
    await _notify_subscribers(
        bot,
        kind="sub:d0",
        message=SUB_EXPIRED,
        day_offset=0,
    )


async def job_trial_expiry_d1(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    start, end = _day_window(now + timedelta(days=1))
    trials = await dal.list_trials_expiring_between(start, end)
    await _notify_trials(bot, trials, "trial:d1", TRIAL_EXPIRY_D1)


async def job_trial_expiry_3h(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=3)
    end = start + timedelta(minutes=30)
    trials = await dal.list_trials_expiring_within(start, end)
    await _notify_trials(bot, trials, "trial:3h", TRIAL_EXPIRY_3H)


async def job_prune_rl() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    removed = await dal.rl_prune_before(cutoff)
    if removed:
        logger.info("rate limit prune removed %s records", removed)


async def job_daily_digest(bot: Bot) -> None:
    # Optional job – implement later as needed.
    return


async def _notify_subscribers(
    bot: Bot,
    *,
    kind: str,
    message: str,
    day_offset: int,
) -> None:
    now = datetime.now(timezone.utc)
    target_start, target_end = _day_window(now + timedelta(days=day_offset))
    subs = await dal.list_paid_subs_expiring_between(target_start, target_end)
    await _dispatch_notifications(bot, subs, kind, message)


async def _notify_trials(
    bot: Bot,
    trials: Iterable[dict],
    kind: str,
    message: str,
) -> None:
    await _dispatch_notifications(bot, trials, kind, message)


async def _dispatch_notifications(
    bot: Bot,
    records: Iterable[dict],
    kind: str,
    message: str,
) -> None:
    keyboard = plans_kb_for_provider()
    now = datetime.now(timezone.utc)
    for record in records:
        uid = record.get("uid")
        if uid is None:
            continue
        try:
            already_sent = await dal.notif_was_sent(uid, kind, now)
        except Exception:
            logger.exception("failed to check notification dedupe for %s/%s", uid, kind)
            continue
        if already_sent:
            continue
        try:
            await bot.send_message(chat_id=uid, text=message, reply_markup=keyboard)
        except TelegramAPIError as exc:
            logger.warning("failed to send notification %s for user %s: %s", kind, uid, exc)
            continue
        except Exception:
            logger.exception("unexpected error sending notification %s for user %s", kind, uid)
            continue
        try:
            await dal.mark_notif_sent(uid, kind, now)
        except Exception:
            logger.exception("failed to mark notification sent for %s/%s", uid, kind)


def _register_jobs(scheduler: AsyncIOScheduler, bot: Bot) -> None:
    scheduler.add_job(
        job_sub_expiry_d3,
        CronTrigger(hour=9, minute=0, timezone="UTC"),
        args=[bot],
        id="sub_expiry_d3",
        replace_existing=True,
    )
    scheduler.add_job(
        job_sub_expiry_d1,
        CronTrigger(hour=9, minute=5, timezone="UTC"),
        args=[bot],
        id="sub_expiry_d1",
        replace_existing=True,
    )
    scheduler.add_job(
        job_sub_expiry_d0,
        CronTrigger(hour=9, minute=10, timezone="UTC"),
        args=[bot],
        id="sub_expiry_d0",
        replace_existing=True,
    )
    scheduler.add_job(
        job_trial_expiry_d1,
        CronTrigger(hour=9, minute=20, timezone="UTC"),
        args=[bot],
        id="trial_expiry_d1",
        replace_existing=True,
    )
    scheduler.add_job(
        job_trial_expiry_3h,
        CronTrigger(minute="*/30", timezone="UTC"),
        args=[bot],
        id="trial_expiry_3h",
        replace_existing=True,
    )
    scheduler.add_job(
        job_prune_rl,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="rate_limit_prune",
        replace_existing=True,
    )
    # Optional daily digest (disabled by default)
    # scheduler.add_job(
    #     job_daily_digest,
    #     CronTrigger(hour=8, minute=30, timezone="UTC"),
    #     args=[bot],
    #     id="daily_digest",
    #     replace_existing=True,
    # )


def _day_window(moment: datetime) -> tuple[datetime, datetime]:
    utc = moment.astimezone(timezone.utc)
    start = utc.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end


__all__ = [
    "build_scheduler",
    "create",
    "job_sub_expiry_d3",
    "job_sub_expiry_d1",
    "job_sub_expiry_d0",
    "job_trial_expiry_d1",
    "job_trial_expiry_3h",
    "job_prune_rl",
    "job_daily_digest",
]
