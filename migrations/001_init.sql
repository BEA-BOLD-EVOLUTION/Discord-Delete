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
    -- How often this channel's cleanup runs, and when it last ran.
    run_every_seconds BIGINT      NOT NULL DEFAULT 86400 CHECK (run_every_seconds > 0),
    last_run_at       TIMESTAMPTZ,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_channel_rules_guild ON channel_rules (guild_id);

-- Upgrade existing deployments that predate the per-channel cadence columns.
ALTER TABLE channel_rules
    ADD COLUMN IF NOT EXISTS run_every_seconds BIGINT NOT NULL DEFAULT 86400;
ALTER TABLE channel_rules
    ADD COLUMN IF NOT EXISTS last_run_at TIMESTAMPTZ;

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

-- Supports the retention purge (delete rows older than N days).
CREATE INDEX IF NOT EXISTS idx_archived_archived_at
    ON archived_messages (archived_at);

-- Audit log of every bulk deletion performed by the bot.
CREATE TABLE IF NOT EXISTS deletion_logs (
    id             SERIAL      PRIMARY KEY,
    guild_id       TEXT        NOT NULL,
    channel_id     TEXT        NOT NULL,
    user_id        TEXT        NOT NULL,
    user_name      TEXT        NOT NULL,
    message_count  INT         NOT NULL,
    deletion_type  TEXT        NOT NULL CHECK (deletion_type IN ('manual', 'scheduled')),
    criteria       TEXT,
    reason         TEXT,
    deleted_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_deletion_logs_guild_time
    ON deletion_logs (guild_id, deleted_at DESC);
