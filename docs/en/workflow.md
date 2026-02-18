# Announcement Workflow

This page explains the full flow from submitting a request to the announcement being posted in VRChat.

## Overview

```
User submits request
    ↓
Bot adds 👀 and confirms receipt
    ↓
Admin adds 👍 to approve
    ↓
AI parses date/time/title/content
    ↓
Booking confirmation embed appears
    ↓
(Optional) Add 📅 to create VRChat calendar event
    ↓
At the scheduled time → Bot posts to VRChat group
```

## Step-by-step details

### Step 1: Submit

Mention the bot in the announcement channel and describe your announcement in plain text.

- Include **when to post the announcement** and the **event details** (title, start/end time, description)
- Japanese or English text both work
- No special syntax or formatting required

### Step 2: Receipt confirmation

When the bot receives your message, it:

1. Adds 👀 to your original message
2. Replies with a confirmation message

### Step 3: Admin approval

An admin adds 👍 to your original message to approve the request.

> **Note:** Only members with the admin role can approve requests.

### Step 4: AI parsing and scheduling

Once 👍 is added, the bot uses AI to automatically extract:

- The date and time to post the announcement
- The event start and end date/time
- The title
- The announcement content

A booking confirmation embed is posted when scheduling is complete. Review it to make sure everything looks correct.

### Step 5: (Optional) Calendar registration

React with 📅 on the booking confirmation embed to create an event in the VRChat group calendar.

- Only the original requester or an admin can do this
- The request must include event start and end times for this to work

### Step 6: Automatic posting

At the scheduled time, the bot automatically posts the announcement to the VRChat group.

## How to cancel

| Method | How |
|--------|-----|
| Delete the original message | Delete your request message in Discord |
| Admin removes 👍 | Admin removes the approval reaction |
| Use a command | Admin runs `!cancel <job_id>` |

On cancellation, the bot replies with a cancellation message. If a calendar event was created, it is also deleted automatically.

## Immediate posting

To post the announcement right now instead of waiting for the scheduled time, react with ⏩ on the booking confirmation embed.

- Only the original requester or an admin can do this
- The bot will confirm once the announcement has been posted
