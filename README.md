# kokuchi-kun

A Discord bot that schedules and posts VRChat group announcements via an emoji-based approval workflow.

DiscordのメッセージとリアクションだけでVRChatのグループ告知やカレンダーを簡単に管理できるボット

[User Manual | 使用説明書](https://inkuxuan.github.io/kokuchi-kun/)

**Announcement flow:**
1. User mentions the bot in a monitored channel → bot reacts with 👀
2. Admin adds 👍 to approve → AI extracts event details → announcement is queued
3. Bot posts a confirmation embed with ⏩ (post immediately) and 📅 (create calendar event) reactions
4. At the scheduled time → VRChat API posts the announcement to the group

## Setup

```bash
uv venv --python 3.12
```

Copy `.prd.env.template` to `.env` and fill in credentials (Discord token, VRChat username/password, OpenRouter API key).

Copy `config.yaml.template` to `config.yaml` and fill in configurations (Guild ID, Channel ID, User ID, VRChat Group ID).

Setup Firestore and Application Default Credentials.

## Run

```bash
uv run --frozen bot.py
```

## Contributing

See [AGENTS.md](AGENTS.md) for development environment setup, commands, architecture, and coding guidelines.


