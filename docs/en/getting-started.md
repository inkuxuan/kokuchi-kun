# Getting Started

kokuchi-kun is a Discord bot that automates scheduling VRChat group announcements. Send a message in the designated channel, and the bot will post your announcement to the VRChat group at the specified time.

> **Note:** For now, all dates and times are assumed to be in **JST (Japan Standard Time, UTC+9)**. Make sure to specify times in JST.

## What the bot does

- Accept announcement requests via Discord mentions
- Use AI to automatically parse dates, times, titles, and content from natural language
- Queue announcements for admin approval before scheduling
- Post to your VRChat group at the scheduled time
- Optionally create VRChat group calendar events

## How to submit a request

### 1. Go to the announcement channel

Navigate to the dedicated announcement channel that the bot monitors. Ask your server admin if you are unsure which channel to use.

### 2. Mention the bot with your announcement details

Include the bot's mention (e.g. `@kokuchi-kun`) and describe your announcement in plain text.

**Example:**
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

At minimum, include:
- Announcement title (used for the post)
- Post time in JST (used for the post)
- Event start time in JST (used for the calendar)
- Event end time in JST (used for the calendar)
- Event name (used for the calendar)

### 3. Watch for the bot's response

The bot will react with 👀 (eyes) to acknowledge your request and reply: "Announcement request received. Waiting for admin approval."

### 4. Wait for admin approval

An admin will review your request and add a 👍 reaction to approve it. Once approved, a booking confirmation embed will appear.

### 5. Booking confirmed

The confirmation embed shows:

- **Post time** — when the announcement will be posted to VRChat
- **Title** — extracted by AI
- **Content** — the announcement text
- **Job ID** — used to cancel if needed

## Next steps

- [Announcement Workflow](./workflow) — detailed step-by-step flow
- [Reactions Reference](./reactions) — what each reaction does
- [Commands](./commands) — available commands
