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

**Per-server state** (`servers/{server_id}/state/`):

| Document | Contents |
|----------|----------|
| `pending` | Message ID → request mapping for unapproved announcements |
| `jobs` | Scheduled job metadata (restored on restart) |
| `history` | Completed announcements (max 1000) |
| `calendar` | VRChat calendar event IDs |

**Shared state** (`shared/`):

| Document | Contents |
|----------|----------|
| `vrchat_session` | VRChat authentication cookies |

**Migration from JSON files:**
```bash
uv run python scripts/migrate_to_firestore.py [--server-id SERVER_ID]
```

### Versioning

Single source of truth is the `version` field in `pyproject.toml`. Use `scripts/bump_version.py` to bump — it commits and tags automatically. Never manually edit the version.

# Coding Guidelines

- Messages sent by the bot should be stored as constants in `utils/messages.py`
- Logs can be literals
- All timezone calculations use JST (`Asia/Tokyo`)
