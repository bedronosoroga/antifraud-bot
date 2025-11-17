from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from aiogram import Bot

from app.core import db as dal

logger = logging.getLogger(__name__)


def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    del bot  # legacy signature; scheduler currently does not use bot
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    _register_jobs(scheduler)
    return scheduler


def create(bot: Bot) -> AsyncIOScheduler:
    return build_scheduler(bot)


async def job_prune_rl() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    removed = await dal.rl_prune_before(cutoff)
    if removed:
        logger.info("rate limit prune removed %s records", removed)


async def job_daily_digest(bot: Bot) -> None:
    # Optional job – implement later as needed.
    return


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
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


__all__ = [
    "build_scheduler",
    "create",
    "job_prune_rl",
    "job_daily_digest",
]
