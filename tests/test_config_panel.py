import pytest

from bot.duration import DurationError, parse_duration
from bot.ui.config_panel import (
    DEFAULT_MAX_AGE,
    DEFAULT_MODE,
    DEFAULT_RUN_EVERY,
    MODE_LABELS,
    PanelState,
    build_panel_embed,
    persist_state,
)


class FakeDB:
    """Records upsert_rule calls so we can assert what would be saved."""

    def __init__(self):
        self.calls = []

    async def upsert_rule(self, **kwargs):
        self.calls.append(("upsert_rule", kwargs))


def test_defaults_are_sensible():
    state = PanelState()
    assert state.max_age_seconds == DEFAULT_MAX_AGE
    assert state.run_every_seconds == DEFAULT_RUN_EVERY
    assert state.mode == DEFAULT_MODE
    assert state.skip_pinned is True


def test_is_complete_requires_channel_and_age():
    assert PanelState().is_complete() is False  # no channel yet
    assert PanelState(channel_id=42).is_complete() is True
    assert PanelState(channel_id=42, max_age_seconds=None).is_complete() is False


def test_to_upsert_kwargs_matches_db_signature():
    state = PanelState(
        channel_id=222,
        max_age_seconds=7 * 86_400,
        mode="archive_delete",
        run_every_seconds=3 * 86_400,
        skip_pinned=False,
    )
    kwargs = state.to_upsert_kwargs(guild_id=111)
    assert kwargs == {
        "guild_id": 111,
        "channel_id": 222,
        "max_age_seconds": 7 * 86_400,
        "mode": "archive_delete",
        "skip_pinned": False,
        "run_every_seconds": 3 * 86_400,
    }


@pytest.mark.asyncio
async def test_persist_state_calls_upsert_once():
    db = FakeDB()
    state = PanelState(channel_id=222)
    await persist_state(db, guild_id=111, state=state)
    assert len(db.calls) == 1
    name, kwargs = db.calls[0]
    assert name == "upsert_rule"
    assert kwargs["guild_id"] == 111
    assert kwargs["channel_id"] == 222
    assert kwargs["mode"] == DEFAULT_MODE


def test_build_panel_embed_reflects_state():
    state = PanelState(
        channel_id=222,
        max_age_seconds=3 * 86_400,
        mode="delete",
        run_every_seconds=86_400,
        skip_pinned=True,
    )
    embed = build_panel_embed(state)
    fields = {f.name: f.value for f in embed.fields}
    assert fields["Channel"] == "<#222>"
    assert fields["Delete messages older than"] == "3d"
    assert fields["Action"] == MODE_LABELS["delete"]
    assert fields["Runs every"] == "1d"
    assert fields["Skip pinned"] == "Yes"


def test_build_panel_embed_incomplete_has_footer():
    embed = build_panel_embed(PanelState())  # no channel selected
    assert embed.fields[0].value == "*none selected*"
    assert embed.footer.text is not None


def test_build_panel_embed_includes_instructions():
    # The panel must explain itself so it's usable without external docs.
    desc = build_panel_embed(PanelState()).description
    assert "How to use" in desc
    assert "Pick a channel" in desc
    assert "Custom" in desc  # mentions the custom-duration option


@pytest.mark.parametrize("text", ["45m", "2d", "1w3d"])
def test_custom_duration_parses(text):
    assert parse_duration(text) > 0


def test_custom_duration_rejects_bad_input():
    with pytest.raises(DurationError):
        parse_duration("nonsense")
