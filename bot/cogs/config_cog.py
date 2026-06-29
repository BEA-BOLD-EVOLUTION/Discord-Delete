"""Slash commands for managing per-channel aging rules."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from ..db import Database
from ..duration import DurationError, humanize_duration, parse_duration

log = logging.getLogger(__name__)

MODE_LABELS = {
    "archive_delete": "Archive then delete",
    "delete": "Delete only",
}


class ConfigCog(commands.Cog):
    """`/aging` command group for configuring channels."""

    def __init__(self, bot: commands.Bot, db: Database) -> None:
        self.bot = bot
        self.db = db

    aging = app_commands.Group(
        name="aging",
        description="Configure automatic message aging for channels.",
        default_permissions=discord.Permissions(manage_messages=True),
        guild_only=True,
    )

    @aging.command(name="set", description="Set or update a channel's aging rule.")
    @app_commands.describe(
        channel="The channel to manage.",
        max_age="How old a message must be before it ages out (e.g. 30d, 12h, 45m).",
        mode="What to do with aged messages.",
        run_every="How often cleanup runs for this channel (e.g. 1d, 3d, 12h). Default 1d.",
        skip_pinned="Skip pinned messages (default: yes).",
    )
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="Archive then delete", value="archive_delete"),
            app_commands.Choice(name="Delete only", value="delete"),
        ]
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def set_rule(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        max_age: str,
        mode: app_commands.Choice[str],
        run_every: str = "1d",
        skip_pinned: bool = True,
    ) -> None:
        try:
            seconds = parse_duration(max_age)
        except DurationError as exc:
            await interaction.response.send_message(
                f"⚠️ Invalid `max_age`: {exc}", ephemeral=True
            )
            return
        try:
            run_every_seconds = parse_duration(run_every)
        except DurationError as exc:
            await interaction.response.send_message(
                f"⚠️ Invalid `run_every`: {exc}", ephemeral=True
            )
            return

        await self.db.upsert_rule(
            guild_id=interaction.guild_id,
            channel_id=channel.id,
            max_age_seconds=seconds,
            mode=mode.value,
            skip_pinned=skip_pinned,
            run_every_seconds=run_every_seconds,
        )
        await interaction.response.send_message(
            f"✅ {channel.mention} will age out messages older than "
            f"**{humanize_duration(seconds)}** — **{MODE_LABELS[mode.value]}**, "
            f"running every **{humanize_duration(run_every_seconds)}**"
            f"{' (skipping pinned)' if skip_pinned else ''}.",
            ephemeral=True,
        )

    @aging.command(name="disable", description="Stop aging messages in a channel.")
    @app_commands.describe(channel="The channel to stop managing.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def disable_rule(
        self, interaction: discord.Interaction, channel: discord.TextChannel
    ) -> None:
        existed = await self.db.disable_rule(channel.id)
        if existed:
            msg = f"🛑 Aging disabled for {channel.mention}."
        else:
            msg = f"ℹ️ {channel.mention} had no aging rule configured."
        await interaction.response.send_message(msg, ephemeral=True)

    @aging.command(name="status", description="Show the aging rule for a channel.")
    @app_commands.describe(channel="The channel to inspect (defaults to here).")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def status(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel | None = None,
    ) -> None:
        target = channel or interaction.channel
        rule = await self.db.get_rule(target.id)
        if rule is None:
            await interaction.response.send_message(
                f"ℹ️ No aging rule configured for {target.mention}.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"Aging rule for #{getattr(target, 'name', target.id)}",
            color=discord.Color.blurple() if rule.enabled else discord.Color.greyple(),
        )
        embed.add_field(name="Max age", value=humanize_duration(rule.max_age_seconds))
        embed.add_field(name="Mode", value=MODE_LABELS.get(rule.mode, rule.mode))
        embed.add_field(
            name="Runs every", value=humanize_duration(rule.run_every_seconds)
        )
        embed.add_field(name="Skip pinned", value="Yes" if rule.skip_pinned else "No")
        embed.add_field(name="Enabled", value="Yes" if rule.enabled else "No")
        last_run = (
            discord.utils.format_dt(rule.last_run_at, style="R")
            if rule.last_run_at
            else "Never"
        )
        embed.add_field(name="Last run", value=last_run)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @aging.command(name="list", description="List all aging rules in this server.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def list_rules(self, interaction: discord.Interaction) -> None:
        rules = await self.db.list_rules(interaction.guild_id)
        if not rules:
            await interaction.response.send_message(
                "ℹ️ No aging rules configured in this server.", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="Aging rules", color=discord.Color.blurple()
        )
        for rule in rules:
            status = "✅" if rule.enabled else "⏸️"
            embed.add_field(
                name=f"{status} <#{rule.channel_id}>",
                value=(
                    f"{humanize_duration(rule.max_age_seconds)} · "
                    f"{MODE_LABELS.get(rule.mode, rule.mode)} · "
                    f"every {humanize_duration(rule.run_every_seconds)}"
                    f"{' · skip pinned' if rule.skip_pinned else ''}"
                ),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # -- lifecycle cleanup -----------------------------------------------

    @commands.Cog.listener()
    async def on_guild_remove(self, guild: discord.Guild) -> None:
        """When kicked from a guild, drop its rules but keep its archive."""
        removed = await self.db.delete_rules_for_guild(guild.id)
        log.info("Removed from guild %d; deleted %d rule(s).", guild.id, removed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(
        self, channel: discord.abc.GuildChannel
    ) -> None:
        """Clean up a rule when its channel is deleted for good."""
        if await self.db.delete_rule(channel.id):
            log.info("Channel %d deleted; removed its aging rule.", channel.id)

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
    await bot.add_cog(ConfigCog(bot, bot.db))
