"""Background sweep loop plus the manual ``/sweep`` command."""

from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import archive
from ..db import ChannelRule, Database

log = logging.getLogger(__name__)

# Discord only allows bulk deletion of messages younger than 14 days.
BULK_DELETE_MAX_AGE = dt.timedelta(days=14)
BULK_DELETE_BATCH = 100


@dataclass
class SweepResult:
    archived: int = 0
    deleted: int = 0
    errors: int = 0

    def add(self, other: "SweepResult") -> None:
        self.archived += other.archived
        self.deleted += other.deleted
        self.errors += other.errors


class SweeperCog(commands.Cog):
    def __init__(
        self,
        bot: commands.Bot,
        db: Database,
        interval_minutes: int,
        retention_days: int,
    ) -> None:
        self.bot = bot
        self.db = db
        self.retention_days = retention_days
        self.sweep_loop.change_interval(minutes=interval_minutes)

    async def cog_load(self) -> None:
        self.sweep_loop.start()
        self.purge_loop.start()

    async def cog_unload(self) -> None:
        self.sweep_loop.cancel()
        self.purge_loop.cancel()

    # -- scheduled loops --------------------------------------------------

    @tasks.loop(minutes=60)
    async def sweep_loop(self) -> None:
        rules = await self.db.list_all_enabled_rules()
        # Only sweep channels whose per-channel cadence (run_every) is due.
        now = dt.datetime.now(dt.timezone.utc)
        due = [rule for rule in rules if rule.is_due(now)]
        if not due:
            return

        # Group by guild so one guild's failure is isolated from the others.
        by_guild: dict[int, list[ChannelRule]] = defaultdict(list)
        for rule in due:
            by_guild[rule.guild_id].append(rule)

        log.info(
            "Scheduled sweep starting: %d due channel(s) across %d guild(s).",
            len(due),
            len(by_guild),
        )
        grand_total = SweepResult()
        for guild_id, guild_rules in by_guild.items():
            guild_total = SweepResult()
            try:
                for rule in guild_rules:
                    guild_total.add(await self._run_sweep(rule))
                    # Record the run so the cadence clock resets for this channel.
                    await self.db.mark_rule_ran(rule.channel_id)
            except Exception:  # noqa: BLE001 - never let one guild break the loop
                log.exception("Unexpected error sweeping guild %d.", guild_id)
                guild_total.errors += 1
            log.info(
                "Guild %d sweep: archived=%d deleted=%d errors=%d",
                guild_id,
                guild_total.archived,
                guild_total.deleted,
                guild_total.errors,
            )
            grand_total.add(guild_total)

        log.info(
            "Scheduled sweep done: archived=%d deleted=%d errors=%d",
            grand_total.archived,
            grand_total.deleted,
            grand_total.errors,
        )

    @sweep_loop.before_loop
    async def _before_sweep(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(hours=24)
    async def purge_loop(self) -> None:
        """Daily purge of archived messages past the retention window."""
        purged = await self.db.purge_old_archives(self.retention_days)
        if purged:
            log.info(
                "Retention purge: removed %d archived message(s) older than %d days.",
                purged,
                self.retention_days,
            )

    @purge_loop.before_loop
    async def _before_purge(self) -> None:
        await self.bot.wait_until_ready()

    # -- core sweep -------------------------------------------------------

    async def _run_sweep(self, rule: ChannelRule) -> SweepResult:
        """Age out messages for a single channel rule. Never raises."""
        result = SweepResult()
        channel = self.bot.get_channel(rule.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(rule.channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                log.warning("Cannot access channel %d: %s", rule.channel_id, exc)
                result.errors += 1
                return result

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return result

        now = dt.datetime.now(dt.timezone.utc)
        cutoff = now - dt.timedelta(seconds=rule.max_age_seconds)
        recent_batch: list[discord.Message] = []

        try:
            async for message in channel.history(
                before=cutoff, limit=None, oldest_first=True
            ):
                if rule.skip_pinned and message.pinned:
                    continue

                if rule.mode == "archive_delete":
                    try:
                        await self.db.archive_message(archive.serialize(message))
                        result.archived += 1
                    except Exception:  # noqa: BLE001 - don't delete if archive failed
                        log.exception(
                            "Failed to archive message %d; skipping delete.",
                            message.id,
                        )
                        result.errors += 1
                        continue

                age = now - message.created_at
                if age < BULK_DELETE_MAX_AGE:
                    recent_batch.append(message)
                    if len(recent_batch) >= BULK_DELETE_BATCH:
                        result.deleted += await self._bulk_delete(channel, recent_batch)
                        recent_batch = []
                else:
                    if await self._delete_one(message):
                        result.deleted += 1
                    else:
                        result.errors += 1

            if recent_batch:
                result.deleted += await self._bulk_delete(channel, recent_batch)
        except discord.Forbidden:
            log.warning("Missing permissions to read history in %d.", rule.channel_id)
            result.errors += 1
        except discord.HTTPException as exc:
            log.warning("HTTP error sweeping channel %d: %s", rule.channel_id, exc)
            result.errors += 1

        return result

    async def _bulk_delete(
        self, channel: discord.abc.Messageable, messages: list[discord.Message]
    ) -> int:
        try:
            await channel.delete_messages(messages)
            return len(messages)
        except discord.HTTPException as exc:
            log.warning("Bulk delete failed (%s); falling back to per-message.", exc)
            deleted = 0
            for message in messages:
                if await self._delete_one(message):
                    deleted += 1
            return deleted

    async def _delete_one(self, message: discord.Message) -> bool:
        try:
            await message.delete()
            return True
        except discord.HTTPException as exc:
            log.warning("Failed to delete message %d: %s", message.id, exc)
            return False

    # -- manual command ---------------------------------------------------

    @app_commands.command(
        name="sweep",
        description="Run the aging sweep now for one channel or the whole server.",
    )
    @app_commands.describe(
        channel="Sweep just this channel (defaults to all configured channels)."
    )
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def sweep_now(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        if channel is not None:
            rule = await self.db.get_rule(channel.id)
            if rule is None or not rule.enabled:
                await interaction.followup.send(
                    f"ℹ️ {channel.mention} has no active aging rule.", ephemeral=True
                )
                return
            rules = [rule]
        else:
            rules = await self.db.list_rules(
                interaction.guild_id, enabled_only=True
            )
            if not rules:
                await interaction.followup.send(
                    "ℹ️ No active aging rules in this server.", ephemeral=True
                )
                return

        total = SweepResult()
        for rule in rules:
            total.add(await self._run_sweep(rule))
            # A manual run also resets the channel's cadence clock.
            await self.db.mark_rule_ran(rule.channel_id)

        summary = (
            f"🧹 Sweep complete across **{len(rules)}** channel(s):\n"
            f"• Archived: **{total.archived}**\n"
            f"• Deleted: **{total.deleted}**"
        )
        if total.errors:
            summary += f"\n• Errors: **{total.errors}** (see logs)"
        await interaction.followup.send(summary, ephemeral=True)

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
    await bot.add_cog(
        SweeperCog(
            bot,
            bot.db,
            bot.sweep_interval_minutes,
            bot.archive_retention_days,
        )
    )
