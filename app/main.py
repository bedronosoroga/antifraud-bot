from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional

from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramAPIError

from app.config import cfg
from app.core import db as dal
from app.core.rate_limit import RateLimitExceeded
from app.core.scheduler import create as create_scheduler

from app.domain.checks.loader import load_catalog
from app.domain.checks.service import CheckerService

from app.domain.onboarding.free import FREE, FreeService
from app.domain.subs import service as subs_service
from app.domain.quotas.service import QuotaService
from app.domain.payments.provider import init_payment_runtime

from app.bot.handlers_public import router as public_router, init_onboarding_runtime
from app.bot.handlers_numeric import (
    router as numeric_router,
    init_checks_runtime,
)
from app.bot import runtime as bot_runtime


LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_quota_service: QuotaService | None = None


@dataclass
class AppContext:
    bot: Bot
    dp: Dispatcher
    scheduler: Optional[object] = None


def setup_logging() -> None:
    level = logging.DEBUG if getattr(cfg, "debug", False) else logging.INFO
    logging.basicConfig(level=level, format=LOG_FORMAT)


async def init_database() -> None:
    await dal.init_db()
    logging.info("Database connection established")


async def init_checks() -> None:
    try:
        catalog = load_catalog(cfg.paths)
    except Exception:
        logging.exception("Failed to load Excel catalogs")
        catalog = None

    if catalog is None:
        logging.warning("Checks catalog is empty; continuing without data")
        init_checks_runtime(None, cfg.lin_ok, cfg.exp_ok)  # type: ignore[arg-type]
        return

    checker = CheckerService(catalog, lin_ok=cfg.lin_ok, exp_ok=cfg.exp_ok)
    init_checks_runtime(checker, cfg.lin_ok, cfg.exp_ok)
    logging.info("Checks runtime initialized")


async def init_free() -> None:
    try:
        free_service = FreeService(total=FREE["total"], ttl_hours=FREE["ttl_hours"])
        init_onboarding_runtime(free=free_service)
        logging.info("Free runtime initialized")
    except Exception:
        logging.exception("Failed to initialize free runtime")


def init_quota_service() -> QuotaService:
    global _quota_service
    if _quota_service is None:
        _quota_service = QuotaService(tz=cfg.tz)
        bot_runtime.set_quota_service(_quota_service)
        init_payment_runtime(quota=_quota_service)
    return _quota_service


def setup_error_handlers(dp: Dispatcher) -> None:
    @dp.errors()
    async def error_handler(event):
        exception = getattr(event, "exception", None)
        if not isinstance(exception, RateLimitExceeded):
            return False
        try:
            update = getattr(event, "update", None)
            text = (
                "Слишком много запросов. "
                f"Подождите {exception.retry_after} сек и попробуйте снова."
            )
            if update and getattr(update, "message", None):
                await update.message.answer(text)
            elif update and getattr(update, "callback_query", None):
                await update.callback_query.answer(text, show_alert=True)
        except TelegramAPIError:
            pass
        except Exception:
            logging.exception("Failed to deliver rate limit notification")
        return True


async def start_scheduler(bot: Bot) -> object:
    scheduler = create_scheduler(bot)
    scheduler.start()
    logging.info("Scheduler started")
    return scheduler


async def shutdown(ctx: AppContext) -> None:
    if ctx.scheduler is not None:
        try:
            ctx.scheduler.shutdown(wait=False)
        except Exception:
            logging.exception("Error during scheduler shutdown")
    await dal.dispose_engine()
    await ctx.bot.session.close()
    logging.info("Shutdown complete")


async def _main() -> None:
    setup_logging()
    logging.info("Starting antifraud bot")

    await init_database()
    await init_checks()
    await init_free()
    init_quota_service()

    bot = Bot(
        token=cfg.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    ctx = AppContext(bot=bot, dp=dp)
    dp["ctx"] = ctx

    dp.include_router(public_router)
    dp.include_router(numeric_router)

    setup_error_handlers(dp)

    ctx.scheduler = await start_scheduler(bot)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler(*_: object) -> None:
        logging.info("Received stop signal")
        stop_event.set()

    for sig in (signal.SIGINT, getattr(signal, "SIGTERM", signal.SIGINT)):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            signal.signal(sig, lambda *_: stop_event.set())

    polling_task = asyncio.create_task(
        dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    )
    wait_task = asyncio.create_task(stop_event.wait())

    try:
        done, pending = await asyncio.wait(
            {polling_task, wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if wait_task in done:
            dp.stop_polling()
            if not polling_task.done():
                polling_task.cancel()
        elif polling_task in done and not wait_task.done():
            stop_event.set()
    finally:
        for task in (polling_task, wait_task):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        await shutdown(ctx)


def main() -> None:
    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
