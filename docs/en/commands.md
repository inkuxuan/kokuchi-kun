# Commands Reference

All commands support both prefix form (`!command`) and slash command form (`/command`).

## General commands

Available to all users in any channel.

| Command | Description |
|---------|-------------|
| `!ping` or `/ping` | Check if the bot is online. Returns the current version. |
| `!version` or `/version` | Display the current bot version. |

## Admin commands

**Requires the admin role.** Must be used inside the monitored announcement channel.

| Command | Description |
|---------|-------------|
| `!list` or `/list` | List all currently scheduled announcements with their job IDs and scheduled times. |
| `!cancel <job_id>` or `/cancel` | Cancel a scheduled announcement by its job ID. |
| `!help` or `/help` | Display the admin command list. |

## Command details

### `!list` / `/list`

If there are scheduled announcements, an embed is shown with:

- Job ID
- Scheduled post time
- Title
- Content (truncated if too long)

If there are no scheduled announcements, the bot replies with "予約されている告知はありません。"

### `!cancel <job_id>` / `/cancel`

The job ID is shown in the **Job ID** field of the booking confirmation embed.

**Example:**
```
!cancel abc123
```

If successful, the bot confirms the cancellation. If the job ID is not found, the bot lets you know.
