from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import TYPE_CHECKING, Any

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from kokuchi.common.messages import Messages
from kokuchi.common.models import JobData

if TYPE_CHECKING:
    from kokuchi.services.vrchat_api import VRChatAPI

logger = logging.getLogger(__name__)

# Job statuses that indicate the job is terminal (no longer active)
TERMINAL_STATUSES = frozenset({'success', 'failed', 'cancelled'})

class Scheduler:
    def __init__(self, vrchat_api: VRChatAPI, scheduler_config: dict | None = None) -> None:
        self.vrchat_api = vrchat_api
        self.scheduler = AsyncIOScheduler()
        self.scheduler.add_jobstore(MemoryJobStore(), 'default')
        self.jobs: dict[str, JobData] = {}
        self.on_job_completion: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None

        # Load misfire_grace_time from config (default: 3600 seconds = 1 hour)
        if scheduler_config is None:
            scheduler_config = {}
        self.misfire_grace_time: int = scheduler_config.get('misfire_grace_time', 3600)

        # Start the scheduler
        self.scheduler.start()

    def set_on_job_completion(
        self, callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        """Set callback for job completion (success or failure)"""
        self.on_job_completion = callback

    async def schedule_announcement(
        self,
        timestamp: float,
        title: str,
        content: str,
        message_id: str,
        guild_id: str,
        group_id: str | None = None,
        channel_id: str | None = None,
        event_start_timestamp: float | None = None,
        event_end_timestamp: float | None = None,
        event_title: str | None = None,
    ) -> str:
        """Schedule an announcement for the given timestamp"""
        # Since job_id == message_id, there is at most one entry to remove.
        # Active (non-terminal) jobs are also unscheduled from APScheduler to prevent
        # a duplicate post when a restored pending job and a freshly-created job both
        # end up in APScheduler for the same message.
        existing_job = self.jobs.get(message_id)
        if existing_job:
            if existing_job.status not in TERMINAL_STATUSES:
                self.unschedule_job(message_id)
            logger.info(f"Removing existing job {message_id} (status={existing_job.status}) for re-scheduled msg {message_id}")
            del self.jobs[message_id]

        job_id = message_id
        run_date = datetime.fromtimestamp(timestamp, tz=pytz.utc)

        logger.info(Messages.Log.SCHEDULING_JOB.format(run_date, job_id))

        # Add job to scheduler
        self.scheduler.add_job(
            self._post_announcement,
            'date',
            run_date=run_date,
            args=[job_id, title, content, group_id],
            id=job_id,
            misfire_grace_time=self.misfire_grace_time
        )

        # Store job info
        if event_title is None:
            event_title = title

        self.jobs[job_id] = JobData(
            id=job_id,
            message_id=message_id,
            guild_id=guild_id,
            group_id=group_id,
            channel_id=channel_id,
            timestamp=timestamp,
            event_start_timestamp=event_start_timestamp,
            event_end_timestamp=event_end_timestamp,
            formatted_date_time=datetime.fromtimestamp(timestamp).strftime('%Y年%m月%d日 %H:%M'),
            title=title,
            event_title=event_title,
            content=content,
        )

        return job_id

    async def _post_announcement(
        self, job_id: str, title: str, content: str, group_id: str | None
    ) -> None:
        """Execute the announcement posting"""
        try:
            # Guard against duplicate execution: if the job was fast-forwarded (or otherwise
            # completed) while APScheduler had already queued this coroutine, skip execution.
            if job_id in self.jobs and self.jobs[job_id].status in TERMINAL_STATUSES:
                logger.info(
                    f"Job {job_id} already terminal (status={self.jobs[job_id].status}), skipping execution"
                )
                return

            logger.info(Messages.Log.EXECUTING_JOB.format(job_id))

            # Re-authenticate if needed
            if not self.vrchat_api.authenticated:
                logger.info(f"Job {job_id}: VRChat not authenticated, attempting re-auth")
                auth_result = await self.vrchat_api.initialize()
                if not auth_result.success:
                    logger.error(Messages.Log.JOB_AUTH_FAIL.format(job_id, auth_result.error))
                    self.jobs[job_id].status = 'failed'
                    if self.on_job_completion:
                        await self.on_job_completion(self.jobs[job_id].to_dict())
                    return

            # Post the announcement
            result = await self.vrchat_api.post_announcement(group_id, title, content)

            if result.success:
                logger.info(Messages.Log.POST_SUCCESS.format('N/A'))
                self.jobs[job_id].status = 'success'
            else:
                logger.error(Messages.Log.POST_FAIL.format(result.error))
                self.jobs[job_id].status = 'failed'

                # If authentication failed, we'll retry after reauth
                if "Authentication failed" in result.error:
                    logger.warning(f"Job {job_id}: auth failure during post, skipping completion callback for retry")
                    return

            # Notify callback for both success and failure to persist state
            # Note: we do NOT delete the job from self.jobs — status update is sufficient
            if self.on_job_completion:
                await self.on_job_completion(self.jobs[job_id].to_dict())

        except Exception as e:
            logger.error(Messages.Log.JOB_EXEC_ERROR.format(job_id, e), exc_info=True)
            if job_id in self.jobs:
                self.jobs[job_id].status = 'failed'
                if self.on_job_completion:
                    await self.on_job_completion(self.jobs[job_id].to_dict())

    def restore_jobs(
        self,
        jobs_list: list[dict[str, Any]],
        guild_id: str | None = None,
        group_id: str | None = None,
    ) -> tuple[int, list[dict[str, Any]]]:
        """Restore jobs from storage. Returns (restored_count, skipped_jobs_list)

        Jobs with terminal statuses (success/failed/cancelled) are kept in memory
        but not re-scheduled with APScheduler.

        Past-due jobs within misfire_grace_time are scheduled (APScheduler will fire
        them immediately). Past-due jobs beyond the grace period are marked 'missed'
        and kept in memory so they can still be fast-forwarded or have calendar events
        created.

        group_id is used as fallback for old jobs that don't have group_id stored.
        """
        restored_count = 0
        skipped_jobs: list[dict[str, Any]] = []
        current_time = datetime.now(pytz.utc).timestamp()

        logger.info(f"Restoring {len(jobs_list)} jobs for guild={guild_id}")

        for job_data in jobs_list:
            try:
                job_id = job_data['id']

                # Migration: fill in missing fields
                if 'event_title' not in job_data:
                    job_data['event_title'] = job_data['title']
                if 'guild_id' not in job_data:
                    job_data['guild_id'] = guild_id
                if not job_data.get('group_id'):
                    job_data['group_id'] = group_id

                status = job_data.get('status', 'pending')

                # Always restore the job data into memory (regardless of status)
                self.jobs[job_id] = JobData.from_dict(job_data)

                # Terminal jobs: keep in memory but don't schedule
                if status in TERMINAL_STATUSES:
                    logger.info(f"Restored terminal job {job_id} (status={status})")
                    continue

                # Missed jobs from previous run: keep in memory but don't schedule
                if status == 'missed':
                    skipped_jobs.append(job_data)
                    logger.info(f"Restored missed job {job_id}")
                    continue

                # Active (pending) jobs: check timing
                effective_group_id = job_data.get('group_id')

                if job_data['timestamp'] <= current_time:
                    # Past-due: check if within misfire_grace_time
                    if current_time - job_data['timestamp'] <= self.misfire_grace_time:
                        # Within grace period: schedule it (APScheduler will fire immediately)
                        run_date = datetime.fromtimestamp(job_data['timestamp'], tz=pytz.utc)
                        self.scheduler.add_job(
                            self._post_announcement,
                            'date',
                            run_date=run_date,
                            args=[job_id, job_data['title'], job_data['content'], effective_group_id],
                            id=job_id,
                            misfire_grace_time=self.misfire_grace_time
                        )
                        restored_count += 1
                        logger.info(f"Restored past-due job {job_id} within grace period, will fire immediately")
                    else:
                        # Beyond grace period: mark as missed
                        self.jobs[job_id].status = 'missed'
                        skipped_jobs.append(job_data)
                        logger.info(f"Job {job_id} missed (past due beyond grace period)")
                else:
                    # Future job: schedule normally
                    run_date = datetime.fromtimestamp(job_data['timestamp'], tz=pytz.utc)
                    self.scheduler.add_job(
                        self._post_announcement,
                        'date',
                        run_date=run_date,
                        args=[job_id, job_data['title'], job_data['content'], effective_group_id],
                        id=job_id,
                        misfire_grace_time=self.misfire_grace_time
                    )
                    restored_count += 1
                    logger.info(f"Restored job {job_id} scheduled for {run_date}")

            except Exception as e:
                logger.error(f"Failed to restore job {job_data.get('id')}: {e}", exc_info=True)

        logger.info(f"Job restore complete: {restored_count} active, {len(skipped_jobs)} skipped")
        return restored_count, skipped_jobs

    def get_jobs_data(self, guild_id: str | None = None) -> list[dict[str, Any]]:
        """Get list of ALL jobs for persistence, optionally filtered by guild_id.

        Includes terminal jobs so their status is preserved across restarts.
        """
        jobs = self.jobs.values()
        if guild_id is not None:
            jobs = [j for j in jobs if j.guild_id == guild_id]
        return [job.to_dict() for job in jobs]

    def list_jobs(self, guild_id: str | None = None) -> list[JobData]:
        """List active scheduled jobs (pending status, still in APScheduler).

        Used for /list command and for rebuilding queued_announcements on restore.
        """
        active_jobs = []
        for job in self.jobs.values():
            if job.status == 'pending' and self.scheduler.get_job(job.id) is not None:
                if guild_id is None or job.guild_id == guild_id:
                    active_jobs.append(job)
        active_jobs.sort(key=lambda j: j.timestamp)
        return active_jobs

    def get_job(self, job_id: str) -> JobData | None:
        """Get a job by its ID, or None if not found"""
        return self.jobs.get(job_id)

    def get_job_by_message_id(self, message_id: str) -> JobData | None:
        """Get a job by message ID (any status). Returns None if not found."""
        return self.jobs.get(message_id)

    def unschedule_job(self, job_id: str) -> None:
        """Remove a job from APScheduler without changing the job's status in self.jobs.

        Safe to call even if the job is not in APScheduler (e.g., missed jobs).
        """
        try:
            if self.scheduler.get_job(job_id) is not None:
                self.scheduler.remove_job(job_id)
                logger.info(f"Unscheduled job {job_id} from APScheduler")
        except Exception as e:
            logger.error(f"Error unscheduling job {job_id}: {e}")

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a scheduled job by setting its status to 'cancelled'.

        Removes from APScheduler if present but keeps the job in self.jobs.
        """
        if job_id not in self.jobs:
            logger.warning(f"Cannot cancel job {job_id}: not found")
            return False

        try:
            self.unschedule_job(job_id)
            self.jobs[job_id].status = 'cancelled'
            logger.info(f"Job {job_id} cancelled")
            return True
        except Exception as e:
            logger.error(Messages.Log.JOB_CANCEL_ERROR.format(job_id, e), exc_info=True)
            return False

    def cancel_job_by_message_id(self, message_id: str) -> bool:
        """Cancel a scheduled job by message ID"""
        return self.cancel_job(message_id)

    def mark_job_success(self, job_id: str) -> None:
        """Mark a job as successfully completed (for immediate posting)."""
        if job_id in self.jobs:
            self.unschedule_job(job_id)
            self.jobs[job_id].status = 'success'
            logger.info(f"Job {job_id} marked as success")

    def mark_job_failed(self, job_id: str) -> None:
        """Mark a job as failed."""
        if job_id in self.jobs:
            self.unschedule_job(job_id)
            self.jobs[job_id].status = 'failed'
            logger.info(f"Job {job_id} marked as failed")

    def shutdown(self) -> None:
        """Shutdown the scheduler"""
        self.scheduler.shutdown()
