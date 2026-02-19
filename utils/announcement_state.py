import logging

logger = logging.getLogger(__name__)


class AnnouncementState:
    """Encapsulates all announcement tracking state with clear transitions."""

    def __init__(self, max_history=1000):
        self.pending_requests: dict[str, str | None] = {}   # msg_id -> bot_reply_id
        self.queued_announcements: set[str] = set()
        self.history: list[str] = []
        self.calendar_events: dict[str, str] = {}           # msg_id -> calendar_event_id
        self._max_history = max_history

    # --- Queries ---

    def is_pending(self, msg_id: str) -> bool:
        return msg_id in self.pending_requests

    def is_queued(self, msg_id: str) -> bool:
        return msg_id in self.queued_announcements

    def is_in_history(self, msg_id: str) -> bool:
        return msg_id in self.history

    def has_calendar_event(self, msg_id: str) -> bool:
        return msg_id in self.calendar_events

    def get_calendar_event_id(self, msg_id: str) -> str | None:
        return self.calendar_events.get(msg_id)

    def get_bot_reply_id(self, msg_id: str) -> str | None:
        return self.pending_requests.get(msg_id)

    def find_request_id_by_bot_message(self, bot_msg_id: str) -> str | None:
        """Reverse lookup: given a bot reply message ID, find the original request msg_id."""
        for req_id, reply_id in self.pending_requests.items():
            if reply_id == bot_msg_id:
                return req_id
        return None

    # --- Transitions ---

    def add_pending(self, msg_id: str) -> None:
        self.pending_requests[msg_id] = None

    def mark_queued(self, msg_id: str, bot_reply_id: str) -> None:
        self.pending_requests[msg_id] = bot_reply_id
        self.queued_announcements.add(msg_id)

    def mark_completed(self, msg_id: str) -> None:
        if msg_id not in self.history:
            self.history.append(msg_id)
            if len(self.history) > self._max_history:
                self.history = self.history[-self._max_history:]
        self.queued_announcements.discard(msg_id)
        self.pending_requests.pop(msg_id, None)

    def cancel(self, msg_id: str) -> str | None:
        """Cancel a queued announcement. Returns calendar_event_id if one existed."""
        self.queued_announcements.discard(msg_id)
        self.pending_requests[msg_id] = None
        return self.calendar_events.pop(msg_id, None)

    def set_calendar_event(self, msg_id: str, event_id: str) -> None:
        self.calendar_events[msg_id] = event_id

    def remove_calendar_event(self, msg_id: str) -> str | None:
        return self.calendar_events.pop(msg_id, None)

    # --- Persistence ---

    async def save(self, persistence) -> None:
        await persistence.save_data('pending', self.pending_requests)
        await persistence.save_data('history', self.history)
        await persistence.save_data('calendar', self.calendar_events)

    async def load(self, persistence) -> None:
        self.pending_requests = await persistence.load_data('pending', {})
        self.history = await persistence.load_data('history', [])
        self.calendar_events = await persistence.load_data('calendar', {})
