"""LegendMind V3 — runtime configuration loader.

Reads environment variables once at startup and exposes a typed `Config`
dataclass to the rest of the codebase. Never read os.environ elsewhere.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

_log = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent / ".env")


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _opt(name: str) -> str | None:
    val = os.environ.get(name)
    return val if val else None


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw else default


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _opt_int(name: str) -> int | None:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return None
    return int(str(raw).strip())


def _reject_localhost_db_on_railway(database_url: str) -> None:
    """Railway injecte RAILWAY_ENVIRONMENT ; une URL localhost ne fonctionne jamais depuis le cloud."""
    if not os.environ.get("RAILWAY_ENVIRONMENT"):
        return
    u = database_url.lower()
    if "localhost" in u or "127.0.0.1" in u:
        raise RuntimeError(
            "DATABASE_URL pointe vers cette machine (localhost), ce qui ne marche pas sur Railway. "
            "Ajoute le plugin PostgreSQL Railway (ou une base cloud), puis dans Variables du service "
            "remplace DATABASE_URL par la chaîne fournie par Railway (référence la variable du plugin Postgres), "
            "pas l'URL de ton Mac."
        )


def infer_database_ssl() -> bool:
    """Active TLS vers Postgres (souvent requis sur Railway / hébergeurs managés).

    Désactive avec ``DATABASE_SSL=false`` si ta base locale n'accepte pas SSL.
    """
    explicit = os.environ.get("DATABASE_SSL", "").strip().lower()
    if explicit in ("0", "false", "no", "off"):
        return False
    if explicit in ("1", "true", "yes", "on", "require"):
        return True
    return bool(os.environ.get("RAILWAY_ENVIRONMENT"))


def _webhook_listen_port() -> int:
    """Port HTTP (Stripe webhook + /health). Railway injecte ``PORT``."""
    if os.environ.get("WEBHOOK_PORT"):
        return int(os.environ["WEBHOOK_PORT"])
    if os.environ.get("PORT"):
        return int(os.environ["PORT"])
    return 8000


def _extended_trial_guild_ids() -> frozenset[int]:
    """Serveurs Discord où l'essai Premium au premier grant est prolongé.

    Liste ``EXTENDED_TRIAL_GUILD_IDS`` (IDs séparés par virgule ou espace).
    Durée : ``EXTENDED_TRIAL_DAYS`` (défaut 60 ≈ 2 mois). Hors liste :
    ``PREMIUM_TRIAL_DAYS`` (constants, ex. 7 j).
    """
    raw = os.environ.get("EXTENDED_TRIAL_GUILD_IDS", "")
    if not raw.strip():
        return frozenset()
    out: set[int] = set()
    for token in raw.replace(",", " ").split():
        t = token.strip()
        if not t:
            continue
        try:
            out.add(int(t))
        except ValueError:
            _log.warning(
                "EXTENDED_TRIAL_GUILD_IDS: jeton ignoré (non entier): %r",
                t,
            )
    return frozenset(out)


def _lifetime_entitled_discord_ids() -> frozenset[int]:
    """IDs Discord avec accès Premium permanent (sans Stripe), liste admin."""
    raw = os.environ.get("LIFETIME_ENTITLED_DISCORD_IDS", "")
    if not raw.strip():
        return frozenset()
    out: set[int] = set()
    for token in raw.replace(",", " ").split():
        t = token.strip()
        if not t:
            continue
        try:
            out.add(int(t))
        except ValueError:
            _log.warning(
                "LIFETIME_ENTITLED_DISCORD_IDS: jeton ignoré (non entier): %r",
                t,
            )
    return frozenset(out)


@dataclass(frozen=True)
class Config:
    discord_token: str
    coc_email: str
    coc_password: str
    database_url: str
    database_use_ssl: bool = False
    log_level: str = "INFO"
    poll_interval_seconds: int = 180
    poll_queue_max: int = 2000
    alert_cooldown_default_seconds: int = 3600
    extra_intents: tuple[str, ...] = field(default_factory=tuple)

    # Slash command sync strategy:
    # - "guild": sync only to connected guilds (fast, avoids "double" commands)
    # - "global": sync only globally (may take time to propagate)
    # - "both": guild first, then global (default)
    slash_sync_mode: str = "both"
    # One-shot maintenance: when True, delete all GLOBAL commands on startup
    # (useful after switching from global->guild to remove "duplicates").
    slash_purge_global: bool = False
    # One-shot maintenance: when True, delete all GUILD commands on startup
    # and re-sync from the local tree (useful when Discord shows duplicates in-guild).
    slash_purge_guild: bool = False

    # Billing (Stripe). All optional — when absent, /premium and the webhook
    # server are disabled and the bot still works as Free-only.
    stripe_api_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_price_id_monthly: str | None = None
    stripe_success_url: str | None = None
    stripe_cancel_url: str | None = None

    # HTTP webhook server (Stripe). Listens locally; expose via tunnel/proxy.
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8000

    # Tuning Legend (JSON distant, ex. mis à jour après lecture des patch notes).
    game_tuning_url: str | None = None
    game_tuning_poll_seconds: int = 86400

    # Accès Premium permanent sans abonnement (IDs Discord, séparés par virgule ou espace).
    lifetime_entitled_discord_ids: frozenset[int] = frozenset()

    # Essai prolongé sur certains serveurs (voir EXTENDED_TRIAL_GUILD_IDS).
    extended_trial_guild_ids: frozenset[int] = frozenset()
    extended_trial_days: int = 60

    # Export Excel quotidien (stats Légende par journée de reset — voir GAME_TUNING / reset UTC).
    daily_legend_export_enabled: bool = False
    daily_legend_export_minute_after_reset: int = 5
    daily_legend_export_xlsx_path: str = "data/daily_legend_stats.xlsx"
    daily_legend_export_state_path: str = "data/.daily_legend_export_last"
    daily_legend_export_discord_channel_id: int | None = None


def load_config() -> Config:
    """Load configuration from environment. Fail fast on missing secrets."""
    database_url = _required("DATABASE_URL")
    _reject_localhost_db_on_railway(database_url)
    return Config(
        discord_token=_required("DISCORD_TOKEN"),
        coc_email=_required("COC_EMAIL"),
        coc_password=_required("COC_PASSWORD"),
        database_url=database_url,
        database_use_ssl=infer_database_ssl(),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
        poll_interval_seconds=_int("POLL_INTERVAL_SECONDS", 180),
        poll_queue_max=_int("POLL_QUEUE_MAX", 2000),
        alert_cooldown_default_seconds=_int("ALERT_COOLDOWN_DEFAULT_SECONDS", 3600),
        slash_sync_mode=os.environ.get("SLASH_SYNC_MODE", "both").strip().lower(),
        slash_purge_global=_bool("SLASH_PURGE_GLOBAL", False),
        slash_purge_guild=_bool("SLASH_PURGE_GUILD", False),
        stripe_api_key=_opt("STRIPE_API_KEY"),
        stripe_webhook_secret=_opt("STRIPE_WEBHOOK_SECRET"),
        stripe_price_id_monthly=_opt("STRIPE_PRICE_ID_MONTHLY"),
        stripe_success_url=_opt("STRIPE_SUCCESS_URL"),
        stripe_cancel_url=_opt("STRIPE_CANCEL_URL"),
        webhook_host=os.environ.get("WEBHOOK_HOST", "0.0.0.0"),
        webhook_port=_webhook_listen_port(),
        game_tuning_url=_opt("GAME_TUNING_URL"),
        game_tuning_poll_seconds=_int("GAME_TUNING_POLL_SECONDS", 86400),
        lifetime_entitled_discord_ids=_lifetime_entitled_discord_ids(),
        extended_trial_guild_ids=_extended_trial_guild_ids(),
        extended_trial_days=_int("EXTENDED_TRIAL_DAYS", 60),
        daily_legend_export_enabled=_bool("DAILY_LEGEND_EXPORT_ENABLED", False),
        daily_legend_export_minute_after_reset=_int(
            "DAILY_LEGEND_EXPORT_MINUTE_AFTER_RESET",
            5,
        ),
        daily_legend_export_xlsx_path=os.environ.get(
            "DAILY_LEGEND_EXPORT_XLSX_PATH",
            "data/daily_legend_stats.xlsx",
        ),
        daily_legend_export_state_path=os.environ.get(
            "DAILY_LEGEND_EXPORT_STATE_PATH",
            "data/.daily_legend_export_last",
        ),
        daily_legend_export_discord_channel_id=_opt_int(
            "DAILY_LEGEND_EXPORT_DISCORD_CHANNEL_ID",
        ),
    )
