"""Environment-backed configuration for the bot."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    discord_token: str
    database_url: str
    sweep_interval_minutes: int
    dev_guild_id: int | None

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise ConfigError("DISCORD_TOKEN is required (set it in your .env).")

        database_url = os.getenv("DATABASE_URL", "").strip()
        if not database_url:
            raise ConfigError("DATABASE_URL is required (set it in your .env).")

        interval_raw = os.getenv("SWEEP_INTERVAL_MINUTES", "60").strip() or "60"
        try:
            interval = int(interval_raw)
        except ValueError as exc:
            raise ConfigError(
                f"SWEEP_INTERVAL_MINUTES must be an integer, got {interval_raw!r}."
            ) from exc
        if interval < 1:
            raise ConfigError("SWEEP_INTERVAL_MINUTES must be at least 1.")

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
            dev_guild_id=dev_guild_id,
        )
