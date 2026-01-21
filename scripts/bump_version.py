#!/usr/bin/env python3
"""
Script to bump the version in pyproject.toml and optionally create a git tag.
Usage: python scripts/bump_version.py [major|minor|patch|new_version]
"""

import sys
import re
import argparse
import subprocess
from pathlib import Path

def get_current_version(pyproject_path):
    with open(pyproject_path, 'r') as f:
        content = f.read()
    match = re.search(r'version = "(\d+\.\d+\.\d+)"', content)
    if not match:
        raise ValueError("Could not find version in pyproject.toml")
    return match.group(1)

def bump_version_string(current_version, part):
    major, minor, patch = map(int, current_version.split('.'))
    if part == 'major':
        return f"{major + 1}.0.0"
    elif part == 'minor':
        return f"{major}.{minor + 1}.0"
    elif part == 'patch':
        return f"{major}.{minor}.{patch + 1}"
    elif re.match(r'^\d+\.\d+\.\d+$', part):
        return part
    else:
        raise ValueError("Invalid version argument. Use 'major', 'minor', 'patch', or a specific version string (X.Y.Z)")

def update_file(pyproject_path, old_version, new_version):
    with open(pyproject_path, 'r') as f:
        content = f.read()

    new_content = content.replace(f'version = "{old_version}"', f'version = "{new_version}"')

    with open(pyproject_path, 'w') as f:
        f.write(new_content)
    print(f"Updated pyproject.toml from {old_version} to {new_version}")

def git_commit_and_tag(new_version):
    try:
        # Check if git is available
        subprocess.run(["git", "--version"], check=True, capture_output=True)

        # Add pyproject.toml
        subprocess.run(["git", "add", "pyproject.toml"], check=True)

        # Commit
        msg = f"Bump version to {new_version}"
        subprocess.run(["git", "commit", "-m", msg], check=True)

        # Tag
        tag_name = f"v{new_version}"
        subprocess.run(["git", "tag", "-a", tag_name, "-m", f"Version {new_version}"], check=True)

        print(f"Committed and tagged {tag_name}")
        print("Don't forget to push: git push && git push --tags")

    except subprocess.CalledProcessError as e:
        print(f"Git operation failed: {e}")
    except FileNotFoundError:
        print("Git command not found. Skipping git operations.")

def main():
    parser = argparse.ArgumentParser(description="Bump version in pyproject.toml")
    parser.add_argument("version", help="major, minor, patch, or specific version (e.g. 1.2.3)")
    parser.add_argument("--no-git", action="store_true", help="Skip git commit and tag")

    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent
    pyproject_path = root_dir / 'pyproject.toml'

    try:
        current_version = get_current_version(pyproject_path)
        new_version = bump_version_string(current_version, args.version)

        if new_version == current_version:
            print(f"Version is already {new_version}")
            return

        update_file(pyproject_path, current_version, new_version)

        if not args.no_git:
            git_commit_and_tag(new_version)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
