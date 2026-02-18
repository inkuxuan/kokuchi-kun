import logging
import uuid
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from utils.messages import Messages

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, vrchat_api):
        self.vrchat_api = vrchat_api
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_jobstore(MemoryJobStore(), 'default')
        self.jobs = {}
        self.on_job_completion = None
        
        # Start the scheduler
        self.scheduler.start()

    def set_on_job_completion(self, callback):
        """Set callback for job completion (success or failure)"""
        self.on_job_completion = callback
        
    async def schedule_announcement(self, timestamp, title, content, message_id, event_start_timestamp=None, event_end_timestamp=None, event_title=None):
        """Schedule an announcement for the given timestamp"""
        job_id = str(uuid.uuid4())
        run_date = datetime.fromtimestamp(timestamp, tz=pytz.utc)
        
        logger.info(Messages.Log.SCHEDULING_JOB.format(run_date, job_id))
        
        # Add job to scheduler
        self.scheduler.add_job(
            self._post_announcement,
            'date',
            run_date=run_date,
            args=[job_id, title, content],
            id=job_id,
            misfire_grace_time=3600  # Allow execution up to 1 hour late (immediate post for recent past)
        )
        
        # Store job info
        if event_title is None:
            event_title = title

        self.jobs[job_id] = {
            'id': job_id,
            'message_id': message_id,
            'timestamp': timestamp,
            'event_start_timestamp': event_start_timestamp,
            'event_end_timestamp': event_end_timestamp,
            'formatted_date_time': datetime.fromtimestamp(timestamp).strftime('%Y年%m月%d日 %H:%M'),
            'title': title,
            'event_title': event_title,
            'content': content,
            'status': 'pending'  # pending, success, failed
        }
        
        return job_id
        
    async def _post_announcement(self, job_id, title, content):
        """Execute the announcement posting"""
        try:
            logger.info(Messages.Log.EXECUTING_JOB.format(job_id))

            # Re-authenticate if needed
            if not self.vrchat_api.authenticated:
                auth_result = await self.vrchat_api.initialize()
                if not auth_result['success']:
                    logger.error(Messages.Log.JOB_AUTH_FAIL.format(job_id, auth_result['error']))
                    self.jobs[job_id]['status'] = 'failed'
                    # Notify callback to persist the failure
                    if self.on_job_completion:
                        await self.on_job_completion(self.jobs[job_id].copy())
                    return

            # Post the announcement
            result = await self.vrchat_api.post_announcement(title, content)

            if result['success']:
                logger.info(Messages.Log.POST_SUCCESS.format(result.get('post_id', 'N/A')))
                self.jobs[job_id]['status'] = 'success'
            else:
                logger.error(Messages.Log.POST_FAIL.format(result['error']))
                self.jobs[job_id]['status'] = 'failed'

                # If authentication failed, we'll retry after reauth
                if "Authentication failed" in result['error']:
                    # The post will be automatically retried after reauth
                    return

            # Copy job data before potential deletion
            job_data = self.jobs[job_id].copy()

            # Remove the job from the jobs dictionary if it succeeded
            if self.jobs[job_id]['status'] == 'success':
                del self.jobs[job_id]

            # Notify callback for both success and failure to persist state
            if self.on_job_completion:
                await self.on_job_completion(job_data)

        except Exception as e:
            logger.error(Messages.Log.JOB_EXEC_ERROR.format(job_id, e))
            if job_id in self.jobs:
                self.jobs[job_id]['status'] = 'failed'
                # Notify callback to persist the failure
                if self.on_job_completion:
                    await self.on_job_completion(self.jobs[job_id].copy())
    
    def restore_jobs(self, jobs_list):
        """Restore jobs from storage. Returns (restored_count, skipped_jobs_list)"""
        restored_count = 0
        skipped_jobs = []
        current_time = datetime.now(pytz.utc).timestamp()

        for job_data in jobs_list:
            try:
                # Check if job is in the past
                if job_data['timestamp'] <= current_time:
                    skipped_jobs.append(job_data)
                    continue

                job_id = job_data['id']
                run_date = datetime.fromtimestamp(job_data['timestamp'], tz=pytz.utc)

                # Add job to scheduler
                self.scheduler.add_job(
                    self._post_announcement,
                    'date',
                    run_date=run_date,
                    args=[job_id, job_data['title'], job_data['content']],
                    id=job_id
                )

                # Restore to jobs dict
                if 'event_title' not in job_data:
                    job_data['event_title'] = job_data['title']

                self.jobs[job_id] = job_data
                restored_count += 1
                logger.info(f"Restored job {job_id} scheduled for {run_date}")

            except Exception as e:
                logger.error(f"Failed to restore job {job_data.get('id')}: {e}")

        return restored_count, skipped_jobs

    def get_jobs_data(self):
        """Get list of current jobs for persistence"""
        return list(self.jobs.values())

    def list_jobs(self):
        """List all active scheduled jobs"""
        active_jobs = []
        for job in self.jobs.values():
            # Check if the job still exists in the scheduler
            if self.scheduler.get_job(job['id']) is not None:
                active_jobs.append(job)
        return active_jobs
    
    def cancel_job(self, job_id):
        """Cancel a scheduled job"""
        if job_id not in self.jobs:
            return False
        
        try:
            self.scheduler.remove_job(job_id)
            del self.jobs[job_id]
            return True
        except Exception as e:
            logger.error(Messages.Log.JOB_CANCEL_ERROR.format(job_id, e))
            return False
    
    def cancel_job_by_message_id(self, message_id):
        """Cancel a scheduled job by message ID"""
        for job_id, job in list(self.jobs.items()):
            if job['message_id'] == message_id:
                return self.cancel_job(job_id)
        return False

    def get_job_by_message_id(self, message_id):
        """Get a scheduled job by message ID"""
        for job in self.jobs.values():
            if job['message_id'] == message_id:
                return job
        return None
    
    def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
