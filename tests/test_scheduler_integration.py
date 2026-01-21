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

            await scheduler.schedule_announcement(timestamp, title, content, message_id)

            # Verify add_job call
            call_args = scheduler.scheduler.add_job.call_args
            _, kwargs = call_args

            self.assertIn('misfire_grace_time', kwargs)
            self.assertEqual(kwargs['misfire_grace_time'], 3600)

            scheduler.shutdown()

        asyncio.run(run_test())

if __name__ == '__main__':
    logging.disable(logging.CRITICAL)
    unittest.main()
