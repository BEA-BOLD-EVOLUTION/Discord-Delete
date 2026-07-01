"""No-network tests for the sweeper's per-message delete outcomes."""

from types import SimpleNamespace

import discord
import pytest

from bot.cogs.sweeper_cog import SweeperCog


def _make_cog():
    # Bypass __init__ (which touches the tasks loop); we only exercise _delete_one.
    return SweeperCog.__new__(SweeperCog)


def _fake_message(delete_exc=None):
    async def delete():
        if delete_exc is not None:
            raise delete_exc

    return SimpleNamespace(id=123, delete=delete)


@pytest.mark.asyncio
async def test_delete_one_success_returns_true():
    cog = _make_cog()
    assert await cog._delete_one(_fake_message()) is True


@pytest.mark.asyncio
async def test_delete_one_not_found_returns_none():
    # A 404 means the message is already gone — not a failure.
    exc = discord.NotFound(
        SimpleNamespace(status=404, reason="Not Found"), "Unknown Message"
    )
    cog = _make_cog()
    assert await cog._delete_one(_fake_message(delete_exc=exc)) is None


@pytest.mark.asyncio
async def test_delete_one_http_error_returns_false():
    exc = discord.HTTPException(
        SimpleNamespace(status=500, reason="Server Error"), "boom"
    )
    cog = _make_cog()
    assert await cog._delete_one(_fake_message(delete_exc=exc)) is False
