from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from aiogram import Bot

from app.core import db as dal
from app.config import cfg
from app.domain.checks.loader import load_catalog
from app.domain.checks.service import CheckerService
from app.domain.catalog_cache.service import AtiCodeCache
from app.bot.handlers_numeric import init_checks_runtime
from app.bot import runtime as bot_runtime

logger = logging.getLogger(__name__)

CATALOG_DEBOUNCE_SECONDS = 60
CATALOG_CHECK_INTERVAL = 60
_catalog_reload_lock = asyncio.Lock()

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


async def job_catalog_reload_if_needed() -> None:
    latest_mtime = _latest_excel_mtime()
    if latest_mtime is None:
        return
    bot_runtime.set_catalog_last_seen_mtime(latest_mtime)
    async with _catalog_reload_lock:
        current_reload_mtime = bot_runtime.get_catalog_last_reload_mtime()
        if current_reload_mtime is not None and latest_mtime <= current_reload_mtime:
            return
        now_ts = datetime.now(timezone.utc).timestamp()
        if now_ts - latest_mtime < CATALOG_DEBOUNCE_SECONDS:
            return
        try:
            catalog = await asyncio.to_thread(load_catalog, cfg.paths)
        except Exception:
            logger.exception("Failed to reload Excel catalog; keeping existing data")
            return
        checker = CheckerService(catalog, lin_ok=cfg.lin_ok, exp_ok=cfg.exp_ok)
        cache = AtiCodeCache()
        cache.refresh_from_catalog(catalog)
        init_checks_runtime(checker, cfg.lin_ok, cfg.exp_ok)
        bot_runtime.set_ati_code_cache(cache)
        bot_runtime.set_catalog_last_seen_mtime(latest_mtime)
        bot_runtime.set_catalog_last_reload_mtime(latest_mtime)
        logger.info("ATI catalog reloaded: %s codes (mtime=%s)", cache.size(), latest_mtime)


def _latest_excel_mtime() -> float | None:
    mtimes: list[float] = []
    for directory in (
        cfg.paths.excel_carriers_dir,
        cfg.paths.excel_forwarders_dir,
        cfg.paths.excel_blacklist_dir,
    ):
        mtimes.extend(_dir_excel_mtimes(directory))
    return max(mtimes) if mtimes else None


def _dir_excel_mtimes(directory: Path) -> list[float]:
    values: list[float] = []
    if not directory.exists() or not directory.is_dir():
        return values
    for path in directory.iterdir():
        if not path.is_file() or path.suffix.lower() != ".xlsx":
            continue
        try:
            values.append(path.stat().st_mtime)
        except OSError:
            continue
    return values


def _register_jobs(scheduler: AsyncIOScheduler) -> None:
    scheduler.add_job(
        job_prune_rl,
        CronTrigger(hour=3, minute=0, timezone="UTC"),
        id="rate_limit_prune",
        replace_existing=True,
    )
    scheduler.add_job(
        job_catalog_reload_if_needed,
        IntervalTrigger(seconds=CATALOG_CHECK_INTERVAL),
        id="catalog_reload",
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
    "job_catalog_reload_if_needed",
    "job_daily_digest",
]
