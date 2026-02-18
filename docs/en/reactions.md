# Reactions Reference

The bot uses emoji reactions to drive its approval and scheduling workflow.

## Quick reference

| Reaction | Name | Added by | Effect |
|----------|------|----------|--------|
| 👀 | Seen | Bot (automatic) | Acknowledges the request has been received |
| 👍 | Approve | Admin | Approves the announcement and triggers AI processing |
| ⏩ | Post now | Requester or admin | Immediately posts the announcement to VRChat |
| 📅 | Calendar | Requester or admin | Creates a VRChat group calendar event |

## Details

### 👀 Seen

- **Added by:** Bot (automatically)
- **On message:** The user's request message
- **Meaning:** The bot has received the announcement request and is waiting for admin approval. No action is needed from you at this point.

### 👍 Approve

- **Added by:** Members with the admin role
- **On message:** The user's request message
- **Meaning:** Approves the announcement. The bot starts AI processing to extract the date, time, title, and content, then schedules the post.
- **Removing it:** If the admin removes the 👍, the scheduled announcement is cancelled.

### ⏩ Post now

- **Added by:** The original requester or members with the admin role
- **On message:** The booking confirmation embed
- **Meaning:** Skips the scheduled time and posts the announcement to VRChat immediately. Useful for urgent announcements or when no scheduling delay is needed.

### 📅 Calendar

- **Added by:** The original requester or members with the admin role
- **On message:** The booking confirmation embed
- **Meaning:** Creates an event in the VRChat group calendar for this announcement. Requires event start and end times to be included in the original request.
- **Removing it:** If the 📅 is removed, the calendar event is also deleted.
