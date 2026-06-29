import pytest

from bot.config import Config, ConfigError


@pytest.fixture
def base_env(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/discorddelete")
    monkeypatch.delenv("SWEEP_INTERVAL_MINUTES", raising=False)
    monkeypatch.delenv("ARCHIVE_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("DEV_GUILD_ID", raising=False)


def test_defaults(base_env):
    cfg = Config.from_env()
    assert cfg.discord_token == "token"
    assert cfg.sweep_interval_minutes == 60
    assert cfg.archive_retention_days == 90
    assert cfg.enable_message_content is True
    assert cfg.dev_guild_id is None


@pytest.mark.parametrize("value", ["false", "False", "0", "no", "off"])
def test_message_content_can_be_disabled(base_env, monkeypatch, value):
    monkeypatch.setenv("ENABLE_MESSAGE_CONTENT", value)
    assert Config.from_env().enable_message_content is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "anything-else"])
def test_message_content_enabled_for_truthy(base_env, monkeypatch, value):
    monkeypatch.setenv("ENABLE_MESSAGE_CONTENT", value)
    assert Config.from_env().enable_message_content is True


def test_localhost_url_is_accepted(base_env, monkeypatch):
    # Local dev / docker use a real host (localhost or 'db') and must work.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost:5432/dd")
    assert Config.from_env().database_url.endswith("/dd")


def test_hostless_url_is_rejected(base_env, monkeypatch):
    # Railway's broken `${{Postgres.DATABASE_URL}}` reference resolves to a
    # hostless URL; asyncpg would silently fall back to localhost otherwise.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@/dd")
    with pytest.raises(ConfigError, match="no host"):
        Config.from_env()


def test_missing_token_is_rejected(base_env, monkeypatch):
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        Config.from_env()
