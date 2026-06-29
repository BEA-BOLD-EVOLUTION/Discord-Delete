"""Serialize a Discord message into a row payload for ``archived_messages``.

Kept free of any ``discord`` import so it can be unit-tested against lightweight
stub objects that mimic the small surface we rely on.
"""

from __future__ import annotations

from typing import Any


def serialize(message: Any) -> dict:
    """Turn a ``discord.Message``-like object into an archive payload dict.

    Only attributes that exist on ``discord.Message`` are accessed:
    ``guild``, ``channel.id``, ``id``, ``author``, ``content``,
    ``attachments``, ``embeds``, ``created_at``.
    """
    guild_id = getattr(message.guild, "id", None) if message.guild else None

    attachments = [
        {
            "filename": att.filename,
            "url": att.url,
            "content_type": getattr(att, "content_type", None),
            "size": getattr(att, "size", None),
        }
        for att in message.attachments
    ]

    embeds = [embed.to_dict() for embed in message.embeds]

    return {
        "guild_id": guild_id,
        "channel_id": message.channel.id,
        "message_id": message.id,
        "author_id": getattr(message.author, "id", None),
        "author_name": str(message.author) if message.author is not None else None,
        "content": message.content,
        "attachments": attachments,
        "embeds": embeds,
        "message_created_at": message.created_at,
    }
