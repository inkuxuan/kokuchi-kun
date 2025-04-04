import logging
import uuid
from datetime import datetime
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

logger = logging.getLogger(__name__)

class Scheduler:
    def __init__(self, vrchat_api):
        self.vrchat_api = vrchat_api
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_jobstore(MemoryJobStore(), 'default')
        self.jobs = {}
        
        # Start the scheduler
        self.scheduler.start()
        
    async def schedule_announcement(self, timestamp, title, content, message_id):
        """Schedule an announcement for the given timestamp"""
        job_id = str(uuid.uuid4())
        run_date = datetime.fromtimestamp(timestamp, tz=pytz.utc)
        
        logger.info(f"Scheduling announcement for {run_date} with job ID {job_id}")
        
        # Add job to scheduler
        self.scheduler.add_job(
            self._post_announcement,
            'date',
            run_date=run_date,
            args=[job_id, title, content],
            id=job_id
        )
        
        # Store job info
        self.jobs[job_id] = {
            'id': job_id,
            'message_id': message_id,
            'timestamp': timestamp,
            'formatted_date_time': datetime.fromtimestamp(timestamp).strftime('%Y年%m月%d日 %H:%M'),
            'title': title,
            'content': content
        }
        
        return job_id
        
    async def _post_announcement(self, job_id, title, content):
        """Execute the announcement posting"""
        try:
            logger.info(f"Executing scheduled job {job_id}")
            
            # Re-authenticate if needed
            if not self.vrchat_api.authenticated:
                auth_result = await self.vrchat_api.initialize()
                if not auth_result['success']:
                    logger.error(f"Failed to authenticate for job {job_id}: {auth_result['error']}")
                    return
            
            # Post the announcement
            result = await self.vrchat_api.post_announcement(title, content)
            
            if result['success']:
                logger.info(f"Successfully posted announcement to VRChat, post ID: {result['post_id']}")
            else:
                logger.error(f"Failed to post announcement to VRChat: {result['error']}")
                
            # Remove the job from the jobs dictionary
            if job_id in self.jobs:
                del self.jobs[job_id]
                
        except Exception as e:
            logger.error(f"Error executing scheduled job {job_id}: {e}")
    
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
            logger.error(f"Error cancelling job {job_id}: {e}")
            return False
    
    def cancel_job_by_message_id(self, message_id):
        """Cancel a scheduled job by message ID"""
        for job_id, job in list(self.jobs.items()):
            if job['message_id'] == message_id:
                return self.cancel_job(job_id)
        return False
    
    def shutdown(self):
        """Shutdown the scheduler"""
        self.scheduler.shutdown() 