from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

__all__ = [
    "AppPaths",
    "SubscriptionPlan",
    "RequestPackage",
    "Cfg",
    "AtiConfig",
    "PostgresCfg",
    "PG",
    "RUN_MIGRATIONS",
    "DEV_CREATE_ALL",
    "PLANS",
    "FREE",
    "REF_TIERS",
    "REF_WITHDRAW_MIN_KOP",
    "REF_WITHDRAW_MIN_USD",
    "REF_WITHDRAW_FEE_PERCENT",
    "REF_SECOND_LINE_PERCENT",
    "COINMARKETCAP_API_KEY",
    "REQUEST_PACKAGES",
    "PAYMENTS_ACTIVE_PROVIDER",
    "PAYMENTS_SANDBOX_NOTE",
    "ADMINS",
    "YooKassaConfig",
    "RUB_STARS_RATE",
    "B2B_ATI_LEADS_CHAT_ID",
    "PAYMENT_EMAIL_ENABLED",
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


def env_float(name: str, default: float | None = None) -> float | None:
    """Return the value of an environment variable parsed as float."""

    value = env_str(name)
    if value is None or value.strip() == "":
        return default
    try:
        return float(value.strip())
    except ValueError as exc:
        raise ValueError(f"Environment variable {name} must be a float") from exc


def env_list(name: str, *, separators: str = ",;") -> list[str]:
    """Return list from env variable split by separators."""

    raw = env_str(name, "") or ""
    tokens: list[str] = []
    current = []
    seps = set(separators)
    for ch in raw:
        if ch in seps:
            token = "".join(current).strip()
            if token:
                tokens.append(token)
            current = []
        else:
            current.append(ch)
    token = "".join(current).strip()
    if token:
        tokens.append(token)
    return tokens


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
class RequestPackage:
    """Per-request package offered for purchase."""

    qty: int
    price_rub: int
    unit_price_rub: float
    discount_hint: str

    @property
    def price_kop(self) -> int:
        return self.price_rub * 100


@dataclass(frozen=True)
class AtiConfig:
    base_url: str = "https://api.ati.su"
    tokens: list[str] = field(default_factory=list)
    request_timeout_sec: float = 3.0
    cache_ttl_hours: int = 24


@dataclass(frozen=True)
class YooKassaConfig:
    shop_id: str
    secret_key: str
    return_url: str
    api_base_url: str = "https://api.yookassa.ru/v3"
    is_sandbox: bool = False


@dataclass(frozen=True)
class Cfg:
    """Application configuration container."""

    bot_token: str
    admin_ids: set[int]
    b2b_leads_chat_id: int | None
    tz: str
    paths: AppPaths
    plans: dict[str, SubscriptionPlan]
    lin_ok: int
    exp_ok: int
    free_count: int
    free_ttl_hours: int
    ref_hold_days: int
    allow_wallet_purchases_only_in_referrals: bool
    payment_email_enabled: bool
    ati: AtiConfig
    yookassa: YooKassaConfig | None


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

    b2b_leads_chat_id = env_int("B2B_ATI_LEADS_CHAT_ID", None)

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
    payment_email_enabled = env_bool("PAYMENT_EMAIL_ENABLED", False)

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
    ati_cfg = AtiConfig(
        base_url=env_str("ATI_API_BASE_URL", "https://api.ati.su") or "https://api.ati.su",
        tokens=env_list("ATI_API_TOKENS"),
        request_timeout_sec=env_float("ATI_API_TIMEOUT_SEC", 3.0) or 3.0,
        cache_ttl_hours=env_int("ATI_CACHE_TTL_HOURS", 24) or 24,
    )

    yks_shop_id = env_str("YKS_SHOP_ID")
    yks_secret = env_str("YKS_SECRET_KEY")
    yookassa_cfg: YooKassaConfig | None = None
    if yks_shop_id and yks_secret:
        yookassa_cfg = YooKassaConfig(
            shop_id=yks_shop_id,
            secret_key=yks_secret,
            return_url=env_str("YKS_RETURN_URL", "https://t.me/giftixxbot") or "https://t.me/giftixxbot",
            api_base_url=env_str("YKS_API_BASE_URL", "https://api.yookassa.ru/v3") or "https://api.yookassa.ru/v3",
            is_sandbox=env_bool("YKS_IS_SANDBOX", False),
        )

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
        payment_email_enabled=payment_email_enabled,
        ati=ati_cfg,
        b2b_leads_chat_id=b2b_leads_chat_id,
        yookassa=yookassa_cfg,
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
    {"min_paid": 0, "percent": 15},   # 0-4 paying referrals
    {"min_paid": 5, "percent": 25},   # 5-14
    {"min_paid": 15, "percent": 35},  # 15-49
    {"min_paid": 50, "percent": 45},  # 50+
]

REF_SECOND_LINE_PERCENT: int = 5
REF_WITHDRAW_MIN_KOP: int = 1_000_00
REF_WITHDRAW_MIN_USD: int = 10
REF_WITHDRAW_FEE_PERCENT: int = 8
COINMARKETCAP_API_KEY: str | None = env_str("COINMARKETCAP_API_KEY")
B2B_ATI_LEADS_CHAT_ID: int | None = cfg.b2b_leads_chat_id
RUB_STARS_RATE: float = float(env_str("RUB_STARS_RATE", "1.6") or 1.6)
PAYMENT_EMAIL_ENABLED: bool = cfg.payment_email_enabled

REQUEST_PACKAGES: list[RequestPackage] = [
    RequestPackage(qty=5, price_rub=99, unit_price_rub=19.8, discount_hint="~20 ₽/шт"),
    RequestPackage(qty=15, price_rub=239, unit_price_rub=15.93, discount_hint="~16 ₽/шт, −20%"),
    RequestPackage(qty=35, price_rub=489, unit_price_rub=13.97, discount_hint="~14 ₽/шт, −30%"),
    RequestPackage(qty=75, price_rub=899, unit_price_rub=11.99, discount_hint="~12 ₽/шт, −40%"),
    RequestPackage(qty=150, price_rub=1490, unit_price_rub=9.93, discount_hint="~10 ₽/шт, −50%"),
    RequestPackage(qty=500, price_rub=2990, unit_price_rub=5.98, discount_hint="~6 ₽/шт, −70%"),
]

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

ADMINS: set[int] = set(cfg.admin_ids)

# Example usage:
# from app.config import cfg
# cfg.bot_token, cfg.paths.excel_carriers_dir, cfg.plans["unlim"].daily_cap, ...
