"""No-network tests for guild/channel lifecycle cleanup listeners."""

from types import SimpleNamespace

import pytest

from bot.cogs.config_cog import ConfigCog


class FakeDB:
    """Records calls so we can assert what the listeners did."""

    def __init__(self, *, delete_rule_result=True, deleted_for_guild=2):
        self.calls = []
        self._delete_rule_result = delete_rule_result
        self._deleted_for_guild = deleted_for_guild

    async def delete_rule(self, channel_id):
        self.calls.append(("delete_rule", channel_id))
        return self._delete_rule_result

    async def delete_rules_for_guild(self, guild_id):
        self.calls.append(("delete_rules_for_guild", guild_id))
        return self._deleted_for_guild


def _make_cog(db):
    # Bypass __init__ to avoid constructing the app_commands.Group machinery.
    cog = ConfigCog.__new__(ConfigCog)
    cog.bot = SimpleNamespace()
    cog.db = db
    return cog


@pytest.mark.asyncio
async def test_on_guild_remove_deletes_rules_keeps_archive():
    db = FakeDB()
    cog = _make_cog(db)

    await cog.on_guild_remove(SimpleNamespace(id=999))

    assert db.calls == [("delete_rules_for_guild", 999)]
    # The archive must NOT be touched on guild removal.
    assert all(call[0] != "purge_old_archives" for call in db.calls)


@pytest.mark.asyncio
async def test_on_guild_channel_delete_removes_rule():
    db = FakeDB()
    cog = _make_cog(db)

    await cog.on_guild_channel_delete(SimpleNamespace(id=4242))

    assert db.calls == [("delete_rule", 4242)]
