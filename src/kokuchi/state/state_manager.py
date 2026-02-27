import logging
from kokuchi.state.announcement_state import AnnouncementState

logger = logging.getLogger(__name__)


class GuildContext:
    """Pre-resolved per-guild references.

    Eliminates repeated guild_id lookups and config unpacking in cog methods.
    Created once per guild by StateManager and reused throughout the session.
    """

    def __init__(self, guild_id, state, group_id, admin_role_id, enabled, channel_ids, state_manager):
        self.guild_id = guild_id
        self.state = state
        self.group_id = group_id
        self.admin_role_id = admin_role_id
        self.enabled = enabled
        self.channel_ids = channel_ids
        self._state_manager = state_manager

    async def save_state(self):
        """Save this guild's state to Firestore (bulk — all announcements)."""
        await self._state_manager.save_state(self.guild_id)

    async def save_announcement(self, msg_id):
        """Save a single announcement document for this guild."""
        await self._state_manager.save_announcement(self.guild_id, msg_id)

    async def load_state(self):
        """Load this guild's state from Firestore.

        Returns (restored_job_count, pending_count, skipped_jobs_list).
        """
        return await self._state_manager.load_state(self.guild_id)

    async def cancel_announcement_detailed(self, message_id):
        """Cancel an announcement for this guild. Returns (success, deleted_calendar)."""
        return await self._state_manager.cancel_announcement_detailed(self.guild_id, message_id)


class StateManager:
    """Unified facade for per-guild announcement state and persistence.

    Owns AnnouncementState instances and Persistence references, and
    orchestrates operations that span multiple subsystems (e.g. cancel
    requires scheduler + state + calendar + persistence).

    Both AnnouncementCog and AdminCog depend on this service instead of
    reaching into each other. The scheduler is accessed via
    ``state_manager.scheduler`` rather than being passed separately.
    """

    def __init__(self, scheduler, vrchat_api, guild_persistences, guild_configs):
        """
        Args:
            scheduler: Scheduler instance (for job data persistence and cancel).
            vrchat_api: VRChatAPI instance (for calendar event deletion).
            guild_persistences: dict of guild_id (str) -> Persistence.
            guild_configs: dict of guild_id (str) -> guild config dict.
        """
        self.scheduler = scheduler
        self.vrchat_api = vrchat_api
        self.guild_persistences = guild_persistences
        self.guild_configs = guild_configs
        self.guild_states = {}  # guild_id -> AnnouncementState
        self._guild_contexts = {}  # guild_id -> GuildContext (cached)

    # --- Accessors ---

    def get_state(self, guild_id):
        """Return (or lazily create) the AnnouncementState for a guild."""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = AnnouncementState()
        return self.guild_states[guild_id]

    def get_persistence(self, guild_id):
        """Return the Persistence for a guild."""
        return self.guild_persistences.get(guild_id)

    def get_guild_context(self, guild_id):
        """Return a GuildContext with pre-resolved references for the given guild.

        Cached per guild_id so the same object is returned on repeated calls.
        """
        if guild_id not in self._guild_contexts:
            guild_conf = self.guild_configs.get(guild_id, {})
            self._guild_contexts[guild_id] = GuildContext(
                guild_id=guild_id,
                state=self.get_state(guild_id),
                group_id=guild_conf.get('group_id'),
                admin_role_id=guild_conf.get('admin_role_id'),
                enabled=guild_conf.get('enabled', True),
                channel_ids=guild_conf.get('channel_ids', []),
                state_manager=self,
            )
        return self._guild_contexts[guild_id]

    def _get_group_id(self, guild_id):
        """Return the VRChat group_id for a guild."""
        guild_conf = self.guild_configs.get(guild_id)
        if guild_conf is None:
            return None
        return guild_conf.get('group_id')

    # --- State persistence ---

    async def save_announcement(self, guild_id, msg_id):
        """Save a single announcement document for a guild.

        Writes to servers/{server_id}/announcements/{msg_id} with the full
        current state of that announcement (bot_reply_id, calendar_event_id,
        completed flag, and embedded job dict).
        """
        state = self.get_state(guild_id)
        persistence = self.get_persistence(guild_id)
        if not persistence:
            logger.warning(f"No persistence configured for guild {guild_id}, announcement not saved")
            return

        job = self.scheduler.get_job_by_message_id(msg_id)
        doc = {
            'guild_id': guild_id,
            'bot_reply_id': state.get_bot_reply_id(msg_id),
            'calendar_event_id': state.get_calendar_event_id(msg_id),
            'completed': state.is_in_history(msg_id),
            'job': job.to_dict() if job else None,
        }
        await persistence.save_announcement(msg_id, doc)
        logger.info(f"Saved announcement {msg_id} for guild {guild_id}")

    async def save_state(self, guild_id=None):
        """Bulk save: write all known announcements for the given guild.

        If guild_id is None, saves all guilds. Used only on on_ready after
        load_state() to persist any status updates (e.g. missed jobs).
        """
        guilds_to_save = [guild_id] if guild_id is not None else list(self.guild_states.keys())
        for gid in guilds_to_save:
            state = self.get_state(gid)
            persistence = self.get_persistence(gid)
            if not persistence:
                logger.warning(f"No persistence configured for guild {gid}, state not saved")
                continue

            # Collect all known msg_ids from state and scheduler
            msg_ids = set(state.pending_requests.keys())
            for job in self.scheduler.jobs.values():
                if job.guild_id == gid and job.message_id:
                    msg_ids.add(job.message_id)

            for msg_id in msg_ids:
                job = self.scheduler.get_job_by_message_id(msg_id)
                doc = {
                    'guild_id': gid,
                    'bot_reply_id': state.get_bot_reply_id(msg_id),
                    'calendar_event_id': state.get_calendar_event_id(msg_id),
                    'completed': state.is_in_history(msg_id),
                    'job': job.to_dict() if job else None,
                }
                await persistence.save_announcement(msg_id, doc)

            logger.info(f"State saved for guild {gid}: {len(msg_ids)} announcements")

    async def load_state(self, guild_id):
        """Load state from Firestore for a specific guild.

        Tries the new per-announcement format first; falls back to the old
        flat-list format if no announcement documents are found.

        Returns (restored_job_count, pending_count, skipped_jobs_list).
        """
        state = self.get_state(guild_id)
        persistence = self.get_persistence(guild_id)
        if not persistence:
            logger.warning(f"No persistence configured for guild {guild_id}, skipping state load")
            return 0, 0, []

        # --- Try new per-announcement format ---
        announcements = await persistence.load_announcements()

        if announcements:
            logger.info(f"Loading {len(announcements)} announcement documents for guild {guild_id}")
            jobs_data = []
            for msg_id, doc in announcements.items():
                bot_reply_id = doc.get('bot_reply_id')
                calendar_event_id = doc.get('calendar_event_id')
                completed = doc.get('completed', False)
                job_dict = doc.get('job')

                # Reconstruct pending_requests (always — even for completed)
                state.pending_requests[msg_id] = bot_reply_id

                # Reconstruct calendar_events
                if calendar_event_id is not None:
                    state.calendar_events[msg_id] = calendar_event_id

                # Reconstruct history
                if completed and msg_id not in state.history:
                    state.history.append(msg_id)

                # Collect job dicts for scheduler restoration
                if job_dict:
                    jobs_data.append(job_dict)

        else:
            # --- Fallback to old flat-list format ---
            logger.info(f"No announcement documents found for guild {guild_id}, falling back to old format")
            state.pending_requests = await persistence.load_data('pending', {})
            state.history = await persistence.load_data('history', [])
            state.calendar_events = await persistence.load_data('calendar', {})
            jobs_data = await persistence.load_data('jobs', [])

        logger.info(
            f"State loaded for guild {guild_id}: {len(state.pending_requests)} pending, "
            f"{len(state.history)} history, {len(state.calendar_events)} calendar"
        )

        restored_count, skipped_jobs = self.scheduler.restore_jobs(
            jobs_data,
            guild_id=guild_id,
            group_id=self._get_group_id(guild_id),
        )

        # Rebuild queued_announcements from restored active jobs
        state.queued_announcements = set()
        for job in self.scheduler.list_jobs(guild_id=guild_id):
            if job.message_id:
                state.queued_announcements.add(job.message_id)
        logger.info(f"Rebuilt queued_announcements for guild {guild_id}: {state.queued_announcements}")

        return restored_count, len(state.pending_requests), skipped_jobs

    # --- Composite operations ---

    async def cancel_announcement(self, guild_id, message_id):
        """Cancel an announcement by message ID.

        Orchestrates: scheduler cancel -> state cancel -> calendar deletion -> persist.

        Returns True if the job was found and cancelled, False otherwise.
        """
        logger.info(f"Cancelling announcement: guild={guild_id}, msg={message_id}")

        # Cancel in scheduler (unschedule + set status to 'cancelled')
        if not self.scheduler.cancel_job_by_message_id(message_id):
            logger.warning(f"Cancel failed: no job found for msg {message_id}")
            return False

        # Cancel in state (sets pending to None, returns calendar_event_id)
        state = self.get_state(guild_id)
        calendar_event_id = state.cancel(message_id)

        # Delete calendar event if one was associated
        if calendar_event_id:
            group_id = self._get_group_id(guild_id)
            if group_id:
                logger.info(f"Deleting associated calendar event {calendar_event_id}")
                await self.vrchat_api.delete_group_calendar_event(group_id, calendar_event_id)

        # Persist the cancellation
        await self.save_announcement(guild_id, message_id)

        return True

    async def cancel_announcement_detailed(self, guild_id, message_id):
        """Like cancel_announcement but returns (success, deleted_calendar)."""
        logger.info(f"Cancelling announcement (detailed): guild={guild_id}, msg={message_id}")

        if not self.scheduler.cancel_job_by_message_id(message_id):
            logger.warning(f"Cancel failed: no job found for msg {message_id}")
            return False, False

        state = self.get_state(guild_id)
        calendar_event_id = state.cancel(message_id)

        deleted_calendar = False
        if calendar_event_id:
            group_id = self._get_group_id(guild_id)
            if group_id:
                logger.info(f"Deleting associated calendar event {calendar_event_id}")
                await self.vrchat_api.delete_group_calendar_event(group_id, calendar_event_id)
                deleted_calendar = True

        await self.save_announcement(guild_id, message_id)
        logger.info(f"Announcement cancelled: msg={message_id}, calendar_deleted={deleted_calendar}")

        return True, deleted_calendar

    async def cancel_specific_job(self, guild_id, job_id):
        """Cancel a specific job by its exact job ID (not by message_id).

        Fixes the admin /cancel bug where cancel_job_by_message_id could cancel
        a different job for the same message.

        Returns (success, deleted_calendar).
        """
        logger.info(f"Cancelling specific job: guild={guild_id}, job={job_id}")

        job = self.scheduler.get_job(job_id)
        if not job:
            logger.warning(f"Cancel failed: job {job_id} not found")
            return False, False

        msg_id = job.message_id

        if not self.scheduler.cancel_job(job_id):
            logger.warning(f"Cancel failed: scheduler could not cancel job {job_id}")
            return False, False

        state = self.get_state(guild_id)
        calendar_event_id = state.cancel(msg_id)

        deleted_calendar = False
        if calendar_event_id:
            group_id = self._get_group_id(guild_id)
            if group_id:
                logger.info(f"Deleting associated calendar event {calendar_event_id}")
                await self.vrchat_api.delete_group_calendar_event(group_id, calendar_event_id)
                deleted_calendar = True

        await self.save_announcement(guild_id, msg_id)
        logger.info(f"Job {job_id} cancelled: msg={msg_id}, calendar_deleted={deleted_calendar}")

        return True, deleted_calendar
