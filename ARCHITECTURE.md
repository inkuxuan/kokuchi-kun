This file contains information of the business logic architecture of the repo.
It is not meant to be read by agents, but only human.
However, if any change is made to the logic, this file should be changes accordingly to give human a better understanding of the repo.

### Folder Structure

```
src/kokuchi/              Main Python package
├── cogs/                 discord.py Cogs — self-contained extensions that group related
│                         commands and event listeners into loadable modules
├── state/                Data ownership — in-memory per-guild state, Firestore
│                         persistence, and the StateManager facade
├── services/             External service integrations — VRChat API client,
│                         AI processor (OpenRouter), job scheduler (APScheduler)
└── common/               Shared utilities — data models/DTOs, string constants, version
tests/                    Test suite
scripts/                  Development scripts (version bumping, Firestore migration)
docs/                     VitePress documentation site (en + ja)
```

### Module Structure

```
bot.py                  Entry point — initializes all components and wires them together
├─→ StateManager        (state/state_manager.py) Owns per-guild state, persistence, and Scheduler
│   ├─→ GuildContext       Pre-resolved per-guild references (state, group_id, admin_role_id, etc.)
│   ├─→ AnnouncementState  (state/announcement_state.py) In-memory state per guild
│   ├─→ Persistence        (state/persistence.py) Firestore read/write per guild
│   ├─→ Scheduler          (services/scheduler.py) Job scheduling, status, persistence + cancel
│   └─→ VRChatAPI          (services/vrchat_api.py) Calendar event deletion on cancel
├─→ AuthCog             (cogs/auth.py) OTP handling — bot-level admin DM interactions
│   └─→ VRChatAPI          Sets OTP callback for 2FA
├─→ AnnouncementCog     (cogs/announcement.py) Announcement workflow + reactions
│   ├─→ AIProcessor        (services/ai_processor.py) Extract event details from messages
│   ├─→ StateManager       State, persistence, Scheduler (via state_manager.scheduler)
│   └─→ VRChatAPI          Post announcements, manage calendar events
├─→ AdminCog            (cogs/admin.py) Server admin commands (/list, /cancel, /help)
│   └─→ StateManager       State, Scheduler queries, cancel + persist
└─→ GeneralCog          (cogs/general.py) Miscellaneous commands
```

No cog-to-cog dependencies exist. Both `AnnouncementCog` and `AdminCog` depend on `StateManager` for state and scheduler operations rather than reaching into each other. Cogs access the scheduler via `state_manager.scheduler` rather than holding a direct reference. `AuthCog` handles bot-level admin concerns (OTP from the single bot admin), while `AdminCog` handles per-guild server admin commands.

Per-guild operations use `GuildContext` objects (obtained via `state_manager.get_guild_context(guild_id)`) which bundle pre-resolved references like `state`, `group_id`, `admin_role_id`, `enabled`, and `channel_ids`, eliminating repeated config lookups.

### Configuration

- **config.yaml** — Discord channel IDs, admin role, emoji reactions, OpenRouter model, VRChat group ID, Firestore server ID.
- **`.env`** — Secret credentials. See `.prd.env.template` for required keys.

### State Persistence (Firestore)

State is stored in Google Cloud Firestore. The bot uses Application Default Credentials (no key file needed on GCP VMs).

Per-announcement state lives under `servers/{server_id}/announcements/`. Shared state lives under `shared/`. (Collection names may differ according to `config.yaml`.)

**Design principle:** Announcement documents are **never deleted**. Fields are set to `None` or statuses are updated so the bot can always recover its full picture after a restart. Exactly one job is embedded per announcement document, making the 1-to-1 mapping structural.

#### `servers/{server_id}/announcements/{msg_id}`

Each document corresponds to one Discord request message and contains:

| Field | Type | Description |
|-------|------|-------------|
| `guild_id` | `str` | Discord server ID |
| `bot_reply_id` | `str \| null` | Discord message ID of the bot's confirmation reply |
| `calendar_event_id` | `str \| null` | VRChat calendar event ID (null if none or removed) |
| `completed` | `bool` | True if the announcement was successfully posted |
| `job` | `dict \| null` | Full serialized `JobData` (see fields below), or null if never scheduled |

Embedded `job` fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | UUID — the APScheduler job ID |
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

**Announcement lifecycle states** (derivable from the document):

| State | Condition |
|-------|-----------|
| `pending` | `job` is null (request registered, not yet approved) |
| `queued` | `job.status = "pending"` |
| `failed` | `job.status = "failed"` |
| `completed` | `completed = true` or `job.status = "success"` |
| `cancelled` | `job.status = "cancelled"` |
| `missed` | `job.status = "missed"` |

**Allowed actions by job status:**

| Action | pending | missed | failed | success | cancelled |
|--------|---------|--------|--------|---------|-----------|
| Fast-forward (⏩) | Yes | Yes | Yes (retry) | No | No |
| Calendar (📅) | Yes | Yes | Yes | Yes | No |
| Cancel | Yes | Yes | Yes | No | No |

Each announcement always has at most one job. The `schedule_announcement` call in the Scheduler removes all existing jobs for the same `message_id` before creating a new one, enforcing the 1-to-1 invariant.

#### Granular vs bulk saves

- **Granular** (`save_announcement(guild_id, msg_id)`): called after every single state transition (approval, completion, calendar change, cancel). Writes only the one affected document.
- **Bulk** (`save_state(guild_id)`): called only at startup after `load_state()` finishes, to persist any status updates (e.g. newly missed jobs). Iterates all known msg_ids and writes each.

#### Shared state (`shared/`)

| Document | Contents |
|----------|----------|
| `vrchat_session` | VRChat authentication cookies |

#### Lifecycle summary

```
User request   →  announcement doc created: {bot_reply_id: null, completed: false, job: null}
Admin approves →  announcement doc updated: {bot_reply_id: <id>, job: {status: "pending", ...}}
Calendar react →  announcement doc updated: {calendar_event_id: <id>}
Job fires OK   →  announcement doc updated: {completed: true, job.status: "success"}
Job fires fail →  announcement doc updated: {job.status: "failed"}
Fast-forward OK→  announcement doc updated: {completed: true, job.status: "success"}
Cancel         →  announcement doc updated: {job.status: "cancelled", bot_reply_id: null, calendar_event_id: null}
Bot restart    →  announcements subcollection loaded; jobs restored from embedded job dicts
                  past-due pending jobs within grace period → re-scheduled (fire immediately)
                  past-due pending jobs beyond grace period → status = missed (doc updated on bulk save)
                  terminal/missed jobs → kept in memory, not re-scheduled
```

#### Migration

To migrate from the old flat-list format (`pending`/`history`/`calendar`/`jobs` docs under `state/`) to per-announcement documents, run before deploying the new code:

```bash
uv run python scripts/migrate_firestore.py [--config config.yaml]
```

The older JSON-to-Firestore migration (now deprecated):

```bash
uv run python scripts/migrate_to_firestore.py [--server-id SERVER_ID]
```

### Versioning

Single source of truth is the `version` field in `pyproject.toml`. Use `scripts/bump_version.py` to bump — it commits and tags automatically.
