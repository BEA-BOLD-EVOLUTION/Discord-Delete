"""Database access layer: connection pool, schema bootstrap, and queries."""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import asyncpg

log = logging.getLogger(__name__)

_MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql"

VALID_MODES = ("archive_delete", "delete")


@dataclass(frozen=True)
class ChannelRule:
    guild_id: int
    channel_id: int
    max_age_seconds: int
    mode: str
    skip_pinned: bool
    enabled: bool
    run_every_seconds: int
    last_run_at: dt.datetime | None

    @classmethod
    def from_row(cls, row: asyncpg.Record) -> "ChannelRule":
        return cls(
            guild_id=row["guild_id"],
            channel_id=row["channel_id"],
            max_age_seconds=row["max_age_seconds"],
            mode=row["mode"],
            skip_pinned=row["skip_pinned"],
            enabled=row["enabled"],
            run_every_seconds=row["run_every_seconds"],
            last_run_at=row["last_run_at"],
        )

    def is_due(self, now: dt.datetime) -> bool:
        """Whether this channel's cleanup should run at ``now``.

        A rule that has never run is always due; otherwise it is due once at
        least ``run_every_seconds`` have elapsed since the last run.
        """
        if self.last_run_at is None:
            return True
        elapsed = (now - self.last_run_at).total_seconds()
        return elapsed >= self.run_every_seconds


class Database:
    """Thin async wrapper around an asyncpg connection pool."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self.pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "Database":
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        db = cls(pool)
        await db.init_schema()
        return db

    async def close(self) -> None:
        await self.pool.close()

    async def init_schema(self) -> None:
        sql = _MIGRATION.read_text(encoding="utf-8")
        async with self.pool.acquire() as conn:
            await conn.execute(sql)
        log.info("Database schema ensured.")

    # -- channel_rules ----------------------------------------------------

    async def upsert_rule(
        self,
        *,
        guild_id: int,
        channel_id: int,
        max_age_seconds: int,
        mode: str,
        skip_pinned: bool,
        run_every_seconds: int,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid mode: {mode!r}")
        # Note: last_run_at is intentionally left untouched on conflict so that
        # editing a rule does not reset its cleanup cadence.
        await self.pool.execute(
            """
            INSERT INTO channel_rules
                (guild_id, channel_id, max_age_seconds, mode, skip_pinned,
                 run_every_seconds, enabled, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, TRUE, now())
            ON CONFLICT (channel_id) DO UPDATE SET
                guild_id          = EXCLUDED.guild_id,
                max_age_seconds   = EXCLUDED.max_age_seconds,
                mode              = EXCLUDED.mode,
                skip_pinned       = EXCLUDED.skip_pinned,
                run_every_seconds = EXCLUDED.run_every_seconds,
                enabled           = TRUE,
                updated_at        = now()
            """,
            guild_id,
            channel_id,
            max_age_seconds,
            mode,
            skip_pinned,
            run_every_seconds,
        )

    async def mark_rule_ran(self, channel_id: int) -> None:
        """Record that a channel's cleanup just ran (resets its cadence clock)."""
        await self.pool.execute(
            "UPDATE channel_rules SET last_run_at = now() WHERE channel_id = $1",
            channel_id,
        )

    async def disable_rule(self, channel_id: int) -> bool:
        """Disable a channel's rule. Returns True if a rule existed."""
        result = await self.pool.execute(
            "UPDATE channel_rules SET enabled = FALSE, updated_at = now() "
            "WHERE channel_id = $1",
            channel_id,
        )
        # asyncpg returns a status string like "UPDATE 1".
        return result.endswith("1")

    async def delete_rule(self, channel_id: int) -> bool:
        """Permanently remove a channel's rule. Returns True if one existed."""
        result = await self.pool.execute(
            "DELETE FROM channel_rules WHERE channel_id = $1", channel_id
        )
        return result.endswith("1")

    async def delete_rules_for_guild(self, guild_id: int) -> int:
        """Remove all rules for a guild (e.g. when the bot is kicked).

        Archived messages are intentionally left untouched. Returns the count
        of rules deleted.
        """
        result = await self.pool.execute(
            "DELETE FROM channel_rules WHERE guild_id = $1", guild_id
        )
        # Status string looks like "DELETE 3".
        return int(result.split()[-1]) if result else 0

    async def get_rule(self, channel_id: int) -> ChannelRule | None:
        row = await self.pool.fetchrow(
            "SELECT * FROM channel_rules WHERE channel_id = $1", channel_id
        )
        return ChannelRule.from_row(row) if row else None

    async def list_rules(
        self, guild_id: int, *, enabled_only: bool = False
    ) -> list[ChannelRule]:
        query = "SELECT * FROM channel_rules WHERE guild_id = $1"
        if enabled_only:
            query += " AND enabled = TRUE"
        query += " ORDER BY channel_id"
        rows = await self.pool.fetch(query, guild_id)
        return [ChannelRule.from_row(r) for r in rows]

    async def list_all_enabled_rules(self) -> list[ChannelRule]:
        rows = await self.pool.fetch(
            "SELECT * FROM channel_rules WHERE enabled = TRUE ORDER BY channel_id"
        )
        return [ChannelRule.from_row(r) for r in rows]

    # -- archived_messages ------------------------------------------------

    async def archive_message(self, payload: dict) -> None:
        """Insert one archived message. No-op if the message_id already exists."""
        await self.pool.execute(
            """
            INSERT INTO archived_messages
                (guild_id, channel_id, message_id, author_id, author_name,
                 content, attachments, embeds, message_created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9)
            ON CONFLICT (message_id) DO NOTHING
            """,
            payload["guild_id"],
            payload["channel_id"],
            payload["message_id"],
            payload["author_id"],
            payload["author_name"],
            payload["content"],
            json.dumps(payload["attachments"]),
            json.dumps(payload["embeds"]),
            payload["message_created_at"],
        )

    async def count_archived(self, channel_id: int) -> int:
        return await self.pool.fetchval(
            "SELECT count(*) FROM archived_messages WHERE channel_id = $1",
            channel_id,
        )

    async def purge_old_archives(self, retention_days: int) -> int:
        """Delete archived messages older than ``retention_days``.

        Returns the number of rows removed.
        """
        result = await self.pool.execute(
            "DELETE FROM archived_messages "
            "WHERE archived_at < now() - make_interval(days => $1)",
            retention_days,
        )
        return int(result.split()[-1]) if result else 0

    # -- deletion_logs ----------------------------------------------------

    async def log_deletion(
        self,
        *,
        guild_id: int,
        channel_id: int,
        user_id: int,
        user_name: str,
        message_count: int,
        deletion_type: str,
        criteria: str | None = None,
        reason: str | None = None,
    ) -> None:
        """Insert one deletion audit record.

        ``deletion_type`` must be ``'manual'`` or ``'scheduled'``.
        """
        await self.pool.execute(
            """
            INSERT INTO deletion_logs
                (guild_id, channel_id, user_id, user_name, message_count,
                 deletion_type, criteria, reason)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            str(guild_id),
            str(channel_id),
            str(user_id),
            user_name,
            message_count,
            deletion_type,
            criteria,
            reason,
        )

    async def list_deletion_logs(
        self, guild_id: int, *, limit: int = 10
    ) -> list[asyncpg.Record]:
        """Return the most recent deletion log entries for a guild.

        ``limit`` is clamped to [1, 50].
        """
        limit = max(1, min(limit, 50))
        return await self.pool.fetch(
            """
            SELECT id, channel_id, user_id, user_name, message_count,
                   deletion_type, criteria, reason, deleted_at
            FROM deletion_logs
            WHERE guild_id = $1
            ORDER BY deleted_at DESC
            LIMIT $2
            """,
            str(guild_id),
            limit,
        )
