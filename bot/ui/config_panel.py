"""The interactive ``/setup`` configuration panel.

The Discord-agnostic pieces (``PanelState``, ``build_panel_embed``,
``persist_state``, and the preset tables) are kept free of any live Discord
objects so they can be unit-tested without a gateway connection. The
``discord.ui`` components below wire those pieces to buttons and menus.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import discord

from ..duration import DurationError, humanize_duration, parse_duration

log = logging.getLogger(__name__)

MODE_LABELS = {
    "archive_delete": "Archive then delete",
    "delete": "Delete only",
}

# (label, seconds) presets offered in the dropdowns. "Custom…" is handled
# separately via a modal.
AGE_PRESETS: list[tuple[str, int]] = [
    ("1 hour", 3600),
    ("6 hours", 6 * 3600),
    ("12 hours", 12 * 3600),
    ("1 day", 86_400),
    ("3 days", 3 * 86_400),
    ("7 days", 7 * 86_400),
    ("14 days", 14 * 86_400),
    ("30 days", 30 * 86_400),
    ("90 days", 90 * 86_400),
]

FREQ_PRESETS: list[tuple[str, int]] = [
    ("Hourly", 3600),
    ("Every 6 hours", 6 * 3600),
    ("Every 12 hours", 12 * 3600),
    ("Daily", 86_400),
    ("Every 3 days", 3 * 86_400),
    ("Weekly", 7 * 86_400),
]

DEFAULT_MAX_AGE = 30 * 86_400
DEFAULT_RUN_EVERY = 86_400
DEFAULT_MODE = "delete"
CUSTOM_VALUE = "custom"
PANEL_TIMEOUT = 180

# Step-by-step instructions shown inside the panel so it explains itself.
HOW_TO = (
    "**How to use**\n"
    "1️⃣ **Pick a channel** in the top menu.\n"
    "2️⃣ Choose an **action** — delete, or archive then delete.\n"
    "3️⃣ Set **how old** a message must be before it's removed.\n"
    "4️⃣ Set **how often** the cleanup runs.\n"
    "5️⃣ Optionally toggle **Skip pinned**.\n"
    "6️⃣ Press **Save** ✅   ·   **Disable rule** 🛑 turns a channel off.\n"
    "\n_Tip: pick **Custom…** in any menu to type an exact time like `36h` or "
    "`1w3d`. Only you can use this panel, and it closes after a few minutes._"
)


@dataclass
class PanelState:
    """Mutable selections backing a single ``/setup`` panel."""

    channel_id: int | None = None
    max_age_seconds: int | None = DEFAULT_MAX_AGE
    mode: str = DEFAULT_MODE
    run_every_seconds: int = DEFAULT_RUN_EVERY
    skip_pinned: bool = True
    existing: bool = False

    def is_complete(self) -> bool:
        """Whether the state has enough to save (a channel and a max age)."""
        return self.channel_id is not None and self.max_age_seconds is not None

    def to_upsert_kwargs(self, guild_id: int) -> dict[str, Any]:
        """Keyword args for ``Database.upsert_rule``."""
        return {
            "guild_id": guild_id,
            "channel_id": self.channel_id,
            "max_age_seconds": self.max_age_seconds,
            "mode": self.mode,
            "skip_pinned": self.skip_pinned,
            "run_every_seconds": self.run_every_seconds,
        }


def build_panel_embed(state: PanelState) -> discord.Embed:
    """Render the live summary embed for the current selections."""
    complete = state.is_complete()
    intro = (
        "✏️ **Editing this channel's existing rule.** Adjust anything below."
        if state.existing
        else "Set up automatic message cleanup for a channel."
    )
    embed = discord.Embed(
        title="🧹 Channel cleanup setup",
        description=f"{intro}\n\n{HOW_TO}",
        color=discord.Color.blurple() if complete else discord.Color.greyple(),
    )
    embed.add_field(
        name="Channel",
        value=f"<#{state.channel_id}>" if state.channel_id else "*none selected*",
        inline=False,
    )
    embed.add_field(
        name="Delete messages older than",
        value=(
            humanize_duration(state.max_age_seconds)
            if state.max_age_seconds
            else "*not set*"
        ),
    )
    embed.add_field(name="Action", value=MODE_LABELS.get(state.mode, state.mode))
    embed.add_field(name="Runs every", value=humanize_duration(state.run_every_seconds))
    embed.add_field(name="Skip pinned", value="Yes" if state.skip_pinned else "No")
    if not complete:
        embed.set_footer(text="Select a channel and a max age to enable Save.")
    return embed


async def persist_state(db: Any, guild_id: int, state: PanelState) -> None:
    """Save the panel's state as a channel rule (the unit-testable seam)."""
    await db.upsert_rule(**state.to_upsert_kwargs(guild_id))


def _duration_options(
    presets: list[tuple[str, int]], selected: int | None
) -> list[discord.SelectOption]:
    options = [
        discord.SelectOption(label=label, value=str(secs), default=(selected == secs))
        for label, secs in presets
    ]
    options.append(
        discord.SelectOption(
            label="Custom…", value=CUSTOM_VALUE, description="Enter your own duration"
        )
    )
    return options


def _mode_options(selected: str) -> list[discord.SelectOption]:
    return [
        discord.SelectOption(
            label="Delete only",
            value="delete",
            description="Permanently delete aged messages",
            default=selected == "delete",
        ),
        discord.SelectOption(
            label="Archive then delete",
            value="archive_delete",
            description="Save a copy to the database, then delete",
            default=selected == "archive_delete",
        ),
    ]


# -- discord.ui components -------------------------------------------------


class DurationModal(discord.ui.Modal):
    """Free-text duration entry for the 'Custom…' dropdown option."""

    def __init__(self, panel: "ConfigPanelView", target: str, title: str) -> None:
        super().__init__(title=title)
        self.panel = panel
        self.target = target  # "max_age" or "run_every"
        self.value_input = discord.ui.TextInput(
            label="Duration",
            placeholder="e.g. 45m, 2d, 1w3d",
            required=True,
            max_length=32,
        )
        self.add_item(self.value_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            seconds = parse_duration(self.value_input.value)
        except DurationError as exc:
            await interaction.response.send_message(f"⚠️ {exc}", ephemeral=True)
            return
        if self.target == "max_age":
            self.panel.state.max_age_seconds = seconds
        else:
            self.panel.state.run_every_seconds = seconds
        await self.panel.refresh(interaction)


class _ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self) -> None:
        super().__init__(
            channel_types=[discord.ChannelType.text],
            placeholder="Select a channel…",
            min_values=1,
            max_values=1,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.on_channel_selected(interaction, self.values[0].id)


class _ModeSelect(discord.ui.Select):
    def __init__(self, state: PanelState) -> None:
        super().__init__(placeholder="Action…", options=_mode_options(state.mode), row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.state.mode = self.values[0]
        await self.view.refresh(interaction)


class _AgeSelect(discord.ui.Select):
    def __init__(self, state: PanelState) -> None:
        super().__init__(
            placeholder="Delete messages older than…",
            options=_duration_options(AGE_PRESETS, state.max_age_seconds),
            row=2,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == CUSTOM_VALUE:
            await interaction.response.send_modal(
                DurationModal(self.view, "max_age", "Custom max age")
            )
            return
        self.view.state.max_age_seconds = int(self.values[0])
        await self.view.refresh(interaction)


class _FreqSelect(discord.ui.Select):
    def __init__(self, state: PanelState) -> None:
        super().__init__(
            placeholder="How often to run…",
            options=_duration_options(FREQ_PRESETS, state.run_every_seconds),
            row=3,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.values[0] == CUSTOM_VALUE:
            await interaction.response.send_modal(
                DurationModal(self.view, "run_every", "Custom frequency")
            )
            return
        self.view.state.run_every_seconds = int(self.values[0])
        await self.view.refresh(interaction)


def _skip_label(state: PanelState) -> str:
    return f"Skip pinned: {'On' if state.skip_pinned else 'Off'}"


class _SkipPinnedButton(discord.ui.Button):
    def __init__(self, state: PanelState) -> None:
        super().__init__(
            style=discord.ButtonStyle.secondary, label=_skip_label(state), row=4
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.state.skip_pinned = not self.view.state.skip_pinned
        self.label = _skip_label(self.view.state)
        await self.view.refresh(interaction)


class _SaveButton(discord.ui.Button):
    def __init__(self, state: PanelState) -> None:
        super().__init__(
            style=discord.ButtonStyle.success,
            label="Save",
            row=4,
            disabled=not state.is_complete(),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.on_save(interaction)


class _DisableButton(discord.ui.Button):
    def __init__(self, state: PanelState) -> None:
        super().__init__(
            style=discord.ButtonStyle.danger,
            label="Disable rule",
            row=4,
            disabled=state.channel_id is None,
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.on_disable(interaction)


class ConfigPanelView(discord.ui.View):
    """The interactive panel opened by ``/setup``."""

    def __init__(
        self,
        db: Any,
        guild_id: int,
        author_id: int,
        state: PanelState,
        *,
        timeout: float = PANEL_TIMEOUT,
    ) -> None:
        super().__init__(timeout=timeout)
        self.db = db
        self.guild_id = guild_id
        self.author_id = author_id
        self.state = state
        self.message: discord.Message | None = None

        self.channel_select = _ChannelSelect()
        self.mode_select = _ModeSelect(state)
        self.age_select = _AgeSelect(state)
        self.freq_select = _FreqSelect(state)
        self.skip_button = _SkipPinnedButton(state)
        self.save_button = _SaveButton(state)
        self.disable_button = _DisableButton(state)
        for item in (
            self.channel_select,
            self.mode_select,
            self.age_select,
            self.freq_select,
            self.skip_button,
            self.save_button,
            self.disable_button,
        ):
            self.add_item(item)

    # -- guards -----------------------------------------------------------

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "🚫 This panel isn't yours — run `/setup` to open your own.",
                ephemeral=True,
            )
            return False
        perms = getattr(interaction.user, "guild_permissions", None)
        if perms is None or not perms.manage_messages:
            await interaction.response.send_message(
                "🚫 You need the **Manage Messages** permission.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # -- rendering --------------------------------------------------------

    def _sync_controls(self) -> None:
        self.save_button.disabled = not self.state.is_complete()
        self.disable_button.disabled = self.state.channel_id is None
        self.skip_button.label = _skip_label(self.state)
        self.mode_select.options = _mode_options(self.state.mode)
        self.age_select.options = _duration_options(
            AGE_PRESETS, self.state.max_age_seconds
        )
        self.freq_select.options = _duration_options(
            FREQ_PRESETS, self.state.run_every_seconds
        )

    async def refresh(self, interaction: discord.Interaction) -> None:
        self._sync_controls()
        await interaction.response.edit_message(
            embed=build_panel_embed(self.state), view=self
        )

    # -- actions ----------------------------------------------------------

    async def on_channel_selected(
        self, interaction: discord.Interaction, channel_id: int
    ) -> None:
        self.state.channel_id = channel_id
        existing = await self.db.get_rule(channel_id)
        if existing is not None:
            self.state.max_age_seconds = existing.max_age_seconds
            self.state.mode = existing.mode
            self.state.run_every_seconds = existing.run_every_seconds
            self.state.skip_pinned = existing.skip_pinned
            self.state.existing = True
        else:
            self.state.existing = False
        await self.refresh(interaction)

    async def on_save(self, interaction: discord.Interaction) -> None:
        if not self.state.is_complete():
            await interaction.response.send_message(
                "⚠️ Pick a channel and a max age first.", ephemeral=True
            )
            return
        await persist_state(self.db, self.guild_id, self.state)
        for item in self.children:
            item.disabled = True
        summary = (
            f"✅ Saved. <#{self.state.channel_id}> will delete messages older than "
            f"**{humanize_duration(self.state.max_age_seconds)}** — "
            f"**{MODE_LABELS[self.state.mode]}**, running every "
            f"**{humanize_duration(self.state.run_every_seconds)}**"
            f"{' (skipping pinned)' if self.state.skip_pinned else ''}."
        )
        await interaction.response.edit_message(content=summary, embed=None, view=self)
        self.stop()

    async def on_disable(self, interaction: discord.Interaction) -> None:
        if self.state.channel_id is None:
            await interaction.response.send_message(
                "⚠️ Select a channel first.", ephemeral=True
            )
            return
        existed = await self.db.disable_rule(self.state.channel_id)
        for item in self.children:
            item.disabled = True
        msg = (
            f"🛑 Aging disabled for <#{self.state.channel_id}>."
            if existed
            else f"ℹ️ <#{self.state.channel_id}> had no rule to disable."
        )
        await interaction.response.edit_message(content=msg, embed=None, view=self)
        self.stop()
