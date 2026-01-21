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

## Test codes

Test codes should always be committed and included in the PR

##

