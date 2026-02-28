# Contributing

## Python environment

Create your development environment by
```bash
uv venv --python 3.12
uv sync
```

Do NOT use `pip install`

Whenever you need a new package installed or updated, modify pyproject.toml using `uv`, and update `requirements.txt`.
For example
```bash
uv add numpy
uv export --format requirements.txt --output-file requirements.txt
```

Whenever you need to run a python-related commands, run it like
```bash
uv run python
```

```bash
uv run pytest
```

When making a PR, make sure to include changes in `pyproject.toml`, `lock.uv` and `requirements.txt` if you installed or updated packages.


# Documentation

End-user documentation lives in `docs/`. It is a [VitePress](https://vitepress.dev/) site with two locales:

The docs are deployed to GitHub Pages automatically via `.github/workflows/deploy-docs.yml` when changes to `docs/**` are pushed to `main`.

Do **not** commit `node_modules/` or `docs/.vitepress/dist` — they are excluded in `.gitignore`.

# Architecture

[ARCHITECTURE.md](ARCHITECTURE.md) gives a general pircture of the business logic design. The file is not intended for agents to read, but only for human to refer to.

# Coding Guidelines

- Messages sent by the bot should be stored as constants in `src/kokuchi/common/messages.py`
- Logs can be literals
- All timezone calculations use JST (`Asia/Tokyo`)
- **If you change any logic** (state transitions, job lifecycle, reaction handling, etc.), update the relevant sections in [ARCHITECTURE.md](ARCHITECTURE.md) updated.
- Always create type-annotated functions
