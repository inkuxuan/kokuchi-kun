import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
from kokuchi.services.scheduler import Scheduler
import time
import asyncio

@pytest.fixture
def mock_vrchat_api():
    return AsyncMock()

@pytest_asyncio.fixture
async def scheduler(mock_vrchat_api):
    # APScheduler start() needs a running loop
    sched = Scheduler(mock_vrchat_api)
    yield sched
    sched.shutdown()

@pytest_asyncio.fixture
async def scheduler_custom_grace(mock_vrchat_api):
    """Scheduler with custom misfire_grace_time."""
    sched = Scheduler(mock_vrchat_api, {'misfire_grace_time': 1800})
    yield sched
    sched.shutdown()

@pytest.mark.asyncio
async def test_schedule_announcement_stores_event_title(scheduler):
    timestamp = int(time.time()) + 3600
    start_ts = timestamp + 7200
    end_ts = timestamp + 10800

    job_id = await scheduler.schedule_announcement(
        timestamp,
        "Application Title",
        "Content",
        "msg_123",
        "111111111",
        group_id="grp_test",
        event_start_timestamp=start_ts,
        event_end_timestamp=end_ts,
        event_title="Event Title"
    )

    assert job_id in scheduler.jobs
    job = scheduler.jobs[job_id]

    assert job.event_start_timestamp == start_ts
    assert job.event_end_timestamp == end_ts
    assert job.message_id == "msg_123"
    assert job.title == "Application Title"
    assert job.event_title == "Event Title"

@pytest.mark.asyncio
async def test_schedule_announcement_default_event_title(scheduler):
    timestamp = int(time.time()) + 3600

    # Test without providing event_title
    job_id = await scheduler.schedule_announcement(
        timestamp,
        "Application Title",
        "Content",
        "msg_124",
        "111111111",
        group_id="grp_test",
    )

    job = scheduler.jobs[job_id]
    assert job.title == "Application Title"
    assert job.event_title == "Application Title" # Should default to title

@pytest.mark.asyncio
async def test_scheduler_persistence_format(scheduler):
    timestamp = 1000000000

    await scheduler.schedule_announcement(
        timestamp,
        "Title",
        "Content",
        "msg_123",
        "111111111",
        group_id="grp_test",
        event_start_timestamp=timestamp+100,
        event_end_timestamp=timestamp+200,
        event_title="Event Title"
    )

    jobs_data = scheduler.get_jobs_data()
    assert len(jobs_data) == 1

    saved_job = jobs_data[0]
    assert saved_job['event_start_timestamp'] == timestamp + 100
    assert saved_job['event_end_timestamp'] == timestamp + 200
    assert saved_job['event_title'] == "Event Title"

@pytest.mark.asyncio
async def test_restore_jobs(scheduler):
    future_time = int(time.time()) + 10000

    jobs_data = [{
        'id': 'job_1',
        'message_id': 'msg_1',
        'timestamp': future_time,
        'title': 'Restored Job',
        'content': 'Content',
        'guild_id': '111111111',
        'group_id': 'grp_test',
        'status': 'pending',
        'event_start_timestamp': future_time + 100,
        'event_end_timestamp': future_time + 200,
        'event_title': 'Restored Event Title'
    }]

    restored, skipped = scheduler.restore_jobs(jobs_data)

    assert restored == 1
    assert skipped == []
    assert 'job_1' in scheduler.jobs
    assert scheduler.jobs['job_1'].event_title == 'Restored Event Title'

@pytest.mark.asyncio
async def test_restore_legacy_jobs(scheduler):
    # Test restoring a job that doesn't have event_title (legacy)
    future_time = int(time.time()) + 10000

    jobs_data = [{
        'id': 'job_legacy',
        'message_id': 'msg_legacy',
        'timestamp': future_time,
        'title': 'Legacy Job',
        'content': 'Content',
        'guild_id': '111111111',
        'status': 'pending'
        # No group_id — tests migration fallback
    }]

    restored, skipped = scheduler.restore_jobs(jobs_data, group_id='grp_fallback')

    assert restored == 1
    assert 'job_legacy' in scheduler.jobs
    # Should default event_title to title
    assert scheduler.jobs['job_legacy'].event_title == 'Legacy Job'
    # Should use fallback group_id
    assert scheduler.jobs['job_legacy'].group_id == 'grp_fallback'

@pytest.mark.asyncio
async def test_restore_skips_terminal_jobs(scheduler):
    """Terminal jobs (success/failed/cancelled) are loaded into memory but not scheduled."""
    future_time = int(time.time()) + 10000

    jobs_data = [
        {
            'id': 'job_success',
            'message_id': 'msg_s',
            'timestamp': future_time,
            'title': 'Success Job',
            'content': 'Content',
            'guild_id': '111111111',
            'group_id': 'grp_test',
            'status': 'success',
        },
        {
            'id': 'job_cancelled',
            'message_id': 'msg_c',
            'timestamp': future_time,
            'title': 'Cancelled Job',
            'content': 'Content',
            'guild_id': '111111111',
            'group_id': 'grp_test',
            'status': 'cancelled',
        },
    ]

    restored, skipped = scheduler.restore_jobs(jobs_data)

    assert restored == 0
    assert skipped == []
    # Jobs are in memory but not in APScheduler
    assert 'job_success' in scheduler.jobs
    assert 'job_cancelled' in scheduler.jobs
    assert scheduler.scheduler.get_job('job_success') is None
    assert scheduler.scheduler.get_job('job_cancelled') is None

@pytest.mark.asyncio
async def test_restore_missed_jobs_within_grace(scheduler):
    """Past-due jobs within misfire_grace_time are scheduled and will fire."""
    # Job 30 minutes ago (within default 3600s grace)
    past_time = int(time.time()) - 1800

    jobs_data = [{
        'id': 'job_recent',
        'message_id': 'msg_r',
        'timestamp': past_time,
        'title': 'Recent Past Job',
        'content': 'Content',
        'guild_id': '111111111',
        'group_id': 'grp_test',
        'status': 'pending',
    }]

    restored, skipped = scheduler.restore_jobs(jobs_data)

    assert restored == 1
    assert skipped == []
    assert scheduler.jobs['job_recent'].status == 'pending'
    assert scheduler.scheduler.get_job('job_recent') is not None

@pytest.mark.asyncio
async def test_restore_missed_jobs_beyond_grace(scheduler):
    """Past-due jobs beyond misfire_grace_time are marked as missed."""
    # Job 2 hours ago (beyond default 3600s grace)
    past_time = int(time.time()) - 7200

    jobs_data = [{
        'id': 'job_old',
        'message_id': 'msg_o',
        'timestamp': past_time,
        'title': 'Old Past Job',
        'content': 'Content',
        'guild_id': '111111111',
        'group_id': 'grp_test',
        'status': 'pending',
    }]

    restored, skipped = scheduler.restore_jobs(jobs_data)

    assert restored == 0
    assert len(skipped) == 1
    assert scheduler.jobs['job_old'].status == 'missed'
    assert scheduler.scheduler.get_job('job_old') is None

@pytest.mark.asyncio
async def test_cancel_job_sets_status(scheduler):
    """cancel_job should set status to 'cancelled' instead of deleting."""
    timestamp = int(time.time()) + 3600
    job_id = await scheduler.schedule_announcement(
        timestamp, "Title", "Content", "msg_1", "111111111", group_id="grp_test"
    )

    result = scheduler.cancel_job(job_id)

    assert result is True
    assert job_id in scheduler.jobs  # Still in memory
    assert scheduler.jobs[job_id].status == 'cancelled'
    assert scheduler.scheduler.get_job(job_id) is None  # Removed from APScheduler

@pytest.mark.asyncio
async def test_cancel_job_by_message_id(scheduler):
    """cancel_job_by_message_id should set status to 'cancelled'."""
    timestamp = int(time.time()) + 3600
    job_id = await scheduler.schedule_announcement(
        timestamp, "Title", "Content", "msg_1", "111111111", group_id="grp_test"
    )

    result = scheduler.cancel_job_by_message_id("msg_1")

    assert result is True
    assert job_id in scheduler.jobs
    assert scheduler.jobs[job_id].status == 'cancelled'

@pytest.mark.asyncio
async def test_list_jobs_excludes_non_pending(scheduler):
    """list_jobs should only return pending jobs that are in APScheduler."""
    timestamp = int(time.time()) + 3600

    job_id1 = await scheduler.schedule_announcement(
        timestamp, "Active", "Content", "msg_1", "111111111", group_id="grp_test"
    )
    job_id2 = await scheduler.schedule_announcement(
        timestamp + 100, "Cancelled", "Content", "msg_2", "111111111", group_id="grp_test"
    )

    scheduler.cancel_job(job_id2)

    active_jobs = scheduler.list_jobs()
    assert len(active_jobs) == 1
    assert active_jobs[0].id == job_id1

@pytest.mark.asyncio
async def test_list_jobs_sorted_by_timestamp(scheduler):
    """list_jobs should return jobs sorted by timestamp."""
    base = int(time.time()) + 3600

    # Schedule jobs out of order: later first, then earlier
    await scheduler.schedule_announcement(
        base + 200, "Later", "Content", "msg_1", "111111111", group_id="grp_test"
    )
    await scheduler.schedule_announcement(
        base, "Earliest", "Content", "msg_2", "111111111", group_id="grp_test"
    )
    await scheduler.schedule_announcement(
        base + 100, "Middle", "Content", "msg_3", "111111111", group_id="grp_test"
    )

    active_jobs = scheduler.list_jobs()
    assert len(active_jobs) == 3
    assert active_jobs[0].title == "Earliest"
    assert active_jobs[1].title == "Middle"
    assert active_jobs[2].title == "Later"

@pytest.mark.asyncio
async def test_mark_job_success(scheduler):
    """mark_job_success should set status and remove from APScheduler."""
    timestamp = int(time.time()) + 3600
    job_id = await scheduler.schedule_announcement(
        timestamp, "Title", "Content", "msg_1", "111111111", group_id="grp_test"
    )

    scheduler.mark_job_success(job_id)

    assert scheduler.jobs[job_id].status == 'success'
    assert scheduler.scheduler.get_job(job_id) is None

@pytest.mark.asyncio
async def test_get_jobs_data_includes_all_statuses(scheduler):
    """get_jobs_data should return all jobs regardless of status."""
    timestamp = int(time.time()) + 3600

    job_id1 = await scheduler.schedule_announcement(
        timestamp, "Active", "Content", "msg_1", "111111111", group_id="grp_test"
    )
    job_id2 = await scheduler.schedule_announcement(
        timestamp + 100, "Cancelled", "Content", "msg_2", "111111111", group_id="grp_test"
    )
    scheduler.cancel_job(job_id2)

    jobs_data = scheduler.get_jobs_data()
    assert len(jobs_data) == 2

@pytest.mark.asyncio
async def test_custom_misfire_grace_time(scheduler_custom_grace):
    """Test that custom misfire_grace_time from config is used."""
    assert scheduler_custom_grace.misfire_grace_time == 1800

@pytest.mark.asyncio
async def test_unschedule_job_safe_for_missing(scheduler):
    """unschedule_job should not raise for jobs not in APScheduler."""
    # Should not raise
    scheduler.unschedule_job("nonexistent_job")
