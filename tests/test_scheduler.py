import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock
from utils.scheduler import Scheduler
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
        "msg_124"
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
        'status': 'pending'
    }]

    restored, skipped = scheduler.restore_jobs(jobs_data)

    assert restored == 1
    assert 'job_legacy' in scheduler.jobs
    # Should default event_title to title
    assert scheduler.jobs['job_legacy'].event_title == 'Legacy Job'
