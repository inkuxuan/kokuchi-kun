# FAQ

## Nothing happened after I sent my request

**Q: I mentioned the bot with my announcement, but I got no response**

Check the following:

- You are in the correct channel (the one the bot monitors)
- Your message includes the bot's mention (`@Kokuchi Kun` or similar)
- The bot is currently online (use `!ping` to check)

---

## Got 👀 but no booking confirmation

**Q: The bot reacted with 👀 but nothing else happened**

The 👀 means the bot received your request. The next step requires **admin approval via 👍**. Your request is waiting for an admin to review it. Contact a server admin if it has been a while.

---

## I made a mistake in my request

**Q: I submitted the wrong date, time, or content**

If the announcement has **not yet been approved** (no 👍): simply edit your original message before an admin approves it.

If it has **already been approved and scheduled**:

1. Ask an admin to remove the 👍 (or run `/cancel <job_id>`) to cancel the booking
2. Edit your original message in Discord to fix the mistake
3. Have an admin add 👍 again to re-approve

The bot will re-process the edited message and create a fresh booking. You don't need to delete and resubmit — just cancel, edit, and re-approve. See [Editing and Re-approving](./features#editing-and-re-approving) for details.

---

## Can I write in English?

**Q: Does the bot understand English requests?**

Yes. The bot's AI parser understands both Japanese and English. Write your announcement in whichever language is most natural for you.

---

## The bot was offline when the scheduled time arrived

**Q: My announcement was scheduled but the bot was down — was it posted?**

No. If the bot was offline at the scheduled time, the announcement is skipped. When the bot restarts, it will report which announcements were missed with a warning message in the channel. Please resubmit those announcements.

---

## Calendar event creation failed

**Q: I added 📅 but got an error about missing event times**

The calendar event feature requires both a **start time and end time** to be present in your original request. Resubmit with both times clearly stated, get it approved again, and then add 📅.
