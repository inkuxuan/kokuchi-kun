import logging
import discord
from discord.ext import commands
from discord import app_commands
import time
from kokuchi.common.messages import Messages

logger = logging.getLogger(__name__)

class AnnouncementCog(commands.Cog):
    def __init__(self, bot, config, ai_processor, state_manager, vrchat_api):
        self.bot = bot
        self.config = config
        self.ai_processor = ai_processor
        self.state_manager = state_manager
        self.vrchat_api = vrchat_api

        # Per-guild config lookup: guild_id (str) -> config dict
        self.guild_configs = {}
        for guild_conf in config['discord'].get('guilds', []):
            gid = guild_conf['guild_id']  # str after normalization
            self.guild_configs[gid] = guild_conf

        # Build flat set of all monitored channel IDs for quick lookup
        self._all_channel_ids = set()
        for guild_conf in self.guild_configs.values():
            self._all_channel_ids.update(guild_conf.get('channel_ids', []))

        # Global emoji config (shared across guilds)
        self.seen_emoji = config['discord'].get('seen_reaction_emoji', "👀")
        self.approval_emoji = config['discord'].get('approval_reaction_emoji', "👍")
        self.fast_forward_emoji = config['discord'].get('fast_forward_emoji', "⏩")
        self.calendar_emoji = config['discord'].get('calendar_emoji', "📅")

        # Admin user ID (receives config warnings)
        self.admin_id = config['discord'].get('admin_id')

        # Set up job completion callback
        self.state_manager.scheduler.set_on_job_completion(self._on_job_complete)

    # --- Callbacks ---

    async def _on_job_complete(self, job_data):
        """Callback for when a job completes (success or failure)"""
        try:
            message_id = job_data.get('message_id')
            status = job_data.get('status', 'success')
            guild_id = job_data['guild_id']

            gctx = self.state_manager.get_guild_context(guild_id)

            if message_id and status == 'success':
                gctx.state.mark_completed(message_id)

            # Save state for both success and failure
            await gctx.save_state()
            guild = self.bot.get_guild(int(guild_id)) if guild_id else None
            logger.info(
                f"Job completion callback: status={status}, message_id={message_id}, "
                f"guild={self._guild_log(guild)}"
            )
        except Exception as e:
            logger.error(f"Error in job completion callback: {e}", exc_info=True)

    # --- Missed reaction warning ---

    async def _warn_missed_reactions(self, gctx):
        """Warn about reactions that may have been added while the bot was offline.

        Rather than automatically acting on missed reactions (which could be
        surprising), we reply to the original request message so the user knows
        they need to re-react now that the bot is back online.
        """
        scheduler = self.state_manager.scheduler

        # Only check non-terminal jobs that have a bot reply
        actionable_jobs = [
            j for j in scheduler.jobs.values()
            if j.guild_id == gctx.guild_id and j.status not in ('success', 'cancelled')
        ]

        for job in actionable_jobs:
            bot_reply_id = gctx.state.get_bot_reply_id(job.message_id)
            if not bot_reply_id:
                continue

            # Try to find and fetch the bot reply message
            bot_reply_msg = None
            for cid in gctx.channel_ids:
                channel = self.bot.get_channel(int(cid))
                if not channel:
                    continue
                try:
                    bot_reply_msg = await channel.fetch_message(int(bot_reply_id))
                    break
                except discord.NotFound:
                    continue
                except Exception:
                    continue

            if not bot_reply_msg:
                continue

            # Check if any non-bot user reacted with ⏩ or 📅 while offline
            missed_emojis = []
            for reaction in bot_reply_msg.reactions:
                emoji_str = str(reaction.emoji)
                if emoji_str == self.fast_forward_emoji:
                    if reaction.count > 1 or (reaction.count == 1 and not reaction.me):
                        missed_emojis.append(self.fast_forward_emoji)
                elif emoji_str == self.calendar_emoji:
                    if reaction.count > 1 or (reaction.count == 1 and not reaction.me):
                        if not gctx.state.has_calendar_event(job.message_id):
                            missed_emojis.append(self.calendar_emoji)

            if missed_emojis:
                emoji_list = " ".join(missed_emojis)
                logger.info(
                    f"Detected missed reactions {emoji_list} on job {job.id} (msg {job.message_id}, "
                    f"guild={self._guild_log(bot_reply_msg.guild)}, channel={self._channel_log(bot_reply_msg.channel)})"
                )
                try:
                    request_msg = await bot_reply_msg.channel.fetch_message(int(job.message_id))
                    await request_msg.reply(
                        Messages.Discord.MISSED_REACTIONS_WARNING.format(emoji_list)
                    )
                except Exception as e:
                    logger.error(
                        f"Error warning about missed reactions for job {job.id} "
                        f"(guild={self._guild_log(bot_reply_msg.guild)}, channel={self._channel_log(bot_reply_msg.channel)}): {e}"
                    )

    # --- Message listener ---

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the bot is ready"""
        try:
            # Validate configured channel IDs
            invalid_channels = []
            for cid in self._all_channel_ids:
                if not self.bot.get_channel(int(cid)):
                    invalid_channels.append(cid)
            if invalid_channels and self.admin_id:
                try:
                    admin_user = await self.bot.fetch_user(int(self.admin_id))
                    dm = await admin_user.create_dm()
                    listing = "\n".join(f"- {cid}" for cid in invalid_channels)
                    await dm.send(Messages.Discord.INVALID_CHANNELS_WARNING.format(listing))
                except Exception:
                    logger.warning(f"Could not DM admin about invalid channels: {invalid_channels}")

            for gid in self.guild_configs:
                gctx = self.state_manager.get_guild_context(gid)
                if not gctx.channel_ids:
                    continue

                # Load state for this guild
                restored_jobs, pending_count, skipped_jobs = await gctx.load_state()

                # Warn about reactions that may have been added while offline
                await self._warn_missed_reactions(gctx)

                # Save state (persists missed-job status updates and any processed reactions)
                await gctx.save_state()

                # Send restoration message to first channel
                channel = self.bot.get_channel(int(gctx.channel_ids[0]))
                if channel:
                    msg = Messages.Discord.RESTORATION_STATS.format(pending_count, restored_jobs)
                    await channel.send(msg)

                    # Notify about skipped jobs
                    if skipped_jobs:
                        skipped_titles = [f"- {job['title']}" for job in skipped_jobs]
                        skipped_msg = Messages.Discord.SKIPPED_JOBS.format(len(skipped_jobs), "\n".join(skipped_titles))
                        await channel.send(skipped_msg)

        except Exception as e:
            logger.error(f"Error during announcement cog initialization: {e}", exc_info=True)

    @commands.Cog.listener()
    async def on_message(self, message):
        """Process messages in the announcement channels"""
        if message.author.bot:
            return

        # Ignore DMs — OTP handling is in AuthCog
        if isinstance(message.channel, discord.DMChannel):
            return

        # Only process guild messages from monitored channels
        if str(message.channel.id) not in self._all_channel_ids:
            return

        # Determine which guild this channel belongs to
        guild_id = str(message.guild.id)
        gctx = self.state_manager.get_guild_context(guild_id)

        # Check if message mentions the bot and is an announcement request
        if self.bot.user.mentioned_in(message):
            # Check if guild is enabled for new requests
            if not gctx.enabled:
                logger.info(
                    f"Request rejected: guild is disabled "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
                )
                await message.reply(Messages.Discord.GUILD_DISABLED)
                return
            await self._handle_announcement_request(message, gctx)

    async def _handle_announcement_request(self, message, gctx):
        """Handle a new announcement request"""
        try:
            msg_id = str(message.id)

            # Check if this message has already been queued or sent
            if gctx.state.is_queued(msg_id) or gctx.state.is_in_history(msg_id):
                logger.info(
                    f"Request {msg_id} rejected: already booked "
                    f"(queued={gctx.state.is_queued(msg_id)}, history={gctx.state.is_in_history(msg_id)}, "
                    f"guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}, "
                    f"author={self._user_log(message.author)})"
                )
                await message.reply(Messages.Discord.ALREADY_BOOKED)
                return

            # Simply store the message ID and add reaction
            gctx.state.add_pending(msg_id)
            await gctx.save_state()
            await message.add_reaction(self.seen_emoji)
            await message.reply(Messages.Discord.REQUEST_CONFIRMED)
            logger.info(
                f"New announcement request registered: msg_id={msg_id}, "
                f"guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}, "
                f"author={self._user_log(message.author)}"
            )

        except Exception as e:
            logger.error(Messages.Log.ANNOUNCEMENT_REQUEST_ERROR.format(e), exc_info=True)
            await message.reply(Messages.Discord.ERROR_OCCURRED.format(str(e)))

    # --- Dispatchers ---

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Dispatcher: route reaction-add events to the appropriate handler.

        All filtering, guard checks, permission checks, and Discord object
        resolution happen here. Handlers receive only pre-validated objects.
        """
        # Ignore own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Ignore DM reactions (guild_id is None for DMs)
        if payload.guild_id is None:
            return

        # Check if the channel is a monitored channel
        if str(payload.channel_id) not in self._all_channel_ids:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            logger.warning(f"Reaction ignored: channel {payload.channel_id} not in bot cache")
            return

        # Determine guild_id for state lookup
        guild_id = str(payload.guild_id)
        gctx = self.state_manager.get_guild_context(guild_id)

        emoji = str(payload.emoji)
        msg_id = str(payload.message_id)

        logger.info(
            f"Reaction add: emoji={emoji!r} msg={msg_id} "
            f"user={self._user_id_log(payload.user_id)} "
            f"guild={self._guild_log(channel.guild)} channel={self._channel_log(channel)}"
        )

        # Case 1: Approval of pending request (Reaction to User's message)
        if emoji == self.approval_emoji and gctx.state.is_pending(msg_id):
            member = await self._fetch_member_safe(channel, payload.user_id)
            if not self._is_admin(member, gctx.admin_role_id):
                logger.info(
                    f"Approval ignored: user {self._user_log(member)} is not admin "
                    f"(role_id={gctx.admin_role_id}, guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            if gctx.state.is_in_history(msg_id):
                logger.info(
                    f"Approval ignored: msg {msg_id} is in history (already completed, "
                    f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            # Check queued status, but verify against actual job state to handle
            # stale queued_announcements (e.g. after !cancel + restart)
            if gctx.state.is_queued(msg_id):
                job = self.state_manager.scheduler.get_job_by_message_id(msg_id)
                if job and job.status not in ('cancelled', 'success', 'failed'):
                    logger.info(
                        f"Approval ignored: msg {msg_id} has active job {job.id} (status={job.status}, "
                        f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
                    return
                # Job is terminal or missing — stale queued flag, clear it and re-approve
                logger.info(
                    f"Approval: clearing stale queued flag for msg {msg_id} "
                    f"(job={'None' if not job else job.status}, "
                    f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                gctx.state.queued_announcements.discard(msg_id)

            logger.info(
                f"Approval accepted: processing msg {msg_id} by admin {self._user_log(member)} "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            message = await channel.fetch_message(payload.message_id)
            if message:
                await self._process_approved_announcement(message, gctx)
            return

        # Case 2: Immediate posting of queued announcement (Reaction to Bot's message)
        if emoji == self.fast_forward_emoji:
            request_msg_id = gctx.state.find_request_id_by_bot_message(msg_id)
            if not request_msg_id:
                logger.info(
                    f"Fast-forward ignored: no request found for bot msg {msg_id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            job = self.state_manager.scheduler.get_job_by_message_id(request_msg_id)
            if not job:
                logger.info(
                    f"Fast-forward blocked: no job found for msg {request_msg_id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return
            if job.status not in ('pending', 'missed', 'failed'):
                logger.info(
                    f"Fast-forward blocked: job {job.id} has status={job.status} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            try:
                request_message = await channel.fetch_message(int(request_msg_id))
                member = await self._fetch_member_safe(channel, payload.user_id)
                is_admin = self._is_admin(member, gctx.admin_role_id)
                is_author = request_message.author.id == payload.user_id
                if is_admin or is_author:
                    logger.info(
                        f"Fast-forward authorized: job {job.id} by user {self._user_log(member)} "
                        f"(admin={is_admin}, author={is_author}, "
                        f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
                    await self._process_immediate_post(request_msg_id, payload.channel_id, payload.message_id, gctx)
                else:
                    logger.info(
                        f"Fast-forward denied: user {self._user_log(member)} "
                        f"(admin={is_admin}, author={is_author}, msg_author={self._user_log(request_message.author)}, "
                        f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
            except Exception as e:
                logger.error(
                    f"Error handling fast-forward for job {job.id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)}): {e}",
                    exc_info=True
                )
            return

        # Case 3: Create Calendar Event (Reaction to Bot's message)
        if emoji == self.calendar_emoji:
            request_msg_id = gctx.state.find_request_id_by_bot_message(msg_id)
            if not request_msg_id:
                logger.info(
                    f"Calendar ignored: no request found for bot msg {msg_id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            if gctx.state.has_calendar_event(request_msg_id):
                logger.info(
                    f"Calendar ignored: event already exists for msg {request_msg_id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            job = self.state_manager.scheduler.get_job_by_message_id(request_msg_id)
            if not job:
                logger.info(
                    f"Calendar blocked: no job found for msg {request_msg_id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return
            if job.status == 'cancelled':
                logger.info(
                    f"Calendar blocked: job {job.id} is cancelled "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            try:
                request_message = await channel.fetch_message(int(request_msg_id))
                member = await self._fetch_member_safe(channel, payload.user_id)
                is_admin = self._is_admin(member, gctx.admin_role_id)
                is_author = request_message.author.id == payload.user_id
                if is_admin or is_author:
                    logger.info(
                        f"Calendar authorized: job {job.id} by user {self._user_log(member)} "
                        f"(admin={is_admin}, author={is_author}, "
                        f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
                    await self._process_calendar_event_creation(request_message, channel, gctx)
                else:
                    logger.info(
                        f"Calendar denied: user {self._user_log(member)} "
                        f"(admin={is_admin}, author={is_author}, msg_author={self._user_log(request_message.author)}, "
                        f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
            except Exception as e:
                logger.error(
                    f"Error handling calendar creation for job {job.id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)}): {e}",
                    exc_info=True
                )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        """Dispatcher: cancel a scheduled announcement when its request message is deleted."""
        if payload.guild_id is None:
            return

        if str(payload.channel_id) not in self._all_channel_ids:
            return

        msg_id = str(payload.message_id)
        guild_id = str(payload.guild_id)
        gctx = self.state_manager.get_guild_context(guild_id)

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            logger.warning(f"Message delete ignored: channel {payload.channel_id} not in bot cache")
            return

        if gctx.state.is_queued(msg_id):
            logger.info(
                f"Queued announcement {msg_id} cancelled due to message deletion "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            await self._cancel_announcement_on_delete(msg_id, channel, gctx)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Dispatcher: route reaction-remove events to the appropriate handler.

        All filtering, guard checks, permission checks, and Discord object
        resolution happen here. Handlers receive only pre-validated objects.
        """
        # Ignore own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Ignore DM reactions (guild_id is None for DMs)
        if payload.guild_id is None:
            return

        # Check if the channel is a monitored channel
        if str(payload.channel_id) not in self._all_channel_ids:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            logger.warning(f"Reaction remove ignored: channel {payload.channel_id} not in bot cache")
            return

        guild_id = str(payload.guild_id)
        gctx = self.state_manager.get_guild_context(guild_id)
        emoji = str(payload.emoji)
        msg_id = str(payload.message_id)

        logger.info(
            f"Reaction remove: emoji={emoji!r} msg={msg_id} "
            f"user={self._user_id_log(payload.user_id)} "
            f"guild={self._guild_log(channel.guild)} channel={self._channel_log(channel)}"
        )

        # Case: Removal of Calendar reaction
        if emoji == self.calendar_emoji:
            request_msg_id = gctx.state.find_request_id_by_bot_message(msg_id)
            if not request_msg_id or not gctx.state.has_calendar_event(request_msg_id):
                logger.info(
                    f"Calendar remove ignored: no request or no calendar event "
                    f"(request_msg_id={request_msg_id}, "
                    f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            try:
                member = await channel.guild.fetch_member(payload.user_id)
                request_message = await channel.fetch_message(int(request_msg_id))
                is_admin = self._is_admin(member, gctx.admin_role_id)
                is_author = request_message.author.id == payload.user_id
                if not (is_admin or is_author):
                    logger.info(
                        f"Calendar remove denied: user {self._user_log(member)} "
                        f"(admin={is_admin}, author={is_author}, "
                        f"guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
                    return

                logger.info(
                    f"Calendar remove authorized: msg {request_msg_id} by user {self._user_log(member)} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                await self._remove_calendar_event(request_msg_id, channel, gctx)
            except Exception as e:
                logger.error(
                    f"Error removing calendar event for msg {request_msg_id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)}): {e}",
                    exc_info=True
                )

        # Case: Removal of Approval reaction (on User's message)
        elif emoji == self.approval_emoji:
            if not gctx.state.is_queued(msg_id):
                return

            message = await channel.fetch_message(payload.message_id)
            if not message:
                return

            # Check if there are any approval reactions left
            approval_reactions = [r for r in message.reactions if str(r.emoji) == self.approval_emoji]
            if approval_reactions and approval_reactions[0].count > 0:
                logger.info(
                    f"Approval remove: still {approval_reactions[0].count} approval reaction(s) on msg {msg_id}, no action "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                return

            logger.info(
                f"All approval reactions removed from msg {msg_id}, cancelling announcement "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            await self._cancel_approved_announcement(msg_id, message, channel, gctx)

    # --- Log formatting helpers ---

    def _guild_log(self, guild) -> str:
        """Format guild for logging: 'id/name'."""
        if guild is None:
            return "unknown"
        return f"{guild.id}/{guild.name!r}"

    def _channel_log(self, channel) -> str:
        """Format channel for logging: 'id/#name'."""
        if channel is None:
            return "unknown"
        return f"{channel.id}/#{channel.name}"

    def _user_log(self, user_or_member) -> str:
        """Format a User or Member for logging: 'id/name'."""
        if user_or_member is None:
            return "unknown"
        return f"{user_or_member.id}/{user_or_member.name!r}"

    def _user_id_log(self, user_id) -> str:
        """Format a user ID for logging, resolving the name from cache when available."""
        if user_id is None:
            return "unknown"
        user = self.bot.get_user(int(user_id))
        if user:
            return f"{user_id}/{user.name!r}"
        return str(user_id)

    # --- Permission helpers ---

    async def _fetch_member_safe(self, channel, user_id):
        """Fetch a guild member, returning None on failure."""
        try:
            return await channel.guild.fetch_member(user_id)
        except Exception as e:
            logger.warning(
                f"Failed to fetch member {user_id} "
                f"(guild={self._guild_log(channel.guild)}): {e}"
            )
            return None

    def _is_admin(self, member, admin_role_id) -> bool:
        """Check if a member has the admin role."""
        if not member or admin_role_id is None:
            return False
        return admin_role_id in [str(role.id) for role in member.roles]

    # --- Handlers (pure business logic — no filtering, guards, or permission checks) ---

    async def _remove_calendar_event(self, request_msg_id, channel, gctx):
        """Remove a VRChat calendar event and persist the state change."""
        calendar_event_id = gctx.state.remove_calendar_event(request_msg_id)
        logger.info(
            f"Deleting calendar event {calendar_event_id} for msg {request_msg_id} "
            f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
        )
        result = await self.vrchat_api.delete_group_calendar_event(gctx.group_id, calendar_event_id)
        await gctx.save_state()
        if result.success:
            logger.info(
                f"Calendar event {calendar_event_id} deleted successfully "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            await channel.send(Messages.Discord.CALENDAR_DELETED)
        else:
            logger.error(
                f"Calendar event deletion failed "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)}): {result.error}"
            )
            await channel.send(result.error)

    async def _cancel_announcement_on_delete(self, msg_id, channel, gctx):
        """Cancel an approved announcement when its original request message was deleted."""
        bot_reply_id = gctx.state.get_bot_reply_id(msg_id)
        if bot_reply_id:
            try:
                scheduled_msg = await channel.fetch_message(bot_reply_id)
                if scheduled_msg:
                    await scheduled_msg.delete()
                    logger.info(
                        f"Deleted bot reply message {bot_reply_id} for cancelled announcement {msg_id} "
                        f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
            except Exception as e:
                logger.error(Messages.Log.SCHEDULED_MSG_DELETE_ERROR.format(e))

        success, deleted_calendar = await gctx.cancel_announcement_detailed(msg_id)
        if not success:
            logger.warning(
                f"Cancel failed for msg {msg_id}: job not found in scheduler "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            return

        logger.info(
            f"Announcement cancelled (message deleted): msg={msg_id}, calendar_deleted={deleted_calendar} "
            f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
        )

        if deleted_calendar:
            await channel.send(Messages.Discord.CALENDAR_DELETED_WITH_CANCEL)

        await channel.send(Messages.Discord.BOOKING_CANCELLED)

    async def _cancel_approved_announcement(self, msg_id, message, channel, gctx):
        """Cancel an approved announcement: delete bot reply, cancel job, notify."""
        # Delete the bot reply message before cancelling
        bot_reply_id = gctx.state.get_bot_reply_id(msg_id)
        if bot_reply_id:
            try:
                scheduled_msg = await channel.fetch_message(bot_reply_id)
                if scheduled_msg:
                    await scheduled_msg.delete()
                    logger.info(
                        f"Deleted bot reply message {bot_reply_id} for cancelled announcement {msg_id} "
                        f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                    )
            except Exception as e:
                logger.error(Messages.Log.SCHEDULED_MSG_DELETE_ERROR.format(e))

        # Cancel via GuildContext (scheduler + state + calendar + persist)
        success, deleted_calendar = await gctx.cancel_announcement_detailed(msg_id)
        if not success:
            logger.warning(
                f"Cancel failed for msg {msg_id}: job not found in scheduler "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            return

        logger.info(
            f"Announcement cancelled: msg={msg_id}, calendar_deleted={deleted_calendar} "
            f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
        )

        if deleted_calendar:
            await channel.send(Messages.Discord.CALENDAR_DELETED_WITH_CANCEL)

        await message.reply(Messages.Discord.BOOKING_CANCELLED)

    async def _process_calendar_event_creation(self, message, channel, gctx):
        """Process the creation of a VRChat calendar event"""
        try:
            job = self.state_manager.scheduler.get_job_by_message_id(str(message.id))
            if not job:
                logger.warning(
                    Messages.Log.CALENDAR_EVENT_CREATE_WARNING.format(message.id) +
                    f" (guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
                )
                return

            # Guard: allow calendar creation for any non-cancelled job.
            # Calendar events are independent of posting status.
            if job.status == 'cancelled':
                logger.info(
                    f"Calendar creation skipped: job {job.id} is cancelled "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
                )
                return

            # Retrieve event details from job
            title = job.event_title or job.title
            content = job.content
            start_at = job.event_start_timestamp
            end_at = job.event_end_timestamp

            if not start_at or not end_at:
                logger.info(
                    f"Calendar creation skipped: missing time (start={start_at}, end={end_at}) for job {job.id} "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
                )
                await channel.send(Messages.Discord.CALENDAR_MISSING_TIME)
                return

            # Call VRChat API
            logger.info(
                f"Creating calendar event: title={title!r}, start={start_at}, end={end_at}, group={gctx.group_id} "
                f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
            )
            result = await self.vrchat_api.create_group_calendar_event(gctx.group_id, title, content, start_at, end_at)

            if result.success:
                calendar_id = result.data['event_id']

                # Store event ID
                gctx.state.set_calendar_event(str(message.id), calendar_id)
                await gctx.save_state()

                # Send success message
                calendar_url = f"https://vrchat.com/home/group/{gctx.group_id}/calendar/{calendar_id}"
                logger.info(
                    f"Calendar event created: {calendar_id} for msg {message.id} "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
                )
                await channel.send(Messages.Discord.CALENDAR_CREATED.format(calendar_url))
            else:
                error_msg = result.error or 'Unknown error'
                logger.error(
                    f"Calendar event creation failed "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}): {error_msg}"
                )
                await channel.send(Messages.Discord.CALENDAR_CREATE_FAIL.format(error_msg))

        except Exception as e:
            logger.error(
                f"Exception creating calendar event for msg {message.id} "
                f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}): {e}",
                exc_info=True
            )
            await channel.send(Messages.Discord.ERROR_OCCURRED.format(str(e)))

    async def _process_immediate_post(self, request_msg_id, channel_id, processing_msg_id, gctx):
        """Process an immediate post request (fast-forward)"""
        scheduler = self.state_manager.scheduler

        # Get job details — allow reposting for pending, missed, or failed jobs
        job = scheduler.get_job_by_message_id(request_msg_id)
        if not job or job.status not in ('pending', 'missed', 'failed'):
            guild = self.bot.get_guild(int(gctx.guild_id)) if gctx.guild_id else None
            logger.warning(
                f"Immediate post aborted: job not actionable "
                f"(job={job}, status={getattr(job, 'status', None)}, "
                f"guild={self._guild_log(guild)}, channel_id={channel_id})"
            )
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            guild = self.bot.get_guild(int(gctx.guild_id)) if gctx.guild_id else None
            logger.warning(
                f"Immediate post aborted: channel {channel_id} not in cache "
                f"(guild={self._guild_log(guild)})"
            )
            return

        processing_msg = await channel.fetch_message(processing_msg_id)

        # Remove from APScheduler if present (no-op for missed jobs)
        scheduler.unschedule_job(job.id)

        # Post immediately
        try:
            logger.info(
                f"Immediate posting: job {job.id}, title={job.title!r}, group={gctx.group_id} "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
            )
            result = await self.vrchat_api.post_announcement(gctx.group_id, job.title, job.content)

            if result.success:
                # Mark the job as successfully completed
                scheduler.mark_job_success(job.id)

                # Update embed to show success
                embed = processing_msg.embeds[0]
                embed.color = discord.Color.gold()
                embed.title = Messages.Discord.IMMEDIATE_POST_SUCCESS
                embed.description = Messages.Discord.IMMEDIATE_POST_EXECUTED

                await processing_msg.edit(embed=embed)

                # Mark completed in state
                gctx.state.mark_completed(str(request_msg_id))

                await gctx.save_state()
                logger.info(
                    f"Immediate post succeeded: job {job.id} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
            else:
                # Mark the job as failed
                scheduler.mark_job_failed(job.id)
                await gctx.save_state()
                logger.error(
                    f"Immediate post failed: job {job.id}, error={result.error} "
                    f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)})"
                )
                await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(result.error))

        except Exception as e:
            logger.error(
                f"Exception in immediate post for job {job.id} "
                f"(guild={self._guild_log(channel.guild)}, channel={self._channel_log(channel)}): {e}",
                exc_info=True
            )
            # Mark job as failed so it's not silently lost
            scheduler.mark_job_failed(job.id)
            await gctx.save_state()
            await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(str(e)))

    def _is_timestamp_too_old(self, timestamp) -> bool:
        """Check if a timestamp is more than misfire_grace_time seconds in the past."""
        return timestamp < time.time() - self.state_manager.scheduler.misfire_grace_time

    def _build_booking_embed(self, result, job_id) -> discord.Embed:
        """Build the confirmation embed for a booked announcement."""
        embed = discord.Embed(
            title=Messages.Discord.BOOKING_COMPLETED_TITLE,
            color=discord.Color.green()
        )
        embed.add_field(name="告知予定時刻", value=f"<t:{int(result.announcement_timestamp)}:F>", inline=False)
        embed.add_field(name="イベント開始", value=f"<t:{int(result.event_start_timestamp)}:F>", inline=False)
        embed.add_field(name="イベント終了", value=f"<t:{int(result.event_end_timestamp)}:F>", inline=False)

        embed.add_field(name=Messages.Discord.FIELD_TITLE, value=result.title, inline=False)

        content = result.content
        if len(content) > 1024:
            content = content[:1021] + "..."
        embed.add_field(name=Messages.Discord.FIELD_CONTENT, value=content, inline=False)
        embed.add_field(name=Messages.Discord.FIELD_JOB_ID, value=job_id, inline=False)
        embed.add_field(name=Messages.Discord.FIELD_HINTS, value=Messages.Discord.FIELD_HINTS_CONTENTS, inline=False)

        return embed

    async def _process_approved_announcement(self, message, gctx):
        """Process an approved announcement request"""
        try:
            # Send processing message
            processing_msg = await message.reply(Messages.Discord.PROCESSING)
            logger.info(
                f"Processing approved announcement: msg={message.id}, "
                f"guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}, "
                f"author={self._user_log(message.author)}"
            )

            # Process with AI using the current message content
            result = await self.ai_processor.process_announcement(message.content)

            if not result.success:
                logger.error(
                    f"AI processing failed for msg {message.id} "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}): {result.error}"
                )
                await processing_msg.edit(content=Messages.Discord.ERROR_OCCURRED.format(result.error))
                return

            # Check if timestamp is too far in the past
            if self._is_timestamp_too_old(result.timestamp):
                logger.warning(
                    f"Announcement timestamp too old for msg {message.id}: {result.timestamp} "
                    f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)})"
                )
                role_mention = f"<@&{gctx.admin_role_id}>" if gctx.admin_role_id else ""
                author_mention = message.author.mention
                mentions = f"{role_mention} {author_mention}".strip()
                await processing_msg.edit(content=Messages.Discord.PAST_TIME_WARNING.format(mentions=mentions))
                return

            # Schedule the announcement
            job_id = await self.state_manager.scheduler.schedule_announcement(
                result.announcement_timestamp,
                result.title,
                result.content,
                str(message.id),
                guild_id=gctx.guild_id,
                group_id=gctx.group_id,
                event_start_timestamp=result.event_start_timestamp,
                event_end_timestamp=result.event_end_timestamp,
                event_title=result.event_title,
            )

            # Build and send confirmation embed
            embed = self._build_booking_embed(result, job_id)
            await processing_msg.edit(content=None, embed=embed)

            # Update state
            gctx.state.mark_queued(str(message.id), str(processing_msg.id))

            # Add calendar and fast-forward reactions for quick access
            await processing_msg.add_reaction(self.calendar_emoji)
            await processing_msg.add_reaction(self.fast_forward_emoji)

            await gctx.save_state()
            logger.info(
                f"Announcement booked: msg={message.id}, job={job_id}, bot_reply={processing_msg.id} "
                f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}, "
                f"author={self._user_log(message.author)})"
            )

        except Exception as e:
            logger.error(
                f"Error processing approved announcement for msg {message.id} "
                f"(guild={self._guild_log(message.guild)}, channel={self._channel_log(message.channel)}): {e}",
                exc_info=True
            )
            if 'processing_msg' in locals():
                await processing_msg.edit(content=Messages.Discord.PROCESSING_ERROR.format(str(e)))
            else:
                await message.reply(Messages.Discord.PROCESSING_ERROR.format(str(e)))
