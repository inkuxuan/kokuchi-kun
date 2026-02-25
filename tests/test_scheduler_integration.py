import unittest
from unittest.mock import MagicMock, AsyncMock
from utils.scheduler import Scheduler
import asyncio
from datetime import datetime
import pytz
import logging

class TestSchedulerIntegration(unittest.TestCase):
    def test_schedule_announcement_includes_grace_time(self):
        async def run_test():
            vrchat_api = AsyncMock()
            # Initialize Scheduler inside the loop where event loop exists
            scheduler = Scheduler(vrchat_api)
            # Mock the underlying APScheduler instance
            scheduler.scheduler = MagicMock()

            timestamp = datetime.now(pytz.utc).timestamp()
            title = "Test"
            content = "Content"
            message_id = "123"

            await scheduler.schedule_announcement(timestamp, title, content, message_id, "111111111", group_id="grp_test")

            # Verify add_job call
            call_args = scheduler.scheduler.add_job.call_args
            _, kwargs = call_args

            self.assertIn('misfire_grace_time', kwargs)
            self.assertEqual(kwargs['misfire_grace_time'], 3600)

            scheduler.shutdown()

        asyncio.run(run_test())

    def test_schedule_announcement_uses_config_grace_time(self):
        """Test that misfire_grace_time from config is passed to APScheduler."""
        async def run_test():
            vrchat_api = AsyncMock()
            scheduler = Scheduler(vrchat_api, {'misfire_grace_time': 1800})
            scheduler.scheduler = MagicMock()

            timestamp = datetime.now(pytz.utc).timestamp()
            await scheduler.schedule_announcement(timestamp, "Test", "Content", "123", "111111111", group_id="grp_test")

            call_args = scheduler.scheduler.add_job.call_args
            _, kwargs = call_args

            self.assertEqual(kwargs['misfire_grace_time'], 1800)

            scheduler.shutdown()

        asyncio.run(run_test())

    def test_restore_jobs_includes_grace_time(self):
        """Test that restored jobs also get misfire_grace_time."""
        async def run_test():
            import time
            vrchat_api = AsyncMock()
            scheduler = Scheduler(vrchat_api, {'misfire_grace_time': 1800})
            scheduler.scheduler = MagicMock()
            # Mock get_job to return None (for the APScheduler check in list_jobs)
            scheduler.scheduler.get_job = MagicMock(return_value=None)

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
            }]

            scheduler.restore_jobs(jobs_data)

            # Verify add_job was called with misfire_grace_time
            call_args = scheduler.scheduler.add_job.call_args
            _, kwargs = call_args

            self.assertIn('misfire_grace_time', kwargs)
            self.assertEqual(kwargs['misfire_grace_time'], 1800)

            scheduler.shutdown()

        asyncio.run(run_test())

if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    unittest.main()
