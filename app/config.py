from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

__all__ = [
    "AppPaths",
    "SubscriptionPlan",
    "Cfg",
    "PostgresCfg",
    "PG",
    "RUN_MIGRATIONS",
    "DEV_CREATE_ALL",
    "PLANS",
    "FREE",
    "REF_TIERS",
    "REF_WITHDRAW_MIN_KOP",
    "PAYMENTS_ACTIVE_PROVIDER",
    "PAYMENTS_SANDBOX_NOTE",
    "load_config",
    "cfg",
]

_DEFAULT_BASE_DIR = Path(__file__).resolve().parents[1]
_TRUTHY_BOOL_VALUES = {"1", "true", "yes", "on"}
_FALSY_BOOL_VALUES = {"0", "false", "no", "off"}


load_dotenv()


def env_str(name: str, default: str | None = None) -> str | None:
    """Return the value of an environment variable as a string."""

    value = os.getenv(name)
    if value is None:
        return default

    stripped = value.strip()
    if stripped == "" and default is not None:
        return default
    return stripped if stripped else value


def env_int(name: str, default: int | None = None) -> int | None:
    """Return the value of an environment variable parsed as an integer."""
    value = env_str(name)
    if value is None or value.strip() == "":
        return default
    try:
        return int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be an integer") from exc


def env_bool(name: str, default: bool = False) -> bool:
    """Return the value of an environment variable parsed as a boolean."""

    value = env_str(name)
    if value is None:
        return default

    lowered = value.strip().lower()
    if lowered == "":
        return default
    if lowered in _TRUTHY_BOOL_VALUES:
        return True
    if lowered in _FALSY_BOOL_VALUES:
        return False
    allowed = sorted(_TRUTHY_BOOL_VALUES | _FALSY_BOOL_VALUES)
    raise ValueError(f"Environment variable {name} must be a boolean ({', '.join(allowed)})")


def env_set_int(name: str) -> set[int]:
    """Return the comma-separated integers from an environment variable as a set."""
    value = env_str(name, "") or ""
    items = [part.strip() for part in value.split(",") if part.strip()]
    result: set[int] = set()
    for item in items:
        try:
            result.add(int(item))
        except ValueError as exc:
            raise ValueError(
                f"Environment variable {name} must contain integers separated by commas"
            ) from exc
    return result


def env_path(name: str, default: str) -> Path:
    """Return a path from an environment variable resolved relative to the project base dir."""
    raw_value = os.getenv(name)
    selected = default if raw_value is None or raw_value.strip() == "" else raw_value
    path = Path(selected).expanduser()
    if not path.is_absolute():
        path = _DEFAULT_BASE_DIR / path
    return path


@dataclass(frozen=True)
class AppPaths:
    """Collection of filesystem paths used by the application."""

    base_dir: Path
    excel_carriers_dir: Path
    excel_forwarders_dir: Path
    excel_blacklist_dir: Path
    excel_cache_dir: Path

    def ensure(self) -> None:
        """Ensure that required directories exist."""
        self.excel_cache_dir.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class SubscriptionPlan:
    """Represents a subscription plan available to users."""

    code: str
    title: str
    price_rub: int
    checks_in_pack: int | None
    is_unlimited: bool
    daily_cap: int | None


@dataclass(frozen=True)
class Cfg:
    """Application configuration container."""

    bot_token: str
    admin_ids: set[int]
    tz: str
    paths: AppPaths
    plans: dict[str, SubscriptionPlan]
    lin_ok: int
    exp_ok: int
    free_count: int
    free_ttl_hours: int
    ref_hold_days: int
    allow_wallet_purchases_only_in_referrals: bool


@dataclass(frozen=True)
class PostgresCfg:
    """PostgreSQL connection configuration."""

    url: str


PG = PostgresCfg(
    url=os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://antifraud:ANTIFRAUD_PASSWORD@127.0.0.1:5433/antifraud",
    )
)

RUN_MIGRATIONS = os.getenv("RUN_MIGRATIONS", "1") == "1"
DEV_CREATE_ALL = os.getenv("DEV_CREATE_ALL", "0") == "1"


def load_config() -> Cfg:
    """Load configuration from environment variables and defaults."""
    load_dotenv()

    base_dir = _DEFAULT_BASE_DIR
    paths = AppPaths(
        base_dir=base_dir,
        excel_carriers_dir=env_path("EXCEL_DIR_CARRIERS", "./data/excel/carriers/data"),
        excel_forwarders_dir=env_path("EXCEL_DIR_FORWARDERS", "./data/excel/forwarders/data"),
        excel_blacklist_dir=env_path("EXCEL_DIR_BLACKLIST", "./data/excel/blacklist/data"),
        excel_cache_dir=env_path("EXCEL_CACHE_DIR", "./data/_cache"),
    )
    paths.ensure()

    bot_token = env_str("BOT_TOKEN")
    if not bot_token:
        raise RuntimeError("Environment variable BOT_TOKEN is required and must be non-empty")

    plan_p20_price = env_int("PLAN_P20_PRICE", 299)
    plan_p50_price = env_int("PLAN_P50_PRICE", 469)
    unlim_price = env_int("PLAN_UNLIM_PRICE", 799)
    unlim_daily_cap = env_int("UNLIM_DAILY_CAP", 50)

    if plan_p20_price is None:
        raise RuntimeError("PLAN_P20_PRICE must be an integer")
    if plan_p50_price is None:
        raise RuntimeError("PLAN_P50_PRICE must be an integer")
    if unlim_price is None:
        raise RuntimeError("PLAN_UNLIM_PRICE must be an integer")
    if unlim_daily_cap is None:
        raise RuntimeError("UNLIM_DAILY_CAP must be an integer")

    plans: dict[str, SubscriptionPlan] = {
        "p20": SubscriptionPlan(
            code="p20",
            title="20 проверок",
            price_rub=plan_p20_price,
            checks_in_pack=20,
            is_unlimited=False,
            daily_cap=None,
        ),
        "p50": SubscriptionPlan(
            code="p50",
            title="50 проверок",
            price_rub=plan_p50_price,
            checks_in_pack=50,
            is_unlimited=False,
            daily_cap=None,
        ),
    }

    plans["unlim"] = SubscriptionPlan(
        code="unlim",
        title="Безлимит",
        price_rub=unlim_price,
        checks_in_pack=None,
        is_unlimited=True,
        daily_cap=unlim_daily_cap,
    )

    lin_ok = env_int("LIN_OK", 2)
    exp_ok = env_int("EXP_OK", 5)
    free_count = env_int("FREE_COUNT", 5)
    free_ttl_hours = env_int("FREE_TTL_HOURS", 72)
    ref_hold_days = env_int("REF_HOLD_DAYS", 3)

    if lin_ok is None:
        raise RuntimeError("LIN_OK must be an integer")
    if exp_ok is None:
        raise RuntimeError("EXP_OK must be an integer")
    if free_count is None:
        raise RuntimeError("FREE_COUNT must be an integer")
    if free_ttl_hours is None:
        raise RuntimeError("FREE_TTL_HOURS must be an integer")
    if ref_hold_days is None:
        raise RuntimeError("REF_HOLD_DAYS must be an integer")

    tz = env_str("TZ", "Europe/Moscow") or "Europe/Moscow"
    config = Cfg(
        bot_token=bot_token,
        admin_ids=env_set_int("ADMIN_IDS"),
        tz=tz,
        paths=paths,
        plans=plans,
        lin_ok=lin_ok,
        exp_ok=exp_ok,
        free_count=free_count,
        free_ttl_hours=free_ttl_hours,
        ref_hold_days=ref_hold_days,
        allow_wallet_purchases_only_in_referrals=True,
    )
    return config


cfg = load_config()

PLANS: dict[str, dict[str, int]] = {
    "p20": {
        "checks_total": cfg.plans["p20"].checks_in_pack or 0,
        "price_kop": cfg.plans["p20"].price_rub * 100,
    },
    "p50": {
        "checks_total": cfg.plans["p50"].checks_in_pack or 0,
        "price_kop": cfg.plans["p50"].price_rub * 100,
    },
    "unlim": {
        "day_cap": cfg.plans["unlim"].daily_cap or 0,
        "price_kop": cfg.plans["unlim"].price_rub * 100,
    },
}

FREE: dict[str, int] = {
    "total": cfg.free_count,
    "ttl_hours": cfg.free_ttl_hours,
}

REF_TIERS: list[dict[str, int]] = [
    {"min_paid": 0, "percent": 10},
    {"min_paid": 3, "percent": 20},
    {"min_paid": 10, "percent": 30},
    {"min_paid": 25, "percent": 40},
    {"min_paid": 50, "percent": 50},
]

REF_WITHDRAW_MIN_KOP: int = 500_00

PAYMENTS_ACTIVE_PROVIDER: str = env_str("PAYMENTS_ACTIVE_PROVIDER", "sandbox") or "sandbox"
PAYMENTS_SANDBOX_NOTE: str = (
    env_str(
        "PAYMENTS_SANDBOX_NOTE",
        (
            "Демонстрационный режим оплаты: списаний не будет. "
            "Для завершения теста выберите «Оплата прошла (демо)» или «Оплата не прошла (демо)»."
        ),
    )
    or ""
)

# Example usage:
# from app.config import cfg
# cfg.bot_token, cfg.paths.excel_carriers_dir, cfg.plans["unlim"].daily_cap, ...
