This file contains information of the business logic architecture of the repo.
It is not meant to be read by agents, but only human.
However, if any change is made to the logic, this file should be changes accordingly to give human a better understanding of the repo.

### Module Structure

```
bot.py                  Entry point — initializes all components and wires them together
├─→ StateManager        (utils/state_manager.py) Owns per-guild state, persistence, and Scheduler
│   ├─→ GuildContext       Pre-resolved per-guild references (state, group_id, admin_role_id, etc.)
│   ├─→ AnnouncementState  (utils/announcement_state.py) In-memory state per guild
│   ├─→ Persistence        (utils/persistence.py) Firestore read/write per guild
│   ├─→ Scheduler          (utils/scheduler.py) Job scheduling, status, persistence + cancel
│   └─→ VRChatAPI          (utils/vrchat_api.py) Calendar event deletion on cancel
├─→ AuthCog             (cogs/auth.py) OTP handling — bot-level admin DM interactions
│   └─→ VRChatAPI          Sets OTP callback for 2FA
├─→ AnnouncementCog     (cogs/announcement.py) Announcement workflow + reactions
│   ├─→ AIProcessor        (utils/ai_processor.py) Extract event details from messages
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
