# Versioning Guide

This project follows a strict versioning process with `pyproject.toml` as the single source of truth.

## Current Version
The current version is defined in `pyproject.toml` under `[project]`:
```toml
version = "1.5.0"
```

## How to Bump Version

We use a helper script `scripts/bump_version.py` to automate the process. This script will:
1. Read the current version from `pyproject.toml`.
2. Calculate the new version.
3. Update `pyproject.toml`.
4. Commit the change to git.
5. Create a git tag (e.g., `v1.5.0`).

### Usage

```bash
# Bump patch (1.5.0 -> 1.5.1)
python scripts/bump_version.py patch

# Bump minor (1.5.0 -> 1.6.0)
python scripts/bump_version.py minor

# Bump major (1.5.0 -> 2.0.0)
python scripts/bump_version.py major

# Set specific version
python scripts/bump_version.py 2.0.0
```

### Options
- `--no-git`: Updates the file but skips git commit and tag steps.

## Post-Release
After running the script, push the changes and tags:
```bash
git push && git push --tags
```

## Code Usage
In the code, access the version using `utils.version.get_version()`:
```python
from utils.version import get_version
print(f"Current version: {get_version()}")
```
