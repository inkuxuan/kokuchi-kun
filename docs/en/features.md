# What Can It Do?

Kokuchi Kun is a Discord bot that schedules VRChat group announcements from Discord. Send a message in the designated channel and the bot posts your announcement to VRChat at the specified time.

This page walks you through the entire process with screenshots.

::: warning Time zone
All dates and times are assumed to be in **JST (Japan Standard Time, UTC+9)**.
:::

## Announcement Workflow

### 1. Submit your request

Mention the bot in the announcement channel and describe your announcement in natural language.

Include:
- **Announcement title** (used for the post)
- **Post time in JST** (when to post)
- **Event start and end times in JST** (used for the calendar)
- **Event name** (used for the calendar)

No special formatting is required. Japanese and English both work.

::: tip Example
```
@kokuchi-kun
Post date: January 1, 2025 18:00

Announcement title: "Let's Play" Event Announcement

Announcement details:

"Let's Play" will be held from 20:00 to 21:00 on January 1, 2025!
Come join us for some fun!
Feel free to join or leave at any time.
Desktop mode and spectator participation are also welcome.
How to join: ......
Requirements/capacity: ......
```
:::

### 2. Bot acknowledges, admin approves

The bot reacts with 👀 to confirm it received your request. An admin then adds a 👍 reaction to approve it.

![The request message with the bot's 👀 reaction and an admin's 👍 approval](/images/request-and-approval.png)

::: info Key points
- 👀 means the bot has received your request
- Only members with the admin role can add 👍
- Your announcement is not scheduled until it is approved
:::

### 3. Booking confirmed

Once approved, the bot uses AI to parse the date, time, title, and content, then displays a booking confirmation embed.

![The booking confirmation embed showing post details, with ⏩ and 📅 reactions](/images/booked-embed.png)

The embed includes:
- **Post time** — when the announcement will be posted to VRChat
- **Event start and end times in JST** — used if a calendar creation is requested
- **Title** — extracted by AI
- **Content** — the announcement text
- **Job ID** — used for cancellation

Reactions available on the confirmation embed:

| Reaction | Effect |
|----------|--------|
| ⏩ | Post the announcement immediately instead of waiting |
| 📅 | Create a VRChat group calendar event |

::: warning
Only the original requester or an admin can use ⏩ and 📅.
:::

### 4. Posted to VRChat

At the scheduled time, the bot automatically posts the announcement to the VRChat group.

![The announcement as it appears in VRChat](/images/vrchat-announcement.png)

### 5. Calendar event (optional)

React with 📅 on the booking confirmation embed to create a VRChat group calendar event.

![A calendar event created in VRChat](/images/vrchat-calendar.png)

::: tip
Calendar event creation requires both a start time and end time in your original request. Removing the 📅 reaction will also delete the calendar event.
:::

## Cancellation

To cancel a scheduled announcement, use any of these methods:

| Method | How |
|--------|-----|
| Delete the original message | Delete your request message in Discord |
| Remove 👍 | Admin removes the approval reaction |
| Use a command | Run `/cancel` or `!cancel <job_id>` |

![The bot's confirmation reply for cancel](/images/cancel-command.png)

::: info
If a calendar event was created, it is automatically deleted when the announcement is cancelled.
:::

## Learn more

- [Reactions Reference](./reactions) — what each reaction does
- [Commands](./commands) — available slash and prefix commands
- [FAQ](./faq) — troubleshooting common issues
