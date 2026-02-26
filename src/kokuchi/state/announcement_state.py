import logging

logger = logging.getLogger(__name__)


class AnnouncementState:
    """Encapsulates all announcement tracking state with clear transitions.

    Design principle: entries are never deleted from pending_requests or
    calendar_events.  Instead their values are set to ``None`` (or left
    as-is) so that restart recovery can always see the full history of
    known message IDs.  The ``history`` list and job statuses in the
    Scheduler are the canonical records of completion.
    """

    def __init__(self, max_history=1000):
        self.pending_requests: dict[str, str | None] = {}   # msg_id -> bot_reply_id
        self.queued_announcements: set[str] = set()
        self.history: list[str] = []
        self.calendar_events: dict[str, str | None] = {}    # msg_id -> calendar_event_id or None
        self._max_history = max_history

    # --- Queries ---

    def is_pending(self, msg_id: str) -> bool:
        return msg_id in self.pending_requests

    def is_queued(self, msg_id: str) -> bool:
        return msg_id in self.queued_announcements

    def is_in_history(self, msg_id: str) -> bool:
        return msg_id in self.history

    def has_calendar_event(self, msg_id: str) -> bool:
        """Return True only if a calendar event ID is actively set (not None)."""
        return self.calendar_events.get(msg_id) is not None

    def get_calendar_event_id(self, msg_id: str) -> str | None:
        return self.calendar_events.get(msg_id)

    def get_bot_reply_id(self, msg_id: str) -> str | None:
        return self.pending_requests.get(msg_id)

    def find_request_id_by_bot_message(self, bot_msg_id: str) -> str | None:
        """Reverse lookup: given a bot reply message ID, find the original request msg_id.

        Only matches entries that have a non-None bot_reply_id.
        """
        for req_id, reply_id in self.pending_requests.items():
            if reply_id is not None and reply_id == bot_msg_id:
                return req_id
        return None

    # --- Transitions ---

    def add_pending(self, msg_id: str) -> None:
        self.pending_requests[msg_id] = None
        logger.info(f"State: added pending msg {msg_id}")

    def mark_queued(self, msg_id: str, bot_reply_id: str) -> None:
        self.pending_requests[msg_id] = bot_reply_id
        self.queued_announcements.add(msg_id)
        logger.info(f"State: marked queued msg={msg_id} -> bot_reply={bot_reply_id}")

    def mark_completed(self, msg_id: str) -> None:
        """Mark a request as completed.

        The entry in pending_requests is kept (not removed) so that the
        bot_reply_id mapping survives restarts.  The history list is the
        canonical record of completion.
        """
        if msg_id not in self.history:
            self.history.append(msg_id)
            if len(self.history) > self._max_history:
                self.history = self.history[-self._max_history:]
        self.queued_announcements.discard(msg_id)
        logger.info(f"State: marked completed msg={msg_id}")
        # Note: pending_requests entry is intentionally kept

    def cancel(self, msg_id: str) -> str | None:
        """Cancel a queued announcement.

        Returns calendar_event_id if one existed (caller should delete it).
        The pending_requests entry is set to None (bot reply is typically
        deleted on cancel).  The calendar_events entry is set to None
        rather than removed.
        """
        self.queued_announcements.discard(msg_id)
        self.pending_requests[msg_id] = None
        calendar_event_id = self.calendar_events.get(msg_id)
        if calendar_event_id is not None:
            self.calendar_events[msg_id] = None
        logger.info(f"State: cancelled msg={msg_id}, had_calendar={calendar_event_id is not None}")
        return calendar_event_id

    def set_calendar_event(self, msg_id: str, event_id: str) -> None:
        self.calendar_events[msg_id] = event_id
        logger.info(f"State: calendar event set msg={msg_id} -> event={event_id}")

    def remove_calendar_event(self, msg_id: str) -> str | None:
        """Clear the calendar event for a request. Returns the old event_id or None."""
        event_id = self.calendar_events.get(msg_id)
        if event_id is not None:
            self.calendar_events[msg_id] = None
        logger.info(f"State: calendar event removed msg={msg_id}, was={event_id}")
        return event_id

    # --- Persistence ---

    async def save(self, persistence) -> None:
        await persistence.save_data('pending', self.pending_requests)
        await persistence.save_data('history', self.history)
        await persistence.save_data('calendar', self.calendar_events)

    async def load(self, persistence) -> None:
        self.pending_requests = await persistence.load_data('pending', {})
        self.history = await persistence.load_data('history', [])
        self.calendar_events = await persistence.load_data('calendar', {})
