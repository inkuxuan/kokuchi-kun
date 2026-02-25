# Contributing

## Python environment

Create your development environment by
```bash
uv venv --python 3.12
uv sync
```

Be considerate to others, do NOT use `pip install`

Whenever you need a new package installed or updated, modify pyproject.toml using `uv`, and update `requirements.txt`.
For example
```bash
uv add numpy
uv export --format requirements.txt --output-file requirements.txt
```

Whenever you need to run a python-related commands, run it like
```bash
uv run pytest
```

When making a PR, make sure to include changes in `pyproject.toml`, `lock.uv` and `requirements.txt` if you installed or updated packages.

## Common Commands

```bash
# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_ai_processor.py

# Run a specific test
uv run pytest tests/test_scheduler.py::test_name

# Format code
uv run black .
uv run isort .

# Bump version (patch/minor/major or specific version)
python scripts/bump_version.py patch
```

## Test codes

Test codes should always be committed and included in the PR

## Architecture

### Key Components

- **bot.py** — Entry point. Initializes `VRChatAPI`, `Scheduler`, `AIProcessor`, and loads three cogs. Handles Discord OTP prompts for VRChat 2FA.
- **cogs/announcement.py** — Core logic. Manages the full announcement lifecycle: pending → queued → posted. Handles all emoji reaction events and state persistence.
- **cogs/admin.py** — Admin slash commands: `/list`, `/cancel`, `/help`.
- **utils/ai_processor.py** — OpenRouter (OpenAI-compatible) integration. Parses natural language Discord messages into structured JSON with announcement time, event time, title, and content.
- **utils/scheduler.py** — APScheduler wrapper. Job metadata persisted via Firestore and restored on restart.
- **utils/vrchat_api.py** — VRChat API client. Cookie-based auth with 2FA (Email OTP and TOTP). Session cached in Firestore (`shared/vrchat_session`).
- **utils/persistence.py** — Async Firestore persistence layer. Per-server state under `servers/{server_id}/state/`, shared state under `shared/`. Uses Application Default Credentials (ADC) on GCP.
- **utils/messages.py** — Centralized message constants. Use `Discord.*` for bot responses and `Log.*` for logger calls.

### Configuration

- **config.yaml** — Discord channel IDs, admin role, emoji reactions, OpenRouter model, VRChat group ID, Firestore server ID.
- **`.env`** — Secret credentials. See `.prd.env.template` for required keys.

### State Persistence (Firestore)

State is stored in Google Cloud Firestore. The bot uses Application Default Credentials (no key file needed on GCP VMs).

All per-server state lives under `servers/{server_id}/state/`. Shared state lives under `shared/`. (The names may differ according to `config.yaml`)

**Design principle:** Entries in `pending`, `jobs`, and `calendar` are **never deleted**. Instead, their values are set to `None` or their status is updated. This ensures the bot can always recover its full picture of known announcements after a restart.

#### `pending`

**Type:** `dict[str, str | None]` — maps Discord message ID of the user's request → Discord message ID of the bot's reply (or `None`).

**Purpose:** Tracks announcement requests through their lifecycle. The bot reply ID is used for reverse lookups (finding which request a reaction belongs to). Also serves as a guard against duplicate approvals — once `mark_queued` sets the bot reply ID, further approval reactions are ignored (`is_queued` returns `True`).

| When | Transition |
|------|------------|
| User mentions bot with a request | `pending[msg_id] = None` |
| Admin approves via reaction | `pending[msg_id] = bot_reply_id` |
| Job completes or is cancelled | Entry is **kept** (not deleted) — `history` and job status are the canonical records |
| Approval reaction removed (cancel) | `pending[msg_id] = None` (bot reply is deleted from Discord) |

#### `jobs`

**Type:** `list[dict]` — serialized `JobData` objects.

Each dict contains:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID, the APScheduler job ID |
| `message_id` | `str` | Discord message ID of the user's request |
| `timestamp` | `float` | Unix timestamp for when to post |
| `title` | `str` | Announcement title |
| `content` | `str` | Announcement body |
| `guild_id` | `str` | Discord server ID |
| `status` | `str` | `"pending"` / `"success"` / `"failed"` / `"missed"` / `"cancelled"` |
| `group_id` | `str \| None` | VRChat group ID |
| `event_start_timestamp` | `float \| None` | Event start time |
| `event_end_timestamp` | `float \| None` | Event end time |
| `event_title` | `str \| None` | Calendar event title |
| `formatted_date_time` | `str \| None` | Human-readable date string |

**Purpose:** Source of truth for all scheduled announcements. Enables `/list`, `/cancel`, fast-forward reposting, and restoration after restart.

| When | Transition |
|------|------------|
| Admin approves a request | New entry added with `status = "pending"` |
| Scheduled job fires successfully | `status` → `"success"` |
| Scheduled job fails (API error, auth error) | `status` → `"failed"` |
| Admin or user cancels | `status` → `"cancelled"` |
| On restart, past-due job beyond `misfire_grace_time` | `status` → `"missed"` |
| Fast-forward (⏩) succeeds on a missed/failed job | `status` → `"success"` |
| Fast-forward (⏩) fails | `status` → `"failed"` |

Jobs are **never deleted** from the list. All statuses are persisted so the bot has a complete picture after restart. Terminal jobs (`success`, `failed`, `cancelled`) and `missed` jobs are kept in memory but not re-scheduled with APScheduler.

**Allowed actions by status:**

| Action | pending | missed | failed | success | cancelled |
|--------|---------|--------|--------|---------|-----------|
| Fast-forward (⏩) | Yes | Yes | Yes (retry) | No | No |
| Calendar (📅) | Yes | Yes | Yes | Yes | No |
| Cancel | Yes | Yes | Yes | No | No |

#### `history`

**Type:** `list[str]` — list of Discord message IDs.

**Purpose:** Rolling log of completed announcements. Before accepting a new request, `is_in_history(msg_id)` is checked — if found, the bot replies "already booked." Capped at 1000 entries (oldest dropped).

| When | Transition |
|------|------------|
| Job completes successfully or immediate post succeeds | `history.append(msg_id)` |
| Length exceeds 1000 | Oldest entries trimmed |

Individual entries are never explicitly deleted.

#### `calendar`

**Type:** `dict[str, str | None]` — maps Discord message ID of the user's request → VRChat calendar event ID (or `None` if removed).

**Purpose:** Maps announcements to their VRChat group calendar events. Used to prevent duplicate calendar creation and to look up the event ID for deletion.

| When | Transition |
|------|------------|
| User/admin adds 📅 reaction | `calendar[msg_id] = event_id` |
| User/admin removes 📅 reaction | `calendar[msg_id] = None` (VRChat API deletes the event) |
| Announcement cancelled | `calendar[msg_id] = None` (VRChat API deletes the event) |

Entries are **set to `None`** rather than deleted, so the bot knows the message ID was once associated with a calendar event.

#### Shared state (`shared/`)

| Document | Contents |
|----------|----------|
| `vrchat_session` | VRChat authentication cookies |

#### Lifecycle summary

```
User request  →  pending[msg_id] = None
Admin approves →  pending[msg_id] = bot_reply_id  +  jobs gains new entry (status=pending)
Calendar react →  calendar[msg_id] = vrchat_event_id
Job fires OK   →  jobs status → success  +  history.append(msg_id)
Job fires fail →  jobs status → failed
Fast-forward OK→  jobs status → success  +  history.append(msg_id)
Cancel         →  jobs status → cancelled  +  pending[msg_id] = None  +  calendar[msg_id] = None
Bot restart    →  pending/jobs/history/calendar loaded from Firestore
                  past-due pending jobs within grace period → re-scheduled (fire immediately)
                  past-due pending jobs beyond grace period → status = missed
                  terminal/missed jobs → kept in memory, not re-scheduled
```

#### Migration from JSON files

(Deprecated)

```bash
uv run python scripts/migrate_to_firestore.py [--server-id SERVER_ID]
```

### Versioning

Single source of truth is the `version` field in `pyproject.toml`. Use `scripts/bump_version.py` to bump — it commits and tags automatically.

# Documentation

End-user documentation lives in `docs/`. It is a [VitePress](https://vitepress.dev/) site with two locales:

- `docs/index.md` — Japanese home page (default locale, served at `/`)
- `docs/ja/` — Japanese pages
- `docs/en/` — English pages (served at `/en/`)
- `docs/.vitepress/config.mts` — VitePress configuration

Node.js is required to work on the docs. Dependencies are declared in `package.json` at the repo root.

```bash
npm install       # first-time setup
npm run docs:dev  # start local dev server at http://localhost:5173/kokuchi-kun/
npm run docs:build   # build static site to docs/.vitepress/dist
npm run docs:preview # preview the built site locally
```

The docs are deployed to GitHub Pages automatically via `.github/workflows/deploy-docs.yml` when changes to `docs/**` are pushed to `main`. The live site is at `https://inkuxuan.github.io/kokuchi-kun/`.

Do **not** commit `node_modules/` or `docs/.vitepress/dist` — they are excluded in `.gitignore`.

# Coding Guidelines

- Messages sent by the bot should be stored as constants in `utils/messages.py`
- Logs can be literals
- All timezone calculations use JST (`Asia/Tokyo`)
- **If you change any logic** (state transitions, job lifecycle, reaction handling, etc.), update the relevant sections in this file — especially the [State Persistence](#state-persistence-firestore) section. Keeping documentation in sync with the code is required for PRs that modify bot behavior.
