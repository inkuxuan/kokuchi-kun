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
- **utils/scheduler.py** — APScheduler wrapper. Persists jobs to `data/jobs.json` and restores them on restart.
- **utils/vrchat_api.py** — VRChat API client. Cookie-based auth with 2FA (Email OTP and TOTP). Caches session in `vrchat_session.json`.
- **utils/persistence.py** — Simple JSON file persistence layer for `data/` directory.
- **utils/messages.py** — Centralized message constants. Use `Discord.*` for bot responses and `Log.*` for logger calls.

### Configuration

- **config.yaml** — Discord channel IDs, admin role, emoji reactions, OpenRouter model, VRChat group ID.
- **`.env`** — Secret credentials. See `.prd.env.template` for required keys.

### State Persistence (`data/` directory)

| File | Contents |
|------|----------|
| `data/pending.json` | Message ID → request mapping for unapproved announcements |
| `data/jobs.json` | Scheduled job metadata (restored on restart) |
| `data/history.json` | Completed announcements |
| `data/calendar_events.json` | VRChat calendar event IDs |

### Versioning

Single source of truth is the `version` field in `pyproject.toml`. Use `scripts/bump_version.py` to bump — it commits and tags automatically. Never manually edit the version.

# Documentation

End-user documentation lives in `docs/`. It is a [VitePress](https://vitepress.dev/) site with two locales:

- `docs/index.md` — Japanese home page (default locale, served at `/`)
- `docs/ja/` — Japanese pages
- `docs/en/` — English pages (served at `/en/`)
- `docs/.vitepress/config.mts` — VitePress configuration

Node.js is required to work on the docs. Dependencies are declared in `package.json` at the repo root.

```bash
npm install       # first-time setup
npm run docs:dev  # start local dev server at http://localhost:5173/vspc-bot/
npm run docs:build   # build static site to docs/.vitepress/dist
npm run docs:preview # preview the built site locally
```

The docs are deployed to GitHub Pages automatically via `.github/workflows/deploy-docs.yml` when changes to `docs/**` are pushed to `main`. The live site is at `https://inkuxuan.github.io/vspc-bot/`.

Do **not** commit `node_modules/` or `docs/.vitepress/dist` — they are excluded in `.gitignore`.

# Coding Guidelines

- Messages sent by the bot should be stored as constants in `utils/messages.py`
- Logs can be literals
- All timezone calculations use JST (`Asia/Tokyo`)
