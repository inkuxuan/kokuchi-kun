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
        """Save this guild's state to Firestore."""
        await self._state_manager.save_state(self.guild_id)

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

    async def save_state(self, guild_id=None):
        """Save the current state to Firestore for the given guild.

        If guild_id is None, saves all guilds.
        """
        guilds_to_save = [guild_id] if guild_id is not None else list(self.guild_states.keys())
        for gid in guilds_to_save:
            state = self.get_state(gid)
            persistence = self.get_persistence(gid)
            if persistence:
                await state.save(persistence)
                jobs_data = self.scheduler.get_jobs_data(guild_id=gid)
                logger.info(f"Saving {len(jobs_data)} jobs for guild {gid}: {[(j['id'][:8], j['message_id'], j['status']) for j in jobs_data]}")
                await persistence.save_data('jobs', jobs_data)
                logger.info(f"State saved for guild {gid}")
            else:
                logger.warning(f"No persistence configured for guild {gid}, state not saved")

    async def load_state(self, guild_id):
        """Load state from Firestore for a specific guild.

        Returns (restored_job_count, pending_count, skipped_jobs_list).
        """
        state = self.get_state(guild_id)
        persistence = self.get_persistence(guild_id)
        if not persistence:
            logger.warning(f"No persistence configured for guild {guild_id}, skipping state load")
            return 0, 0, []

        await state.load(persistence)
        logger.info(f"State loaded for guild {guild_id}: {len(state.pending_requests)} pending, {len(state.history)} history, {len(state.calendar_events)} calendar")

        jobs_data = await persistence.load_data('jobs', [])
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
        await self.save_state(guild_id)

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

        await self.save_state(guild_id)
        logger.info(f"Announcement cancelled: msg={message_id}, calendar_deleted={deleted_calendar}")

        return True, deleted_calendar
