import datetime as dt
from types import SimpleNamespace

from bot import archive


def _make_message():
    embed = SimpleNamespace(to_dict=lambda: {"title": "hi", "type": "rich"})
    attachment = SimpleNamespace(
        filename="cat.png",
        url="https://cdn.example/cat.png",
        content_type="image/png",
        size=1234,
    )
    return SimpleNamespace(
        guild=SimpleNamespace(id=111),
        channel=SimpleNamespace(id=222),
        id=333,
        author=SimpleNamespace(id=444, __str__=lambda self: "user#0001"),
        content="hello world",
        attachments=[attachment],
        embeds=[embed],
        created_at=dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
    )


def test_serialize_basic_fields():
    payload = archive.serialize(_make_message())
    assert payload["guild_id"] == 111
    assert payload["channel_id"] == 222
    assert payload["message_id"] == 333
    assert payload["author_id"] == 444
    assert payload["content"] == "hello world"
    assert payload["message_created_at"] == dt.datetime(
        2024, 1, 1, tzinfo=dt.timezone.utc
    )


def test_serialize_attachments_and_embeds():
    payload = archive.serialize(_make_message())
    assert payload["attachments"] == [
        {
            "filename": "cat.png",
            "url": "https://cdn.example/cat.png",
            "content_type": "image/png",
            "size": 1234,
        }
    ]
    assert payload["embeds"] == [{"title": "hi", "type": "rich"}]


def test_serialize_handles_no_guild():
    msg = _make_message()
    msg.guild = None
    payload = archive.serialize(msg)
    assert payload["guild_id"] is None


def test_serialize_empty_collections():
    msg = _make_message()
    msg.attachments = []
    msg.embeds = []
    payload = archive.serialize(msg)
    assert payload["attachments"] == []
    assert payload["embeds"] == []
