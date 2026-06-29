import datetime as dt

from bot.db import ChannelRule

NOW = dt.datetime(2026, 6, 29, 12, 0, 0, tzinfo=dt.timezone.utc)


def _rule(*, run_every_seconds=86_400, last_run_at=None):
    return ChannelRule(
        guild_id=1,
        channel_id=2,
        max_age_seconds=7 * 86_400,
        mode="delete",
        skip_pinned=True,
        enabled=True,
        run_every_seconds=run_every_seconds,
        last_run_at=last_run_at,
    )


def test_never_run_is_always_due():
    assert _rule(last_run_at=None).is_due(NOW) is True


def test_not_due_before_interval_elapses():
    # Ran 12h ago, runs daily -> not due yet.
    rule = _rule(run_every_seconds=86_400, last_run_at=NOW - dt.timedelta(hours=12))
    assert rule.is_due(NOW) is False


def test_due_once_interval_elapsed():
    # Ran exactly 1 day ago, runs daily -> due.
    rule = _rule(run_every_seconds=86_400, last_run_at=NOW - dt.timedelta(days=1))
    assert rule.is_due(NOW) is True


def test_due_well_past_interval():
    rule = _rule(run_every_seconds=3 * 86_400, last_run_at=NOW - dt.timedelta(days=10))
    assert rule.is_due(NOW) is True


def test_multi_day_cadence_not_due():
    # Ran 2 days ago, runs every 3 days -> not due.
    rule = _rule(run_every_seconds=3 * 86_400, last_run_at=NOW - dt.timedelta(days=2))
    assert rule.is_due(NOW) is False
