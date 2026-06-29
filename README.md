# Discord Message Aging Bot

A Discord bot that manages channels by **aging out** messages — either
**archiving them to a database and then deleting**, or **just deleting** — on a
per-channel basis. Aging runs both on an **automatic schedule** and **on demand**
via admin slash commands.

## Features

- **Per-channel rules.** Each channel gets its own maximum message age and mode:
  - `archive_delete` — copy the message (content, attachments, embeds, author,
    timestamps) into PostgreSQL, then delete it.
  - `delete` — delete the message outright, no copy kept.
- **Automatic sweeps.** A background task scans every enabled channel on an
  interval (default hourly) and ages out anything past its threshold.
- **Manual sweeps.** Admins can run `/sweep` to process a channel immediately.
- **Pinned-message protection** (on by default, configurable per channel).
- **Durable archive** in PostgreSQL for later querying.

## Slash commands

All commands require the **Manage Messages** permission.

| Command | Description |
| --- | --- |
| `/aging set channel:<#channel> max_age:<duration> mode:<archive_delete\|delete> [run_every:<duration>] [skip_pinned:<bool>]` | Create or update a channel's rule. |
| `/aging disable channel:<#channel>` | Stop aging a channel (keeps its archive). |
| `/aging status [channel:<#channel>]` | Show a channel's current rule. |
| `/aging list` | List all rules in the server. |
| `/sweep [channel:<#channel>]` | Run the sweep now — one channel, or all configured channels. |

**Durations** accept compact forms: `30d`, `12h`, `45m`, `90s`, `2w`, or
combinations like `1d12h`. A bare number is seconds.

### Per-channel schedule

Each channel has two independent settings:

- **`max_age`** — how old a message must be before it qualifies for cleanup.
- **`run_every`** — how often that channel's cleanup actually runs (default
  **`1d`**). Set it to `3d`, `12h`, `1w`, etc. per channel.

The bot wakes up every `SWEEP_INTERVAL_MINUTES` (the global "tick", default 60),
but a given channel is only swept once its own `run_every` has elapsed since its
last run — so `run_every` is effectively rounded up to the tick. Running `/sweep`
manually processes the channel immediately and resets its cadence clock.

Example — clear messages older than 7 days, but only run the pass once a day:
`/aging set channel:#general max_age:7d mode:delete run_every:1d`

## Multi-server (public bot)

The bot is built to run across **many servers at once, fully isolated**:

- Every rule and archived message is tagged with its `guild_id`, and Discord
  channel/message IDs are globally unique — so one server can never see or affect
  another's configuration or data.
- Commands are **synced globally**, so they appear automatically in every server
  the bot joins (the first global sync can take up to ~1 hour to propagate;
  use `DEV_GUILD_ID` for instant availability while developing).
- When the bot is **removed from a server**, that server's rules are deleted
  automatically; its already-archived messages are retained (and still age out
  under the retention policy below). Deleting a channel removes its rule too.

> **One caveat:** a single bot token shares **one** global Discord rate-limit
> pool. Extremely heavy deletion in one server can briefly slow sweeps in others.
> This affects timing only — never data isolation.

## Archive retention

Archived messages are kept for at most **`ARCHIVE_RETENTION_DAYS`** (default
**90**) days. A daily background job deletes anything older. This keeps the
archive bounded and applies uniformly to every server.

## Requirements

- Python 3.10+
- A PostgreSQL database
- A Discord application/bot token

### Discord setup

1. Create an application at <https://discord.com/developers/applications>.
2. Under **Bot**, enable the **Message Content Intent** (required to read and
   archive message bodies). Copy the bot token. If you only use `delete` mode and
   don't want this privileged intent, set `ENABLE_MESSAGE_CONTENT=false` instead
   (archived text will then be empty). Without either, the bot exits on startup
   with a clear message telling you to enable the intent.
3. Invite the bot with the **`bot`** and **`applications.commands`** scopes and
   the **Manage Messages** + **Read Message History** permissions
   (`8192 + 65536 = 73728`). Ready-made invite link for this application:
   ```
   https://discord.com/api/oauth2/authorize?client_id=1491207826477940877&scope=bot%20applications.commands&permissions=73728
   ```
   (Replace the `client_id` if you deploy under a different application.)

## Configuration

Copy `.env.example` to `.env` and fill in:

| Variable | Required | Default | Notes |
| --- | --- | --- | --- |
| `DISCORD_TOKEN` | ✅ | — | Bot token. |
| `DATABASE_URL` | ✅ | — | e.g. `postgresql://user:pass@host:5432/discorddelete`. |
| `SWEEP_INTERVAL_MINUTES` | | `60` | How often the automatic sweep runs. |
| `ARCHIVE_RETENTION_DAYS` | | `90` | Archived messages older than this are purged daily. |
| `ENABLE_MESSAGE_CONTENT` | | `true` | Request the Message Content Intent (needed to archive text). Set `false` for delete-only mode without the privileged intent. |
| `DEV_GUILD_ID` | | — | Sync commands to one guild instantly during dev. Leave blank for global sync. |

## Running

### With Docker (bot + Postgres together)

```bash
cp .env.example .env      # set DISCORD_TOKEN (DATABASE_URL is provided by compose)
docker compose up --build
```

This starts PostgreSQL and the bot; the database schema is created automatically
on first boot.

### Locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env      # fill in DISCORD_TOKEN and DATABASE_URL
python -m bot.main
```

### On Railway

The repo is Railway-ready: `railway.toml` pins the Docker build and a restart
policy, and the bot runs as a background worker (no HTTP port or domain needed).

1. Create a project from this repo (**New Project → Deploy from GitHub repo**).
   Railway builds the `Dockerfile` automatically.
2. In that project, **add a database → PostgreSQL**. This creates a `Postgres`
   service exposing a `DATABASE_URL`.
3. Open the **bot service → Variables** and set:
   - `DISCORD_TOKEN` = your bot token
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (reference the Postgres service
     so they connect over Railway's private network)
   - *(optional)* `SWEEP_INTERVAL_MINUTES`, `DEV_GUILD_ID`
4. Deploy. The schema is created on first boot; watch the deploy logs for
   `Logged in as ...`.

> **Other hosts:** the bot just needs a long-running Python process and a Postgres
> URL — a VPS, a home server/Raspberry Pi via `docker compose`, or Fly.io/Render
> all work the same way. Railway is just one option.

## Testing

Unit tests cover the duration parser and the archive serializer — no database or
network needed:

```bash
pip install -r requirements.txt
pytest
```

## How it works

- `bot/main.py` — sets up intents (incl. message content), connects the DB pool,
  loads cogs, and syncs slash commands.
- `bot/db.py` — asyncpg pool, idempotent schema bootstrap (`migrations/001_init.sql`),
  and typed query helpers.
- `bot/cogs/config_cog.py` — the `/aging` command group.
- `bot/cogs/sweeper_cog.py` — the scheduled `tasks.loop` sweep and `/sweep`.
- `bot/archive.py` / `bot/duration.py` — message serialization and duration parsing.

### A note on the 14-day rule

Discord's bulk-delete API only works on messages **younger than 14 days**.
Anything older is deleted one-by-one (slower, rate-limited). For channels you
want fully cleared on the first run, expect older messages to take longer.

## Roadmap (not in v1)

- Restoring archived messages back into Discord.
- A web dashboard / search UI over the archive.
- Multi-instance coordination (v1 assumes a single bot instance).
