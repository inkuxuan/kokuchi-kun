import pytest
from unittest.mock import AsyncMock
from kokuchi.state.announcement_state import AnnouncementState


@pytest.fixture
def state():
    return AnnouncementState(max_history=5)


@pytest.fixture
def mock_persistence():
    persistence = AsyncMock()
    persistence.save_data = AsyncMock()
    persistence.load_data = AsyncMock()
    return persistence


class TestAnnouncementState:
    def test_add_pending(self, state):
        state.add_pending("msg1")
        assert state.is_pending("msg1")
        assert state.get_bot_reply_id("msg1") is None

    def test_mark_queued(self, state):
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        assert state.is_queued("msg1")
        assert state.get_bot_reply_id("msg1") == "reply1"

    def test_mark_completed_keeps_pending_entry(self, state):
        """mark_completed should keep the pending_requests entry (not pop it)."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.mark_completed("msg1")
        assert state.is_in_history("msg1")
        assert not state.is_queued("msg1")
        # Entry is kept in pending_requests (not removed)
        assert state.is_pending("msg1")
        assert state.get_bot_reply_id("msg1") == "reply1"

    def test_history_limit(self, state):
        for i in range(10):
            state.mark_completed(f"msg{i}")
        assert len(state.history) == 5
        assert state.history[0] == "msg5"
        assert state.history[-1] == "msg9"

    def test_cancel(self, state):
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.set_calendar_event("msg1", "cal1")

        calendar_id = state.cancel("msg1")

        assert calendar_id == "cal1"
        assert not state.is_queued("msg1")
        assert state.is_pending("msg1")
        assert state.get_bot_reply_id("msg1") is None
        # Calendar entry is set to None, not removed
        assert not state.has_calendar_event("msg1")
        assert "msg1" in state.calendar_events
        assert state.calendar_events["msg1"] is None

    def test_cancel_without_calendar(self, state):
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")

        calendar_id = state.cancel("msg1")

        assert calendar_id is None
        assert not state.is_queued("msg1")

    def test_find_request_id_by_bot_message(self, state):
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.add_pending("msg2")
        state.mark_queued("msg2", "reply2")

        assert state.find_request_id_by_bot_message("reply1") == "msg1"
        assert state.find_request_id_by_bot_message("reply2") == "msg2"
        assert state.find_request_id_by_bot_message("unknown") is None

    def test_find_request_id_skips_none_values(self, state):
        """find_request_id_by_bot_message should not match entries with None value."""
        state.add_pending("msg1")  # pending_requests["msg1"] = None
        assert state.find_request_id_by_bot_message("msg1") is None

    def test_find_request_id_skips_cancelled(self, state):
        """After cancel, the entry has None value and should not be found by reverse lookup."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.cancel("msg1")  # Sets value to None
        assert state.find_request_id_by_bot_message("reply1") is None

    def test_calendar_events(self, state):
        state.set_calendar_event("msg1", "cal1")
        assert state.has_calendar_event("msg1")
        assert state.get_calendar_event_id("msg1") == "cal1"

        removed = state.remove_calendar_event("msg1")
        assert removed == "cal1"
        assert not state.has_calendar_event("msg1")
        # Entry still exists but is None
        assert "msg1" in state.calendar_events
        assert state.calendar_events["msg1"] is None

    def test_remove_nonexistent_calendar_event(self, state):
        assert state.remove_calendar_event("msg1") is None

    def test_has_calendar_event_false_for_none(self, state):
        """has_calendar_event should return False when value is None."""
        state.calendar_events["msg1"] = None
        assert not state.has_calendar_event("msg1")

    @pytest.mark.asyncio
    async def test_save(self, state, mock_persistence):
        state.add_pending("msg1")
        state.history.append("msg0")
        state.set_calendar_event("msg2", "cal2")

        await state.save(mock_persistence)

        assert mock_persistence.save_data.call_count == 3
        calls = mock_persistence.save_data.call_args_list
        assert calls[0].args == ('pending', state.pending_requests)
        assert calls[1].args == ('history', state.history)
        assert calls[2].args == ('calendar', state.calendar_events)

    @pytest.mark.asyncio
    async def test_load(self, state, mock_persistence):
        mock_persistence.load_data.side_effect = [
            {'msg1': 'reply1'},
            ['msg0'],
            {'msg2': 'cal2'},
        ]

        await state.load(mock_persistence)

        assert state.pending_requests == {'msg1': 'reply1'}
        assert state.history == ['msg0']
        assert state.calendar_events == {'msg2': 'cal2'}

    @pytest.mark.asyncio
    async def test_load_with_none_calendar_values(self, state, mock_persistence):
        """Loading calendar_events with None values should work correctly."""
        mock_persistence.load_data.side_effect = [
            {},
            [],
            {'msg1': None, 'msg2': 'cal2'},
        ]

        await state.load(mock_persistence)

        assert not state.has_calendar_event("msg1")
        assert state.has_calendar_event("msg2")
