"""Slash command for reviewing the deletion audit log."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..db import Database

log = logging.getLogger(__name__)

# Maximum rows the user can request in one call.
_MAX_LIMIT = 50
_DEFAULT_LIMIT = 10


class LogsCog(commands.Cog):
    """`/logs` command for browsing deletion history."""

    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    @app_commands.command(
        name="logs",
        description="Show recent message-deletion history for this server.",
    )
    @app_commands.describe(
        limit=f"Number of entries to show (1–{_MAX_LIMIT}, default {_DEFAULT_LIMIT}).",
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def deletion_logs(
        self,
        interaction: discord.Interaction,
        limit: app_commands.Range[int, 1, _MAX_LIMIT] = _DEFAULT_LIMIT,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            rows = await self.db.list_deletion_logs(interaction.guild_id, limit=limit)
        except Exception:  # noqa: BLE001
            log.exception("Failed to fetch deletion logs for guild %d.", interaction.guild_id)
            await interaction.followup.send(
                "⚠️ Could not retrieve deletion logs. Please try again later.",
                ephemeral=True,
            )
            return

        if not rows:
            await interaction.followup.send(
                "ℹ️ No deletion history found for this server.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Deletion log — last {len(rows)} entr{'y' if len(rows) == 1 else 'ies'}",
            color=discord.Color.orange(),
        )

        for row in rows:
            # Format the timestamp as a Discord relative timestamp.
            ts = discord.utils.format_dt(row["deleted_at"], style="R")
            channel_mention = f"<#{row['channel_id']}>"

            # Build a compact value string.
            parts = [
                f"**Channel:** {channel_mention}",
                f"**By:** <@{row['user_id']}> ({row['user_name']})",
                f"**Messages deleted:** {row['message_count']}",
                f"**Type:** {row['deletion_type']}",
            ]
            if row["criteria"]:
                parts.append(f"**Criteria:** {row['criteria']}")
            if row["reason"]:
                parts.append(f"**Reason:** {row['reason']}")
            parts.append(f"**When:** {ts}")

            embed.add_field(
                name=f"#{row['id']}",
                value="\n".join(parts),
                inline=False,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "🚫 You need the **Manage Messages** permission to do that."
        else:
            log.exception("Unhandled app command error", exc_info=error)
            message = "⚠️ Something went wrong handling that command."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:  # pragma: no cover - wired in main
    await bot.add_cog(LogsCog(bot, bot.db))
