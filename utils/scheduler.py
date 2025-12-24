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
        
        # Start the scheduler
        self.scheduler.start()
        
    async def schedule_announcement(self, timestamp, title, content, message_id):
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
            id=job_id
        )
        
        # Store job info
        self.jobs[job_id] = {
            'id': job_id,
            'message_id': message_id,
            'timestamp': timestamp,
            'formatted_date_time': datetime.fromtimestamp(timestamp).strftime('%Y年%m月%d日 %H:%M'),
            'title': title,
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
                    return
            
            # Post the announcement
            result = await self.vrchat_api.post_announcement(title, content)
            
            if result['success']:
                logger.info(Messages.Log.POST_SUCCESS.format(result['post_id']))
                self.jobs[job_id]['status'] = 'success'
            else:
                logger.error(Messages.Log.POST_FAIL.format(result['error']))
                self.jobs[job_id]['status'] = 'failed'
                
                # If authentication failed, we'll retry after reauth
                if "Authentication failed" in result['error']:
                    # The post will be automatically retried after reauth
                    return
                
            # Remove the job from the jobs dictionary if it succeeded
            if self.jobs[job_id]['status'] == 'success':
                del self.jobs[job_id]
                
        except Exception as e:
            logger.error(Messages.Log.JOB_EXEC_ERROR.format(job_id, e))
            self.jobs[job_id]['status'] = 'failed'
    
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