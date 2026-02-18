# Getting Started

VSPC Bot automates scheduling VRChat group announcements from Discord. Send a message in the designated channel, and the bot will post your announcement to the VRChat group at the specified time.

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

Include the bot's mention (`@VSPC Bot` or similar) and describe your announcement in plain text.

**Example:**
```
@VSPC Bot
[Event Announcement]
"Beginner-Friendly VRChat Tea Party" on May 10 at 8:00 PM.
Please post this announcement on May 8 at noon.
Location: World "Cozy Cafe"
```

No special formatting is needed. Just make sure the date/time for posting and the event details are clear.

### 3. Watch for the bot's response

The bot will react with 👀 (eyes) to acknowledge your request and reply with a confirmation message. Your request is now waiting for admin approval.

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
