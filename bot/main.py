"""Entry point: wire up intents, the DB pool, cogs, and run the bot."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from .config import Config
from .db import Database

log = logging.getLogger(__name__)

COGS = (
    "bot.cogs.config_cog",
    "bot.cogs.sweeper_cog",
)


class AgingBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        intents = discord.Intents.default()
        # Needed to read message bodies for archiving.
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.config = config
        self.sweep_interval_minutes = config.sweep_interval_minutes
        self.db: Database | None = None

    async def setup_hook(self) -> None:
        self.db = await Database.connect(self.config.database_url)

        for ext in COGS:
            await self.load_extension(ext)

        if self.config.dev_guild_id:
            guild = discord.Object(id=self.config.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to dev guild %d.", self.config.dev_guild_id)
        else:
            await self.tree.sync()
            log.info("Synced commands globally.")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s).", self.user, self.user.id)

    async def close(self) -> None:
        if self.db is not None:
            await self.db.close()
        await super().close()


async def _amain() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    config = Config.from_env()
    bot = AgingBot(config)
    async with bot:
        await bot.start(config.discord_token)


def main() -> None:
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        log.info("Shutting down.")


if __name__ == "__main__":
    main()
