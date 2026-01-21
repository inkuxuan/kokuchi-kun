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
uv dd numpy
uv export --format requirements.txt --output-file requirements.txt
```

## Test codes

Test codes should always be committed and included in the PR

##

