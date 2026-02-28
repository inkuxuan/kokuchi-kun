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

### Environment Setup

This program runs on most environments that supports python.

You need to [install uv](https://docs.astral.sh/uv/getting-started/installation/) to manage dependencies.

After installing uv, create your environment by

```bash
git clone https://github.com/inkuxuan/kokuchi-kun.git
cd kokuchi-kun
uv venv --python 3.12
uv sync --frozen
```

### Configuration setup

Copy `.prd.env.template` to `.env` and fill in credentials (Discord token, VRChat username/password, OpenRouter API key).

Copy `config.yaml.template` to `config.yaml` and fill in configurations (Guild ID, Channel ID, User ID, VRChat Group ID).

```bash
cp .prd.env.template .env
cp config.yaml.template config.yaml
```

You need these external information setup for .env:
- A [Discord Bot](https://discord.com/developers/home) Token
- An [OpenRouter](https://openrouter.ai/) API Key
  - Yes, you need to pay for it, unless you change config.yaml to use a free model (which could fail)
- A VRChat account for the bot (OTP 2FA recommended)
- A Google Cloud Platform [Firestore database](https://console.cloud.google.com/firestore/databases), and a Service Account for the bot (set the path to ADC JSON file at `GOOGLE_APPLICATION_CREDENTIALS`)
  - The bot is unlikely to use up your GCP free tier so no worry on bills

You need these external information setup for config.yaml:
- The User ID of the bot's admin (for receiving login OTP requests)
- The Guild ID(s) of the Discord server(s)
- The Role ID(s) of who can approve requests in the Discord Server(s)
- The Channel ID(s) the bot should be monitoring
  - NOTE: All mentioned messages will be treated as a request so it is a good idea to restrict the access to the channel
- The VRChat Group ID(s) that is bound to each Discord Server(s)

Discord User/Guild/Role/Channel IDs can be retrieved by right clicking at a User / Server / Role or Channel and select "Copy ?? ID" (if not shown, enable Developer Mode in Settings)

The VRChat Group ID is the UUID starts with `grp_` in the URL when you access the webpage of the group

Note that:
- You need to manually invite the bot to your server
- The bot must have proper permissions to read, send messages, reactions and embedded messages
- The bot must have the following permissions in the VRChat Group:
  - Manage Group Announcement
  - Manage Group Calendar


## Run the bot

```bash
uv run --frozen -m kokuchi.bot
```

or alternatively use `run.bat` / `run.sh`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development environment setup, commands, architecture, and coding guidelines.


