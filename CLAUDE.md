# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **Where to add new content:**
> - Development setup, commands, coding conventions → [CONTRIBUTING.md](CONTRIBUTING.md) (read by all agents and human contributors)
> - Architecture changes → [ARCHITECTURE.md](ARCHITECTURE.md)
> - Project overview, usage → [README.md](README.md)
> - Only add content here if it is Claude Code-specific and not useful to other agents or humans.

## References

- [CONTRIBUTING.md](CONTRIBUTING.md) — Environment setup, common commands, architecture overview, coding guidelines
- [README.md](README.md) — Project description and how to run the bot
- [VERSIONING.md](VERSIONING.md) — Version management details

## Rules

- If you are unable to run `uv` command, it is probably because the user's main shell is zsh. Try `source ~/.zshrc` in that case
- Never ever implement any operation that deletes database entries which do not exceeds the maximum count, unless explicitly told to do that. Instead, ask for clarification or use flags
- If you are to delete a feature during a refactoring, make sure it's explicitly shown to your human. Do not delete any functionality without permission.
- Refactor bravely. Do not add backward-compatibility shims or fallback handling for old data formats in production code. If a change is breaking, provide a migration script and move on. At most, add a startup check that detects the old state and exits with a clear error message pointing to the migration script — do not silently handle it at runtime.
- With that being said, warn your human before making breaking changes.
