import pytest

from bot.duration import DurationError, humanize_duration, parse_duration


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30d", 30 * 86_400),
        ("12h", 12 * 3600),
        ("45m", 45 * 60),
        ("90s", 90),
        ("2w", 2 * 604_800),
        ("1d12h", 86_400 + 12 * 3600),
        ("1w2d3h4m5s", 604_800 + 2 * 86_400 + 3 * 3600 + 4 * 60 + 5),
        ("3600", 3600),  # bare integer = seconds
        ("  10m  ", 600),  # surrounding whitespace
        ("1D", 86_400),  # case-insensitive
    ],
)
def test_parse_valid(text, expected):
    assert parse_duration(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "abc", "10x", "1d2", "-5m", "0", "0s"])
def test_parse_invalid(text):
    with pytest.raises(DurationError):
        parse_duration(text)


def test_parse_none():
    with pytest.raises(DurationError):
        parse_duration(None)


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0s"),
        (90, "1m 30s"),
        (3600, "1h"),
        (86_400, "1d"),
        (86_400 + 12 * 3600, "1d 12h"),
        (604_800, "1w"),
    ],
)
def test_humanize(seconds, expected):
    assert humanize_duration(seconds) == expected


@pytest.mark.parametrize("text", ["30d", "12h", "45m", "1d12h", "1w2d3h4m5s"])
def test_roundtrip(text):
    # humanize(parse(x)) should itself re-parse to the same number of seconds.
    seconds = parse_duration(text)
    assert parse_duration(humanize_duration(seconds)) == seconds
