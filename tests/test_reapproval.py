"""Tests for cancelled-then-reapproved announcement lifecycle.

When an announcement is cancelled and then re-approved, the system must:
1. Clean up the stale cancelled job
2. Create a new job that behaves identically to a fresh job
3. Support all normal operations: cancel, fast-forward, calendar creation
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock
from kokuchi.services.scheduler import Scheduler, TERMINAL_STATUSES
from kokuchi.state.announcement_state import AnnouncementState
import time


@pytest.fixture
def mock_vrchat_api():
    api = AsyncMock()
    api.post_announcement = AsyncMock(return_value=AsyncMock(success=True))
    api.delete_group_calendar_event = AsyncMock(return_value=AsyncMock(success=True))
    api.create_group_calendar_event = AsyncMock(return_value=AsyncMock(
        success=True, data={'event_id': 'cal_new'}
    ))
    return api


@pytest_asyncio.fixture
async def scheduler(mock_vrchat_api):
    sched = Scheduler(mock_vrchat_api)
    yield sched
    sched.shutdown()


@pytest.fixture
def state():
    return AnnouncementState()


# --- Scheduler: stale job cleanup ---

class TestSchedulerReapproval:
    @pytest.mark.asyncio
    async def test_reapproval_removes_cancelled_job(self, scheduler):
        """Scheduling for a message_id that has a cancelled job should remove the old job."""
        ts = int(time.time()) + 3600

        # First approval
        job_id1 = await scheduler.schedule_announcement(
            ts, "Title v1", "Content v1", "msg_1", "guild_1", group_id="grp_1"
        )
        assert job_id1 in scheduler.jobs

        # Cancel
        scheduler.cancel_job(job_id1)
        assert scheduler.jobs[job_id1].status == 'cancelled'

        # Re-approve (same message_id)
        job_id2 = await scheduler.schedule_announcement(
            ts + 60, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        # New job should exist with updated content
        assert job_id2 in scheduler.jobs
        assert scheduler.jobs[job_id2].status == 'pending'
        assert scheduler.jobs[job_id2].title == "Title v2"

    @pytest.mark.asyncio
    async def test_reapproval_removes_failed_job(self, scheduler):
        """Scheduling for a message_id that has a failed job should remove the old job."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.mark_job_failed(job_id1)
        assert scheduler.jobs[job_id1].status == 'failed'

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        assert job_id2 in scheduler.jobs
        assert scheduler.jobs[job_id2].status == 'pending'

    @pytest.mark.asyncio
    async def test_reapproval_removes_success_job(self, scheduler):
        """Scheduling for a message_id that has a success job should remove the old job."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.mark_job_success(job_id1)

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        assert job_id2 in scheduler.jobs

    @pytest.mark.asyncio
    async def test_reapproval_does_not_remove_other_messages(self, scheduler):
        """Cleanup should only remove jobs for the same message_id."""
        ts = int(time.time()) + 3600

        job_other = await scheduler.schedule_announcement(
            ts, "Other", "Content", "msg_other", "guild_1", group_id="grp_1"
        )
        job_cancelled = await scheduler.schedule_announcement(
            ts, "Cancelled", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_cancelled)

        # Re-approve msg_1
        job_new = await scheduler.schedule_announcement(
            ts, "New", "Content", "msg_1", "guild_1", group_id="grp_1"
        )

        # msg_other's job should be untouched
        assert job_other in scheduler.jobs
        assert scheduler.jobs[job_other].status == 'pending'
        # msg_1's job replaced with new pending entry
        assert job_new in scheduler.jobs
        assert scheduler.jobs[job_new].title == "New"
        assert scheduler.jobs[job_new].status == 'pending'

    @pytest.mark.asyncio
    async def test_reapproval_replaces_cancelled_job(self, scheduler):
        """Rescheduling always replaces the existing job for the same msg_id."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "v1", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_id1)

        job_id3 = await scheduler.schedule_announcement(
            ts, "v3", "Content", "msg_1", "guild_1", group_id="grp_1"
        )

        assert job_id3 in scheduler.jobs
        assert scheduler.jobs[job_id3].title == "v3"
        assert scheduler.jobs[job_id3].status == "pending"


# --- Scheduler: reapproved job behaves normally ---

class TestReapprovedJobOperations:
    @pytest.mark.asyncio
    async def test_reapproved_job_can_be_found_by_message_id(self, scheduler):
        """get_job_by_message_id should find the reapproved job."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_id1)

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        found = scheduler.get_job_by_message_id("msg_1")
        assert found is not None
        assert found.id == job_id2
        assert found.status == 'pending'

    @pytest.mark.asyncio
    async def test_reapproved_job_can_be_cancelled(self, scheduler):
        """A reapproved job should be cancellable."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_id1)

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        result = scheduler.cancel_job_by_message_id("msg_1")
        assert result is True
        assert scheduler.jobs[job_id2].status == 'cancelled'

    @pytest.mark.asyncio
    async def test_reapproved_job_can_be_marked_success(self, scheduler):
        """A reapproved job should support mark_job_success (fast-forward)."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_id1)

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        scheduler.mark_job_success(job_id2)
        assert scheduler.jobs[job_id2].status == 'success'
        assert scheduler.scheduler.get_job(job_id2) is None

    @pytest.mark.asyncio
    async def test_reapproved_job_appears_in_list_jobs(self, scheduler):
        """A reapproved pending job should appear in list_jobs."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_id1)

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        active = scheduler.list_jobs()
        assert len(active) == 1
        assert active[0].id == job_id2

    @pytest.mark.asyncio
    async def test_reapproved_job_persists_correctly(self, scheduler):
        """get_jobs_data should only include the new job, not the old cancelled one."""
        ts = int(time.time()) + 3600

        job_id1 = await scheduler.schedule_announcement(
            ts, "Title", "Content", "msg_1", "guild_1", group_id="grp_1"
        )
        scheduler.cancel_job(job_id1)

        job_id2 = await scheduler.schedule_announcement(
            ts, "Title v2", "Content v2", "msg_1", "guild_1", group_id="grp_1"
        )

        data = scheduler.get_jobs_data()
        msg1_jobs = [j for j in data if j['message_id'] == 'msg_1']
        assert len(msg1_jobs) == 1
        assert msg1_jobs[0]['id'] == job_id2
        assert msg1_jobs[0]['status'] == 'pending'


# --- AnnouncementState: cancel-reapprove cycle ---

class TestStateCancelReapprove:
    def test_cancel_then_requeue(self, state):
        """After cancel, the same msg_id can be re-queued with a new bot reply."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.cancel("msg1")

        # After cancel: bot_reply_id is None, not queued
        assert state.get_bot_reply_id("msg1") is None
        assert not state.is_queued("msg1")
        assert state.find_request_id_by_bot_message("reply1") is None

        # Re-queue with a new bot reply
        state.mark_queued("msg1", "reply2")

        assert state.is_queued("msg1")
        assert state.get_bot_reply_id("msg1") == "reply2"
        assert state.find_request_id_by_bot_message("reply2") == "msg1"
        # Old reply no longer resolves
        assert state.find_request_id_by_bot_message("reply1") is None

    def test_cancel_requeue_calendar(self, state):
        """After cancel clears calendar, a new calendar event can be set."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.set_calendar_event("msg1", "cal1")
        state.cancel("msg1")

        assert not state.has_calendar_event("msg1")

        # Re-queue and set new calendar
        state.mark_queued("msg1", "reply2")
        state.set_calendar_event("msg1", "cal2")

        assert state.has_calendar_event("msg1")
        assert state.get_calendar_event_id("msg1") == "cal2"

    def test_cancel_requeue_not_in_history(self, state):
        """A cancelled-then-requeued msg should not be in history."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.cancel("msg1")
        state.mark_queued("msg1", "reply2")

        assert not state.is_in_history("msg1")
        assert state.is_queued("msg1")

    def test_requeued_then_completed(self, state):
        """A requeued msg can be completed normally."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.cancel("msg1")
        state.mark_queued("msg1", "reply2")
        state.mark_completed("msg1")

        assert state.is_in_history("msg1")
        assert not state.is_queued("msg1")
        # Bot reply mapping is kept for restart recovery
        assert state.get_bot_reply_id("msg1") == "reply2"

    def test_requeued_then_cancelled_again(self, state):
        """A requeued msg can be cancelled again."""
        state.add_pending("msg1")
        state.mark_queued("msg1", "reply1")
        state.cancel("msg1")
        state.mark_queued("msg1", "reply2")
        state.set_calendar_event("msg1", "cal2")

        cal_id = state.cancel("msg1")

        assert cal_id == "cal2"
        assert not state.is_queued("msg1")
        assert state.get_bot_reply_id("msg1") is None
        assert not state.has_calendar_event("msg1")
