from __future__ import annotations

import logging
import asyncio
from contextlib import suppress
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
from app.domain.payments.yookassa_service import YooKassaService
from app.keyboards import kb_payment_success, kb_payment_error
from app.domain.referrals import service as referral_service
from app.keyboards import kb_payment_error

logger = logging.getLogger(__name__)
logging.getLogger("apscheduler").setLevel(logging.WARNING)

CATALOG_DEBOUNCE_SECONDS = 60
CATALOG_CHECK_INTERVAL = 60
CATALOG_HEARTBEAT_INTERVAL = 3600
_catalog_reload_lock = asyncio.Lock()
_catalog_heartbeat = {
    "runs": 0,
    "reloads": 0,
    "failures": 0,
    "last_log_ts": datetime.now(timezone.utc).timestamp(),
}
_yk_heartbeat = {"runs": 0, "updated": 0, "failures": 0, "last_log_ts": datetime.now(timezone.utc).timestamp(), "429": 0, "pending": 0}
_scheduler_bot: Bot | None = None
YK_POLL_INTERVAL = 10
STARS_EXPIRE_INTERVAL = 30


def _maybe_log_catalog_heartbeat(now_ts: float) -> None:
    if now_ts - _catalog_heartbeat["last_log_ts"] < CATALOG_HEARTBEAT_INTERVAL:
        return
    last_reload = bot_runtime.get_catalog_last_reload_mtime()
    logger.info(
        "Catalog watcher heartbeat: runs=%s, reloads=%s, failures=%s, last_reload_mtime=%s",
        _catalog_heartbeat["runs"],
        _catalog_heartbeat["reloads"],
        _catalog_heartbeat["failures"],
        last_reload,
    )
    _catalog_heartbeat["runs"] = 0
    _catalog_heartbeat["reloads"] = 0
    _catalog_heartbeat["failures"] = 0
    _catalog_heartbeat["last_log_ts"] = now_ts

def build_scheduler(bot: Bot) -> AsyncIOScheduler:
    global _scheduler_bot
    _scheduler_bot = bot
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


async def job_poll_yk_payments(bot: Bot | None = None) -> None:
    if cfg.yookassa is None:
        return
    _yk_heartbeat["runs"] += 1
    service = YooKassaService(cfg.yookassa)
    try:
        pending = await dal.yk_list_pending()
    except Exception:
        _yk_heartbeat["failures"] += 1
        logger.exception("failed to fetch pending yk payments")
        return
    if not pending:
        return
    _yk_heartbeat["pending"] = len(pending)
    quota = bot_runtime.get_quota_service()
    for payment in pending:
        # drop stale confirmation links older than 60 minutes and notify
        created_at = payment.get("created_at")
        meta = payment.get("raw_metadata") or {}
        if created_at:
            age = datetime.now(timezone.utc) - created_at
            if age.total_seconds() > 3600:
                if payment.get("confirmation_url"):
                    with suppress(Exception):
                        await dal.yk_clear_confirmation_url(payment["id"])
                if payment.get("status") not in {"succeeded", "canceled", "expired"}:
                    await dal.yk_update_status(payment["id"], status="expired")
                    if bot is not None:
                        if meta.get("chat_id") and meta.get("message_id"):
                            with suppress(Exception):
                                await bot.delete_message(meta["chat_id"], meta["message_id"])
                        with suppress(Exception):
                            await bot.send_message(
                                payment["uid"],
                                "⏳ Ссылка на оплату устарела. Начните оплату заново.",
                                reply_markup=kb_payment_error(str(payment["id"])),
                            )
                    continue
        try:
            res = await service.fetch_status(payment["yk_payment_id"])
            status = res.status
            await dal.yk_update_status(payment["id"], status=status, raw_metadata=res.metadata)
            if status == "succeeded" and payment.get("granted_requests", 0) == 0:
                await quota.add(
                    payment["uid"],
                    payment["package_qty"],
                    source="yookassa",
                    metadata={"payment_id": payment["id"], "yk_payment_id": payment.get("yk_payment_id")},
                )
                await dal.yk_mark_granted(payment["id"], payment["package_qty"])
                with suppress(Exception):
                    await referral_service.record_paid_subscription(
                        payment["uid"],
                        amount_kop=int(payment.get("package_price_rub", 0) * 100),
                        provider="yookassa",
                        payment_id=payment.get("id"),
                    )
                _yk_heartbeat["updated"] += 1
                if bot is not None and not payment.get("notified"):
                    balance = (await quota.get_state(payment["uid"])).balance
                    text = (
                        f"<b>✅ Оплата прошла</b>\n\n"
                        f"Начислено <b>+{payment['package_qty']}</b> запросов.\n"
                        f"<b>Доступно запросов</b>: {balance}"
                    )
                    meta = payment.get("raw_metadata") or {}
                    if meta.get("chat_id") and meta.get("message_id"):
                        with suppress(Exception):
                            await bot.delete_message(meta["chat_id"], meta["message_id"])
                    with suppress(Exception):
                        await bot.send_message(payment["uid"], text, reply_markup=kb_payment_success())
                    with suppress(Exception):
                        await dal.yk_update_status(payment["id"], status="succeeded", notified=True)
            elif status in {"canceled", "expired", "refunded"}:
                await dal.yk_update_status(payment["id"], status=status, raw_metadata=res.metadata)
                if status == "refunded":
                    with suppress(Exception):
                        await referral_service.handle_payment_refund("yookassa", payment["id"])
                meta = payment.get("raw_metadata") or {}
                if meta.get("chat_id") and meta.get("message_id") and bot is not None:
                    with suppress(Exception):
                        await bot.delete_message(meta["chat_id"], meta["message_id"])
        except Exception as exc:
            _yk_heartbeat["failures"] += 1
            msg = str(exc)
            if "429" in msg:
                _yk_heartbeat["429"] += 1
                logger.warning("YooKassa rate limit hit, stopping poll run early")
                break
            logger.exception("failed to poll yk payment %s", payment.get("id"))
        await asyncio.sleep(0.2)


async def job_daily_digest(bot: Bot) -> None:
    # Optional job – implement later as needed.
    return


async def job_expire_stars(bot: Bot | None = None) -> None:
    try:
        pending = await dal.yk_list_pending_by_provider("stars", statuses=["pending"])
    except Exception:
        logger.exception("failed to fetch pending stars payments")
        return
    if not pending:
        return
    now = datetime.now(timezone.utc)
    for payment in pending:
        created_at = payment.get("created_at")
        if not created_at:
            continue
        age = now - created_at
        if age.total_seconds() > 3600:
            meta = payment.get("raw_metadata") or {}
            if meta.get("chat_id") and meta.get("message_id") and bot is not None:
                with suppress(Exception):
                    await bot.delete_message(meta["chat_id"], meta["message_id"])
            with suppress(Exception):
                await dal.yk_update_status(payment["id"], status="expired")
            if bot is not None:
                with suppress(Exception):
                    await bot.send_message(
                        payment["uid"],
                        "⏳ Счёт в Stars устарел. Создайте новый, чтобы оплатить.",
                        reply_markup=kb_payment_error(str(payment["id"])),
                    )


async def job_catalog_reload_if_needed() -> None:
    now_ts = datetime.now(timezone.utc).timestamp()
    _catalog_heartbeat["runs"] += 1
    try:
        latest_mtime = _latest_excel_mtime()
        if latest_mtime is None:
            return
        bot_runtime.set_catalog_last_seen_mtime(latest_mtime)
        async with _catalog_reload_lock:
            current_reload_mtime = bot_runtime.get_catalog_last_reload_mtime()
            if current_reload_mtime is not None and latest_mtime <= current_reload_mtime:
                return
            if now_ts - latest_mtime < CATALOG_DEBOUNCE_SECONDS:
                return
            try:
                catalog = await asyncio.to_thread(load_catalog, cfg.paths)
            except Exception:
                _catalog_heartbeat["failures"] += 1
                logger.exception("Failed to reload Excel catalog; keeping existing data")
                return
            checker = CheckerService(catalog, lin_ok=cfg.lin_ok, exp_ok=cfg.exp_ok)
            cache = AtiCodeCache()
            cache.refresh_from_catalog(catalog)
            init_checks_runtime(checker, cfg.lin_ok, cfg.exp_ok)
            bot_runtime.set_ati_code_cache(cache)
            bot_runtime.set_catalog_last_seen_mtime(latest_mtime)
            bot_runtime.set_catalog_last_reload_mtime(latest_mtime)
            _catalog_heartbeat["reloads"] += 1
            logger.info("ATI catalog reloaded: %s codes (mtime=%s)", cache.size(), latest_mtime)
    finally:
        _maybe_log_catalog_heartbeat(now_ts)


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
    scheduler.add_job(
        job_poll_yk_payments,
        IntervalTrigger(seconds=YK_POLL_INTERVAL),
        args=[_scheduler_bot],
        id="yk_poll",
        replace_existing=True,
    )
    scheduler.add_job(
        job_expire_stars,
        IntervalTrigger(seconds=STARS_EXPIRE_INTERVAL),
        args=[_scheduler_bot],
        id="stars_expire",
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
    "job_poll_yk_payments",
    "job_expire_stars",
]
