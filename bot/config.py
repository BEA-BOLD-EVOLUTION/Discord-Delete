"""Environment-backed configuration for the bot."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    discord_token: str
    database_url: str
    sweep_interval_minutes: int
    archive_retention_days: int
    enable_message_content: bool
    dev_guild_id: int | None

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError("DISCORD_TOKEN is required (set it in your .env).")

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigError("DATABASE_URL is required (set it in your .env).")
        # A DATABASE_URL with no host means asyncpg silently falls back to
        # localhost:5432. On Railway this is the signature of a broken
        # `${{Postgres.DATABASE_URL}}` reference (the Postgres service isn't
        # linked), so fail fast with an actionable message instead.
        if urlparse(database_url).hostname is None:
            raise ConfigError(
                "DATABASE_URL has no host. On Railway, add a PostgreSQL service "
                "and set DATABASE_URL to reference it, e.g. "
                "DATABASE_URL=${{Postgres.DATABASE_URL}}."
            )

        interval_raw = os.getenv("SWEEP_INTERVAL_MINUTES", "60").strip() or "60"
        try:
            interval = int(interval_raw)
        except ValueError as exc:
            raise ConfigError(
                f"SWEEP_INTERVAL_MINUTES must be an integer, got {interval_raw!r}."
            ) from exc
        if interval < 1:
            raise ConfigError("SWEEP_INTERVAL_MINUTES must be at least 1.")

        retention_raw = os.getenv("ARCHIVE_RETENTION_DAYS", "90").strip() or "90"
        try:
            retention = int(retention_raw)
        except ValueError as exc:
            raise ConfigError(
                f"ARCHIVE_RETENTION_DAYS must be an integer, got {retention_raw!r}."
            ) from exc
        if retention < 1:
            raise ConfigError("ARCHIVE_RETENTION_DAYS must be at least 1.")

        content_raw = os.getenv("ENABLE_MESSAGE_CONTENT", "true").strip().lower()
        enable_message_content = content_raw not in ("false", "0", "no", "off")

        dev_guild_raw = os.getenv("DEV_GUILD_ID", "").strip()
        dev_guild_id: int | None
        if dev_guild_raw:
            try:
                dev_guild_id = int(dev_guild_raw)
            except ValueError as exc:
                raise ConfigError(
                    f"DEV_GUILD_ID must be an integer, got {dev_guild_raw!r}."
                ) from exc
        else:
            dev_guild_id = None

        return cls(
            discord_token=token,
            database_url=database_url,
            sweep_interval_minutes=interval,
            archive_retention_days=retention,
            enable_message_content=enable_message_content,
            dev_guild_id=dev_guild_id,
        )
