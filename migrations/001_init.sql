-- Schema for the Discord message aging bot.
-- Applied idempotently on startup by bot/db.py.

-- One configuration row per managed channel.
CREATE TABLE IF NOT EXISTS channel_rules (
    guild_id          BIGINT      NOT NULL,
    channel_id        BIGINT      PRIMARY KEY,
    max_age_seconds   BIGINT      NOT NULL CHECK (max_age_seconds > 0),
    mode              TEXT        NOT NULL CHECK (mode IN ('archive_delete', 'delete')),
    skip_pinned       BOOLEAN     NOT NULL DEFAULT TRUE,
    enabled           BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_channel_rules_guild ON channel_rules (guild_id);

-- Saved copies of messages archived before deletion.
CREATE TABLE IF NOT EXISTS archived_messages (
    id                  BIGSERIAL   PRIMARY KEY,
    guild_id            BIGINT,
    channel_id          BIGINT      NOT NULL,
    message_id          BIGINT      NOT NULL UNIQUE,
    author_id           BIGINT,
    author_name         TEXT,
    content             TEXT,
    attachments         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    embeds              JSONB       NOT NULL DEFAULT '[]'::jsonb,
    message_created_at  TIMESTAMPTZ,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_archived_channel_time
    ON archived_messages (channel_id, message_created_at);
