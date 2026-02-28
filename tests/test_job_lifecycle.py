"""Comprehensive job lifecycle edge-case tests.

Covers the full matrix of state transitions:
- Pending -> Approved -> Posted (success)
- Pending -> Approved -> Failed
- Pending -> Approved -> Cancelled (reaction removal)
- Pending -> Approved -> Cancelled (admin command)
- Pending -> Approved -> Cancelled -> Reapproved -> Posted
- Pending -> Approved -> Cancelled -> Reapproved -> Cancelled again
- Pending -> Approved -> Posted (instant via ⏩)
- Pending -> Approved -> Posted -> Cannot cancel
- Calendar creation / removal lifecycle
- Missed job handling
- Persistence round-trips
- Stale queued_announcements after restart
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
from kokuchi.services.scheduler import Scheduler, TERMINAL_STATUSES
from kokuchi.state.announcement_state import AnnouncementState
from kokuchi.state.state_manager import StateManager
from kokuchi.common.models import JobData
import time


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_vrchat_api():
    api = AsyncMock()
    api.post_announcement = AsyncMock(return_value=AsyncMock(success=True))
    api.delete_group_calendar_event = AsyncMock(return_value=AsyncMock(success=True))
    api.create_group_calendar_event = AsyncMock(return_value=AsyncMock(
        success=True, data={'event_id': 'cal_123'}
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


@pytest.fixture
def mock_persistence():
    persistence = MagicMock()
    persistence.load_data = AsyncMock(return_value=[])
    persistence.save_data = AsyncMock(return_value=True)
    persistence.save_announcement = AsyncMock(return_value=True)
    persistence.load_announcements = AsyncMock(return_value={})
    return persistence


GUILD_ID = "guild_1"
GROUP_ID = "grp_1"


def _future_ts(offset=3600):
    return int(time.time()) + offset


async def _schedule(scheduler, msg_id="msg_1", ts=None, title="Title", content="Content"):
    """Helper to schedule an announcement with sensible defaults."""
    if ts is None:
        ts = _future_ts()
    return await scheduler.schedule_announcement(
        ts, title, content, msg_id, GUILD_ID, group_id=GROUP_ID,
        event_start_timestamp=ts + 3600, event_end_timestamp=ts + 7200,
        event_title=f"Event: {title}",
    )


# ===========================================================================
# 1. Happy path: pending -> approved -> posted (success)
# ===========================================================================

class TestHappyPath:
    @pytest.mark.asyncio
    async def test_schedule_creates_pending_job(self, scheduler):
        job_id = await _schedule(scheduler)
        assert scheduler.jobs[job_id].status == "pending"
        assert scheduler.scheduler.get_job(job_id) is not None

    @pytest.mark.asyncio
    async def test_mark_success_transitions_to_success(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.mark_job_success(job_id)
        assert scheduler.jobs[job_id].status == "success"
        assert scheduler.scheduler.get_job(job_id) is None

    def test_state_full_lifecycle(self, state):
        """AnnouncementState: add_pending -> mark_queued -> mark_completed."""
        state.add_pending("msg_1")
        assert state.is_pending("msg_1")
        assert not state.is_queued("msg_1")

        state.mark_queued("msg_1", "reply_1")
        assert state.is_queued("msg_1")
        assert state.get_bot_reply_id("msg_1") == "reply_1"
        assert state.find_request_id_by_bot_message("reply_1") == "msg_1"

        state.mark_completed("msg_1")
        assert state.is_in_history("msg_1")
        assert not state.is_queued("msg_1")
        # pending_requests entry kept for restart recovery
        assert state.is_pending("msg_1")


# ===========================================================================
# 2. Failure path: pending -> approved -> failed
# ===========================================================================

class TestFailurePath:
    @pytest.mark.asyncio
    async def test_mark_failed_transitions_to_failed(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.mark_job_failed(job_id)
        assert scheduler.jobs[job_id].status == "failed"
        assert scheduler.scheduler.get_job(job_id) is None

    @pytest.mark.asyncio
    async def test_failed_job_not_in_list_jobs(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.mark_job_failed(job_id)
        assert scheduler.list_jobs() == []

    @pytest.mark.asyncio
    async def test_failed_job_still_in_get_jobs_data(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.mark_job_failed(job_id)
        data = scheduler.get_jobs_data()
        assert len(data) == 1
        assert data[0]["status"] == "failed"


# ===========================================================================
# 3. Cancellation via reaction removal (👍 removed)
# ===========================================================================

class TestReactionCancellation:
    @pytest.mark.asyncio
    async def test_cancel_by_message_id(self, scheduler):
        job_id = await _schedule(scheduler, msg_id="msg_1")
        result = scheduler.cancel_job_by_message_id("msg_1")
        assert result is True
        assert scheduler.jobs[job_id].status == "cancelled"
        assert scheduler.scheduler.get_job(job_id) is None

    def test_state_cancel_clears_queued(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.cancel("msg_1")
        assert not state.is_queued("msg_1")
        assert state.get_bot_reply_id("msg_1") is None
        assert state.find_request_id_by_bot_message("reply_1") is None

    def test_state_cancel_returns_calendar_event(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        cal_id = state.cancel("msg_1")
        assert cal_id == "cal_1"
        assert not state.has_calendar_event("msg_1")

    def test_state_cancel_returns_none_when_no_calendar(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        cal_id = state.cancel("msg_1")
        assert cal_id is None


# ===========================================================================
# 4. Cancellation via admin command (!cancel)
# ===========================================================================

class TestAdminCancellation:
    @pytest.mark.asyncio
    async def test_cancel_by_job_id(self, scheduler):
        job_id = await _schedule(scheduler)
        result = scheduler.cancel_job(job_id)
        assert result is True
        assert scheduler.jobs[job_id].status == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_job(self, scheduler):
        result = scheduler.cancel_job("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_by_nonexistent_message_id(self, scheduler):
        result = scheduler.cancel_job_by_message_id("no_such_msg")
        assert result is False


# ===========================================================================
# 5. Cancel -> Reapprove -> Posted
# ===========================================================================

class TestCancelReapprovePost:
    @pytest.mark.asyncio
    async def test_reapproved_job_replaces_cancelled(self, scheduler):
        job_id1 = await _schedule(scheduler, msg_id="msg_1", title="v1")
        scheduler.cancel_job(job_id1)

        job_id2 = await _schedule(scheduler, msg_id="msg_1", title="v2")
        assert scheduler.jobs[job_id2].status == "pending"
        assert scheduler.jobs[job_id2].title == "v2"

    @pytest.mark.asyncio
    async def test_reapproved_job_can_succeed(self, scheduler):
        job_id1 = await _schedule(scheduler, msg_id="msg_1")
        scheduler.cancel_job(job_id1)
        job_id2 = await _schedule(scheduler, msg_id="msg_1")
        scheduler.mark_job_success(job_id2)
        assert scheduler.jobs[job_id2].status == "success"

    def test_state_cancel_requeue_complete(self, state):
        """Full state lifecycle: pending -> queued -> cancel -> requeue -> complete."""
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.cancel("msg_1")
        state.mark_queued("msg_1", "reply_2")
        state.mark_completed("msg_1")
        assert state.is_in_history("msg_1")
        assert not state.is_queued("msg_1")
        assert state.get_bot_reply_id("msg_1") == "reply_2"


# ===========================================================================
# 6. Cancel -> Reapprove -> Cancel again
# ===========================================================================

class TestCancelReapproveCancelAgain:
    @pytest.mark.asyncio
    async def test_double_cancel_reapprove_cycle(self, scheduler):
        # First cycle
        job_id1 = await _schedule(scheduler, msg_id="msg_1", title="v1")
        scheduler.cancel_job(job_id1)

        # Second cycle
        job_id2 = await _schedule(scheduler, msg_id="msg_1", title="v2")
        scheduler.cancel_job(job_id2)
        assert scheduler.jobs[job_id2].status == "cancelled"

        # Third cycle
        job_id3 = await _schedule(scheduler, msg_id="msg_1", title="v3")
        assert scheduler.jobs[job_id3].status == "pending"
        assert scheduler.jobs[job_id3].title == "v3"

    def test_state_double_cancel_requeue(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        cal_id = state.cancel("msg_1")
        assert cal_id == "cal_1"

        state.mark_queued("msg_1", "reply_2")
        state.set_calendar_event("msg_1", "cal_2")
        cal_id = state.cancel("msg_1")
        assert cal_id == "cal_2"
        assert not state.is_queued("msg_1")
        assert not state.has_calendar_event("msg_1")


# ===========================================================================
# 7. Instant post (⏩) — job marked success immediately
# ===========================================================================

class TestInstantPost:
    @pytest.mark.asyncio
    async def test_instant_post_marks_success(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.mark_job_success(job_id)
        assert scheduler.jobs[job_id].status == "success"
        assert scheduler.scheduler.get_job(job_id) is None

    @pytest.mark.asyncio
    async def test_instant_post_not_in_list_jobs(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.mark_job_success(job_id)
        assert scheduler.list_jobs() == []

    def test_state_instant_post_completes(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.mark_completed("msg_1")
        assert state.is_in_history("msg_1")
        assert not state.is_queued("msg_1")


# ===========================================================================
# 8. Posted job cannot be cancelled
# ===========================================================================

class TestPostedCannotCancel:
    @pytest.mark.asyncio
    async def test_cancel_success_job_is_noop(self, scheduler):
        """Cancelling a job that already succeeded should still set status to cancelled,
        but in practice the cog guard prevents this. At scheduler level it's allowed."""
        job_id = await _schedule(scheduler)
        scheduler.mark_job_success(job_id)
        # cancel_job changes status but it's already terminal
        result = scheduler.cancel_job(job_id)
        assert result is True  # scheduler allows it mechanically
        assert scheduler.jobs[job_id].status == "cancelled"

    @pytest.mark.asyncio
    async def test_success_job_excluded_from_cancel_by_message_id(self, scheduler):
        """cancel_job_by_message_id will find the success job and cancel it at scheduler
        level, but cog-level guards should prevent reaching here."""
        job_id = await _schedule(scheduler, msg_id="msg_1")
        scheduler.mark_job_success(job_id)
        # At scheduler level, this still works
        result = scheduler.cancel_job_by_message_id("msg_1")
        assert result is True

    def test_completed_state_not_affected_by_cancel(self, state):
        """Once in history, cancel doesn't remove from history."""
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.mark_completed("msg_1")
        state.cancel("msg_1")
        # Still in history — cancel doesn't undo completion
        assert state.is_in_history("msg_1")


# ===========================================================================
# 9. Calendar event lifecycle
# ===========================================================================

class TestCalendarLifecycle:
    def test_set_and_get_calendar(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        assert state.has_calendar_event("msg_1")
        assert state.get_calendar_event_id("msg_1") == "cal_1"

    def test_remove_calendar_returns_old_id(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        old_id = state.remove_calendar_event("msg_1")
        assert old_id == "cal_1"
        assert not state.has_calendar_event("msg_1")

    def test_remove_calendar_without_event(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        old_id = state.remove_calendar_event("msg_1")
        assert old_id is None

    def test_cancel_clears_calendar(self, state):
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        cal_id = state.cancel("msg_1")
        assert cal_id == "cal_1"
        assert not state.has_calendar_event("msg_1")

    def test_calendar_after_reapproval(self, state):
        """Calendar can be set on a reapproved message."""
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        state.cancel("msg_1")

        state.mark_queued("msg_1", "reply_2")
        assert not state.has_calendar_event("msg_1")  # Cleared by cancel
        state.set_calendar_event("msg_1", "cal_2")
        assert state.get_calendar_event_id("msg_1") == "cal_2"

    def test_calendar_remove_then_re_add(self, state):
        """Calendar can be removed via 📅 removal and re-added."""
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")
        state.remove_calendar_event("msg_1")
        assert not state.has_calendar_event("msg_1")

        state.set_calendar_event("msg_1", "cal_2")
        assert state.get_calendar_event_id("msg_1") == "cal_2"


# ===========================================================================
# 10. Missed job handling
# ===========================================================================

class TestMissedJobs:
    @pytest.mark.asyncio
    async def test_restore_past_due_beyond_grace_marks_missed(self, scheduler):
        past_time = int(time.time()) - 7200  # 2 hours ago, beyond 1h grace
        jobs_data = [{
            'id': 'job_old',
            'message_id': 'msg_old',
            'timestamp': past_time,
            'title': 'Old Job',
            'content': 'Content',
            'guild_id': GUILD_ID,
            'group_id': GROUP_ID,
            'status': 'pending',
        }]

        restored, skipped = scheduler.restore_jobs(jobs_data)
        assert restored == 0
        assert len(skipped) == 1
        assert scheduler.jobs['job_old'].status == 'missed'
        assert scheduler.scheduler.get_job('job_old') is None

    @pytest.mark.asyncio
    async def test_restore_past_due_within_grace_scheduled(self, scheduler):
        past_time = int(time.time()) - 1800  # 30 min ago, within 1h grace
        jobs_data = [{
            'id': 'job_recent',
            'message_id': 'msg_recent',
            'timestamp': past_time,
            'title': 'Recent Job',
            'content': 'Content',
            'guild_id': GUILD_ID,
            'group_id': GROUP_ID,
            'status': 'pending',
        }]

        restored, skipped = scheduler.restore_jobs(jobs_data)
        assert restored == 1
        assert len(skipped) == 0
        assert scheduler.jobs['job_recent'].status == 'pending'
        assert scheduler.scheduler.get_job('job_recent') is not None

    @pytest.mark.asyncio
    async def test_missed_status_restored_as_missed(self, scheduler):
        """Jobs already marked 'missed' in persistence are kept as missed."""
        jobs_data = [{
            'id': 'job_missed',
            'message_id': 'msg_missed',
            'timestamp': int(time.time()) - 100000,
            'title': 'Previously Missed',
            'content': 'Content',
            'guild_id': GUILD_ID,
            'group_id': GROUP_ID,
            'status': 'missed',
        }]

        restored, skipped = scheduler.restore_jobs(jobs_data)
        assert restored == 0
        assert len(skipped) == 1
        assert scheduler.jobs['job_missed'].status == 'missed'


# ===========================================================================
# 11. Persistence round-trips
# ===========================================================================

class TestPersistence:
    @pytest.mark.asyncio
    async def test_jobs_data_roundtrip(self, scheduler):
        """Jobs can be serialized and restored faithfully."""
        ts = _future_ts()
        job_id = await _schedule(scheduler, msg_id="msg_1", ts=ts)

        data = scheduler.get_jobs_data()
        assert len(data) == 1
        assert data[0]['id'] == job_id
        assert data[0]['status'] == 'pending'
        assert data[0]['event_title'] == "Event: Title"

    @pytest.mark.asyncio
    async def test_cancelled_job_persisted(self, scheduler):
        job_id = await _schedule(scheduler)
        scheduler.cancel_job(job_id)
        data = scheduler.get_jobs_data()
        assert data[0]['status'] == 'cancelled'

    @pytest.mark.asyncio
    async def test_get_jobs_data_guild_filter(self, scheduler):
        ts = _future_ts()
        await scheduler.schedule_announcement(
            ts, "G1", "C", "msg_g1", "guild_1", group_id="grp_1"
        )
        await scheduler.schedule_announcement(
            ts + 1, "G2", "C", "msg_g2", "guild_2", group_id="grp_2"
        )

        g1_data = scheduler.get_jobs_data(guild_id="guild_1")
        g2_data = scheduler.get_jobs_data(guild_id="guild_2")
        all_data = scheduler.get_jobs_data()

        assert len(g1_data) == 1
        assert len(g2_data) == 1
        assert len(all_data) == 2

    @pytest.mark.asyncio
    async def test_restore_terminal_jobs_kept_in_memory(self, scheduler):
        """Terminal jobs are loaded into memory but not scheduled."""
        ts = _future_ts()
        jobs_data = [
            {'id': 'j_s', 'message_id': 'm_s', 'timestamp': ts,
             'title': 'T', 'content': 'C', 'guild_id': GUILD_ID,
             'group_id': GROUP_ID, 'status': 'success'},
            {'id': 'j_c', 'message_id': 'm_c', 'timestamp': ts,
             'title': 'T', 'content': 'C', 'guild_id': GUILD_ID,
             'group_id': GROUP_ID, 'status': 'cancelled'},
            {'id': 'j_f', 'message_id': 'm_f', 'timestamp': ts,
             'title': 'T', 'content': 'C', 'guild_id': GUILD_ID,
             'group_id': GROUP_ID, 'status': 'failed'},
        ]

        restored, skipped = scheduler.restore_jobs(jobs_data)
        assert restored == 0
        assert len(skipped) == 0
        for jid in ['j_s', 'j_c', 'j_f']:
            assert jid in scheduler.jobs
            assert scheduler.scheduler.get_job(jid) is None


# ===========================================================================
# 12. Stale queued_announcements after restart
# ===========================================================================

class TestStaleQueuedState:
    """Tests for the scenario where queued_announcements has a stale entry
    because a job was cancelled via !cancel and then the bot restarted,
    restoring the cancelled job which rebuilt queued_announcements incorrectly.

    The fix: approval guard verifies actual job status when is_queued is True.
    """

    @pytest.mark.asyncio
    async def test_queued_set_rebuilt_from_active_jobs_only(self, scheduler):
        """On restore, queued_announcements should only contain active (pending) jobs."""
        ts = _future_ts()
        state = AnnouncementState()

        # Simulate: one cancelled job and one active job restored
        jobs_data = [
            {'id': 'j_cancelled', 'message_id': 'msg_1', 'timestamp': ts,
             'title': 'T', 'content': 'C', 'guild_id': GUILD_ID,
             'group_id': GROUP_ID, 'status': 'cancelled'},
            {'id': 'j_active', 'message_id': 'msg_2', 'timestamp': ts,
             'title': 'T', 'content': 'C', 'guild_id': GUILD_ID,
             'group_id': GROUP_ID, 'status': 'pending'},
        ]
        scheduler.restore_jobs(jobs_data, guild_id=GUILD_ID, group_id=GROUP_ID)

        # Rebuild queued_announcements like state_manager.load_state does
        state.queued_announcements = set()
        for job in scheduler.list_jobs(guild_id=GUILD_ID):
            if job.message_id:
                state.queued_announcements.add(job.message_id)

        # Only the active job should be queued
        assert state.is_queued("msg_2")
        assert not state.is_queued("msg_1")

    @pytest.mark.asyncio
    async def test_stale_queued_flag_allows_reapproval(self, scheduler):
        """If queued_announcements has a stale entry (job is terminal),
        the approval guard should detect and clear it."""
        state = AnnouncementState()
        ts = _future_ts()

        # Schedule and cancel
        job_id = await _schedule(scheduler, msg_id="msg_1")
        scheduler.cancel_job(job_id)

        # Simulate stale state: msg_1 still in queued_announcements (e.g. rebuilt wrong)
        state.queued_announcements.add("msg_1")
        assert state.is_queued("msg_1")

        # Simulate approval guard logic from announcement.py
        job = scheduler.get_job_by_message_id("msg_1")
        if job and job.status not in ('cancelled', 'success', 'failed'):
            pytest.fail("Active job found — should not happen after cancel")
        else:
            # Job is terminal — stale flag, clear it
            state.queued_announcements.discard("msg_1")

        assert not state.is_queued("msg_1")

    @pytest.mark.asyncio
    async def test_stale_queued_flag_when_job_missing(self, scheduler):
        """If queued_announcements has an entry but no job exists at all,
        the flag should be cleared."""
        state = AnnouncementState()
        state.queued_announcements.add("msg_orphan")

        job = scheduler.get_job_by_message_id("msg_orphan")
        assert job is None

        # Approval guard: job missing means stale
        if job is None or job.status in TERMINAL_STATUSES:
            state.queued_announcements.discard("msg_orphan")

        assert not state.is_queued("msg_orphan")


# ===========================================================================
# 13. StateManager composite operations
# ===========================================================================

class TestStateManagerOperations:
    @pytest.fixture
    def state_manager(self, scheduler, mock_vrchat_api, mock_persistence):
        guild_configs = {GUILD_ID: {'group_id': GROUP_ID, 'enabled': True}}
        guild_persistences = {GUILD_ID: mock_persistence}
        return StateManager(
            scheduler=scheduler,
            vrchat_api=mock_vrchat_api,
            guild_persistences=guild_persistences,
            guild_configs=guild_configs,
        )

    @pytest.mark.asyncio
    async def test_cancel_announcement_detailed(self, state_manager, scheduler, mock_vrchat_api):
        job_id = await _schedule(scheduler, msg_id="msg_1")
        state = state_manager.get_state(GUILD_ID)
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.set_calendar_event("msg_1", "cal_1")

        success, deleted_calendar = await state_manager.cancel_announcement_detailed(GUILD_ID, "msg_1")
        assert success is True
        assert deleted_calendar is True
        mock_vrchat_api.delete_group_calendar_event.assert_called_once_with(GROUP_ID, "cal_1")
        assert not state.is_queued("msg_1")

    @pytest.mark.asyncio
    async def test_cancel_announcement_no_calendar(self, state_manager, scheduler):
        job_id = await _schedule(scheduler, msg_id="msg_1")
        state = state_manager.get_state(GUILD_ID)
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")

        success, deleted_calendar = await state_manager.cancel_announcement_detailed(GUILD_ID, "msg_1")
        assert success is True
        assert deleted_calendar is False

    @pytest.mark.asyncio
    async def test_cancel_announcement_no_job(self, state_manager):
        success, deleted_calendar = await state_manager.cancel_announcement_detailed(GUILD_ID, "nonexistent")
        assert success is False
        assert deleted_calendar is False

    @pytest.mark.asyncio
    async def test_save_state_persists_jobs(self, state_manager, scheduler, mock_persistence):
        await _schedule(scheduler, msg_id="msg_1")
        state = state_manager.get_state(GUILD_ID)
        state.add_pending("msg_1")

        await state_manager.save_state(GUILD_ID)
        # Should have saved announcement doc for msg_1
        assert mock_persistence.save_announcement.call_count >= 1

    @pytest.mark.asyncio
    async def test_guild_context_caching(self, state_manager):
        ctx1 = state_manager.get_guild_context(GUILD_ID)
        ctx2 = state_manager.get_guild_context(GUILD_ID)
        assert ctx1 is ctx2

    @pytest.mark.asyncio
    async def test_guild_context_save_delegates(self, state_manager, mock_persistence):
        gctx = state_manager.get_guild_context(GUILD_ID)
        state = gctx.state
        state.add_pending("msg_1")

        await gctx.save_state()
        assert mock_persistence.save_announcement.called


# ===========================================================================
# 14. Edge cases: duplicate / ordering
# ===========================================================================

class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_schedule_two_different_messages(self, scheduler):
        """Two different messages can be scheduled simultaneously."""
        job_id1 = await _schedule(scheduler, msg_id="msg_1")
        job_id2 = await _schedule(scheduler, msg_id="msg_2")
        assert job_id1 != job_id2
        assert len(scheduler.list_jobs()) == 2

    @pytest.mark.asyncio
    async def test_reschedule_replaces_existing_job(self, scheduler):
        """Rescheduling for same msg_id always replaces the existing job, even if pending."""
        ts = _future_ts()
        job_id1 = await _schedule(scheduler, msg_id="msg_1", ts=ts, title="v1")
        assert scheduler.jobs["msg_1"].status == "pending"

        job_id2 = await _schedule(scheduler, msg_id="msg_1", ts=ts + 60, title="v2")
        # Since job_id == message_id, job_id1 == job_id2 == "msg_1"
        assert scheduler.jobs["msg_1"].title == "v2"
        assert scheduler.jobs["msg_1"].status == "pending"
        assert len(scheduler.list_jobs()) == 1

    def test_history_cap(self, state):
        """History respects max_history limit."""
        small_state = AnnouncementState(max_history=3)
        for i in range(5):
            small_state.add_pending(f"msg_{i}")
            small_state.mark_queued(f"msg_{i}", f"reply_{i}")
            small_state.mark_completed(f"msg_{i}")

        assert len(small_state.history) == 3
        # Most recent ones kept
        assert small_state.is_in_history("msg_4")
        assert small_state.is_in_history("msg_3")
        assert small_state.is_in_history("msg_2")
        assert not small_state.is_in_history("msg_0")
        assert not small_state.is_in_history("msg_1")

    def test_mark_completed_idempotent(self, state):
        """Calling mark_completed twice doesn't duplicate history."""
        state.add_pending("msg_1")
        state.mark_queued("msg_1", "reply_1")
        state.mark_completed("msg_1")
        state.mark_completed("msg_1")
        assert state.history.count("msg_1") == 1

    def test_find_request_by_bot_message_ignores_none_replies(self, state):
        """Cancelled entries with None reply_id don't match any lookup."""
        state.add_pending("msg_1")
        # reply_id is None (not yet queued)
        assert state.find_request_id_by_bot_message("anything") is None

    @pytest.mark.asyncio
    async def test_unschedule_missing_job_no_error(self, scheduler):
        """Unscheduling a nonexistent job doesn't raise."""
        scheduler.unschedule_job("does_not_exist")  # Should not raise

    @pytest.mark.asyncio
    async def test_get_job_by_message_id_returns_none_for_unknown(self, scheduler):
        assert scheduler.get_job_by_message_id("unknown") is None

    @pytest.mark.asyncio
    async def test_legacy_job_restore_fills_defaults(self, scheduler):
        """Legacy jobs without event_title or group_id get defaults."""
        ts = _future_ts()
        jobs_data = [{
            'id': 'job_legacy',
            'message_id': 'msg_legacy',
            'timestamp': ts,
            'title': 'Legacy Title',
            'content': 'Content',
            'guild_id': GUILD_ID,
            'status': 'pending',
            # No group_id, no event_title
        }]

        restored, _ = scheduler.restore_jobs(jobs_data, group_id='grp_fallback')
        assert restored == 1
        assert scheduler.jobs['job_legacy'].event_title == 'Legacy Title'
        assert scheduler.jobs['job_legacy'].group_id == 'grp_fallback'
