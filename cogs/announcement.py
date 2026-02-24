import logging
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import uuid
import time
from utils.messages import Messages
from utils.announcement_state import AnnouncementState

logger = logging.getLogger(__name__)

class AnnouncementCog(commands.Cog):
    def __init__(self, bot, config, ai_processor, scheduler, guild_persistences, vrchat_api):
        self.bot = bot
        self.config = config
        self.ai_processor = ai_processor
        self.scheduler = scheduler
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

        # Per-guild announcement state (lazily populated in on_ready)
        self.guild_states = {}  # guild_id -> AnnouncementState

        # Per-guild persistences passed from bot
        self.guild_persistences = guild_persistences  # guild_id -> Persistence

        # Global emoji config (shared across guilds)
        self.seen_emoji = config['discord'].get('seen_reaction_emoji', "👀")
        self.approval_emoji = config['discord'].get('approval_reaction_emoji', "👍")
        self.fast_forward_emoji = config['discord'].get('fast_forward_emoji', "⏩")
        self.calendar_emoji = config['discord'].get('calendar_emoji', "📅")

        # Admin user ID (receives OTP DMs and config warnings)
        self.admin_id = config['discord'].get('admin_id')

        self.otp_requests = {}  # request_id -> {'future': Future, 'message_id': int}

        # Set up OTP callback for VRChat API
        self.vrchat_api.set_otp_callback(self._request_otp)

        # Set up job completion callback
        self.scheduler.set_on_job_completion(self._on_job_complete)

        # Load state will be called in on_ready

    # --- Guild config helpers ---

    def _get_guild_config(self, guild_id):
        """Return the config for a guild, or None if not configured."""
        return self.guild_configs.get(guild_id)

    def _get_state(self, guild_id):
        """Return (or lazily create) the AnnouncementState for a guild."""
        if guild_id not in self.guild_states:
            self.guild_states[guild_id] = AnnouncementState()
        return self.guild_states[guild_id]

    def _get_persistence(self, guild_id):
        """Return the Persistence for a guild."""
        return self.guild_persistences.get(guild_id)

    def _is_guild_enabled(self, guild_id):
        """Return True if the guild is enabled for new announcement requests."""
        guild_conf = self._get_guild_config(guild_id)
        if guild_conf is None:
            return False
        return guild_conf.get('enabled', True)

    def _get_admin_role_id(self, guild_id):
        """Return the admin_role_id for a guild."""
        guild_conf = self._get_guild_config(guild_id)
        if guild_conf is None:
            return None
        return guild_conf.get('admin_role_id')

    # --- State persistence ---

    async def save_state(self, guild_id=None):
        """Save the current state to Firestore for the given guild.

        If guild_id is None, saves all guilds.
        """
        guilds_to_save = [guild_id] if guild_id is not None else list(self.guild_states.keys())
        for gid in guilds_to_save:
            state = self._get_state(gid)
            persistence = self._get_persistence(gid)
            if persistence:
                await state.save(persistence)
                await persistence.save_data('jobs', self.scheduler.get_jobs_data(guild_id=gid))

    async def load_state(self, guild_id):
        """Load state from Firestore for a specific guild."""
        state = self._get_state(guild_id)
        persistence = self._get_persistence(guild_id)
        if not persistence:
            return 0, 0, []

        await state.load(persistence)

        jobs_data = await persistence.load_data('jobs', [])
        restored_count, skipped_jobs = self.scheduler.restore_jobs(
            jobs_data,
            guild_id=guild_id
        )

        # Rebuild queued_announcements from restored jobs
        state.queued_announcements = set()
        for job in self.scheduler.list_jobs(guild_id=guild_id):
            if job.message_id:
                state.queued_announcements.add(job.message_id)

        return restored_count, len(state.pending_requests), skipped_jobs

    # --- Callbacks ---

    async def _on_job_complete(self, job_data):
        """Callback for when a job completes (success or failure)"""
        try:
            message_id = job_data.get('message_id')
            status = job_data.get('status', 'success')
            guild_id = job_data['guild_id']

            if message_id and status == 'success':
                state = self._get_state(guild_id)
                state.mark_completed(message_id)

            # Save state for both success and failure
            await self.save_state(guild_id)
            logger.info(f"Job {status} and state saved: {message_id}")
        except Exception as e:
            logger.error(f"Error in job completion callback: {e}")

    # --- OTP handling ---

    async def _request_otp(self, otp_type):
        """Request OTP from the configured admin user via DM"""
        if not self.admin_id:
            logger.error(Messages.Log.OTP_DM_USER_NOT_CONFIGURED)
            return None

        try:
            user = await self.bot.fetch_user(int(self.admin_id))
        except Exception:
            logger.error(Messages.Log.OTP_DM_USER_NOT_FOUND)
            return None

        # Create a unique request ID
        request_id = str(uuid.uuid4())

        # Create a future to wait for the response
        future = asyncio.Future()

        # Open DM channel and send request
        dm_channel = await user.create_dm()
        message = await dm_channel.send(Messages.Discord.OTP_REQUEST_DM.format(otp_type=otp_type))

        # Store request with the sent message ID for reply-to verification
        self.otp_requests[request_id] = {'future': future, 'message_id': message.id}

        try:
            # Wait for response with timeout
            otp = await asyncio.wait_for(future, timeout=300)  # 5 minute timeout
            return otp
        except asyncio.TimeoutError:
            await message.edit(content=Messages.Discord.OTP_TIMEOUT_DM)
            return None
        finally:
            # Clean up
            if request_id in self.otp_requests:
                del self.otp_requests[request_id]

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

            for gid, guild_conf in self.guild_configs.items():
                channel_ids = guild_conf.get('channel_ids', [])
                if not channel_ids:
                    continue

                # Load state for this guild
                restored_jobs, pending_count, skipped_jobs = await self.load_state(gid)

                # Immediately save state to clean up any skipped jobs
                await self.save_state(gid)

                # Send restoration message to first channel
                channel = self.bot.get_channel(int(channel_ids[0]))
                if channel:
                    msg = Messages.Discord.RESTORATION_STATS.format(pending_count, restored_jobs)
                    await channel.send(msg)

                    # Notify about skipped jobs
                    if skipped_jobs:
                        skipped_titles = [f"- {job['title']}" for job in skipped_jobs]
                        skipped_msg = Messages.Discord.SKIPPED_JOBS.format(len(skipped_jobs), "\n".join(skipped_titles))
                        await channel.send(skipped_msg)

        except Exception as e:
            logger.error(f"Error during announcement cog initialization: {e}")

    @commands.Cog.listener()
    async def on_message(self, message):
        """Process messages in the announcement channels or DMs for OTP"""
        if message.author.bot:
            return

        # Handle DM messages for OTP responses (reply-to only)
        if isinstance(message.channel, discord.DMChannel):
            if self.admin_id and str(message.author.id) == self.admin_id:
                if message.reference and message.reference.message_id:
                    for request_id, request in list(self.otp_requests.items()):
                        if not request['future'].done() and message.reference.message_id == request['message_id']:
                            request['future'].set_result(message.content.strip())
                            return
            return  # Ignore all other DMs

        # Only process guild messages from monitored channels
        if str(message.channel.id) not in self._all_channel_ids:
            return

        # Determine which guild this channel belongs to
        guild_id = str(message.guild.id)

        # Check if message mentions the bot and is an announcement request
        if self.bot.user.mentioned_in(message):
            # Check if guild is enabled for new requests
            if not self._is_guild_enabled(guild_id):
                await message.reply(Messages.Discord.GUILD_DISABLED)
                return
            await self._handle_announcement_request(message)

    async def _handle_announcement_request(self, message):
        """Handle a new announcement request"""
        try:
            guild_id = str(message.guild.id)
            msg_id = str(message.id)
            state = self._get_state(guild_id)

            # Check if this message has already been queued or sent
            if state.is_queued(msg_id) or state.is_in_history(msg_id):
                await message.reply(Messages.Discord.ALREADY_BOOKED)
                return

            # Simply store the message ID and add reaction
            state.add_pending(msg_id)
            await self.save_state(guild_id)
            await message.add_reaction(self.seen_emoji)
            await message.reply(Messages.Discord.REQUEST_CONFIRMED)

        except Exception as e:
            logger.error(Messages.Log.ANNOUNCEMENT_REQUEST_ERROR.format(e))
            await message.reply(Messages.Discord.ERROR_OCCURRED.format(str(e)))

    # --- Reaction handlers ---

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Process reactions to announcement requests"""
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
            return

        # Determine guild_id for state lookup
        guild_id = str(payload.guild_id)

        emoji = str(payload.emoji)
        msg_id = str(payload.message_id)
        state = self._get_state(guild_id)

        # Case 1: Approval of pending request (Reaction to User's message)
        if emoji == self.approval_emoji and state.is_pending(msg_id):
            member = await self._fetch_member_safe(channel, payload.user_id)
            admin_role_id = self._get_admin_role_id(guild_id)
            if not self._is_admin(member, admin_role_id):
                return

            if state.is_queued(msg_id) or state.is_in_history(msg_id):
                return

            message = await channel.fetch_message(payload.message_id)
            if message:
                await self._process_approved_announcement(message)
            return

        # Case 2: Immediate posting of queued announcement (Reaction to Bot's message)
        if emoji == self.fast_forward_emoji:
            await self._handle_fast_forward_reaction(channel, payload, guild_id)
            return

        # Case 3: Create Calendar Event (Reaction to Bot's message)
        if emoji == self.calendar_emoji:
            await self._handle_calendar_reaction(channel, payload, guild_id)

    async def _handle_fast_forward_reaction(self, channel, payload, guild_id):
        """Handle fast-forward reaction to immediately post a queued announcement"""
        state = self._get_state(guild_id)
        request_msg_id = state.find_request_id_by_bot_message(str(payload.message_id))
        if not request_msg_id:
            return

        try:
            request_message = await channel.fetch_message(int(request_msg_id))
            member = await self._fetch_member_safe(channel, payload.user_id)
            admin_role_id = self._get_admin_role_id(guild_id)

            if self._is_admin(member, admin_role_id) or request_message.author.id == payload.user_id:
                await self._process_immediate_post(request_msg_id, payload.channel_id, payload.message_id, guild_id)
        except Exception as e:
            logger.error(f"Error handling immediate post request: {e}")

    async def _handle_calendar_reaction(self, channel, payload, guild_id):
        """Handle calendar reaction to create a VRChat calendar event"""
        state = self._get_state(guild_id)
        request_msg_id = state.find_request_id_by_bot_message(str(payload.message_id))
        if not request_msg_id:
            return

        # Check if event already exists
        if state.has_calendar_event(request_msg_id):
            return

        try:
            request_message = await channel.fetch_message(int(request_msg_id))
            member = await self._fetch_member_safe(channel, payload.user_id)
            admin_role_id = self._get_admin_role_id(guild_id)

            if self._is_admin(member, admin_role_id) or request_message.author.id == payload.user_id:
                await self._process_calendar_event_creation(request_message, channel, guild_id)
        except Exception as e:
            logger.error(f"Error handling calendar event creation: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Handle reaction removals"""
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
            return

        guild_id = str(payload.guild_id)
        emoji = str(payload.emoji)

        # Case: Removal of Calendar reaction
        if emoji == self.calendar_emoji:
            await self._handle_calendar_reaction_remove(channel, payload, guild_id)

        # Case: Removal of Approval reaction (on User's message)
        elif emoji == self.approval_emoji:
            await self._handle_approval_reaction_remove(channel, payload, guild_id)

    async def _handle_calendar_reaction_remove(self, channel, payload, guild_id):
        """Handle removal of calendar reaction to delete the VRChat calendar event"""
        state = self._get_state(guild_id)
        request_msg_id = state.find_request_id_by_bot_message(str(payload.message_id))
        if not request_msg_id or not state.has_calendar_event(request_msg_id):
            return

        try:
            member = await channel.guild.fetch_member(payload.user_id)
            request_message = await channel.fetch_message(int(request_msg_id))
            admin_role_id = self._get_admin_role_id(guild_id)

            if not (self._is_admin(member, admin_role_id) or request_message.author.id == payload.user_id):
                return

            calendar_event_id = state.remove_calendar_event(request_msg_id)
            result = await self.vrchat_api.delete_group_calendar_event(calendar_event_id)
            await self.save_state(guild_id)
            if result.success:
                await channel.send(Messages.Discord.CALENDAR_DELETED)
            else:
                await channel.send(result.error)
        except Exception as e:
            logger.error(Messages.Log.CALENDAR_EVENT_DELETE_ERROR.format(e))

    async def _handle_approval_reaction_remove(self, channel, payload, guild_id):
        """Handle removal of approval reaction to cancel a queued announcement"""
        state = self._get_state(guild_id)
        msg_id = str(payload.message_id)
        if not state.is_queued(msg_id):
            return

        message = await channel.fetch_message(payload.message_id)
        if not message:
            return

        # Check if there are any approval reactions left
        approval_reactions = [r for r in message.reactions if str(r.emoji) == self.approval_emoji]
        if approval_reactions and approval_reactions[0].count > 0:
            return

        # Cancel the job and delete the scheduled message
        if not self.scheduler.cancel_job_by_message_id(msg_id):
            return

        bot_reply_id = state.get_bot_reply_id(msg_id)
        if bot_reply_id:
            try:
                scheduled_msg = await channel.fetch_message(bot_reply_id)
                if scheduled_msg:
                    await scheduled_msg.delete()
            except Exception as e:
                logger.error(Messages.Log.SCHEDULED_MSG_DELETE_ERROR.format(e))

        # Also delete calendar event if exists
        calendar_event_id = state.cancel(msg_id)
        if calendar_event_id:
            await self.vrchat_api.delete_group_calendar_event(calendar_event_id)
            await channel.send(Messages.Discord.CALENDAR_DELETED_WITH_CANCEL)

        await self.save_state(guild_id)
        await message.reply(Messages.Discord.BOOKING_CANCELLED)

    # --- Permission helpers ---

    async def _fetch_member_safe(self, channel, user_id):
        """Fetch a guild member, returning None on failure."""
        try:
            return await channel.guild.fetch_member(user_id)
        except Exception:
            return None

    def _is_admin(self, member, admin_role_id) -> bool:
        """Check if a member has the admin role."""
        if not member or admin_role_id is None:
            return False
        return admin_role_id in [str(role.id) for role in member.roles]

    # --- Business logic ---

    async def _process_calendar_event_creation(self, message, channel, guild_id):
        """Process the creation of a VRChat calendar event"""
        try:
            job = self.scheduler.get_job_by_message_id(str(message.id))
            if not job:
                logger.warning(Messages.Log.CALENDAR_EVENT_CREATE_WARNING.format(message.id))
                return

            # Retrieve event details from job
            title = job.event_title or job.title
            content = job.content
            start_at = job.event_start_timestamp
            end_at = job.event_end_timestamp

            if not start_at or not end_at:
                await channel.send(Messages.Discord.CALENDAR_MISSING_TIME)
                return

            # Call VRChat API
            result = await self.vrchat_api.create_group_calendar_event(title, content, start_at, end_at)

            if result.success:
                calendar_id = result.data['event_id']
                group_id = self.vrchat_api.group_id

                # Store event ID
                state = self._get_state(guild_id)
                state.set_calendar_event(str(message.id), calendar_id)
                await self.save_state(guild_id)

                # Send success message
                calendar_url = f"https://vrchat.com/home/group/{group_id}/calendar/{calendar_id}"
                await channel.send(Messages.Discord.CALENDAR_CREATED.format(calendar_url))
            else:
                error_msg = result.error or 'Unknown error'
                await channel.send(Messages.Discord.CALENDAR_CREATE_FAIL.format(error_msg))
                logger.error(Messages.Log.CALENDAR_EVENT_CREATE_FAIL.format(error_msg))

        except Exception as e:
            logger.error(Messages.Log.CALENDAR_EVENT_CREATE_EXCEPTION.format(e))
            await channel.send(Messages.Discord.ERROR_OCCURRED.format(str(e)))

    async def _process_immediate_post(self, request_msg_id, channel_id, processing_msg_id, guild_id):
        """Process an immediate post request"""
        # Get job details
        job = self.scheduler.get_job_by_message_id(request_msg_id)
        if not job:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        processing_msg = await channel.fetch_message(processing_msg_id)

        # Cancel the scheduled job
        self.scheduler.cancel_job(job.id)

        # Post immediately
        try:
            result = await self.vrchat_api.post_announcement(job.title, job.content)

            if result.success:
                # Update embed to show success
                embed = processing_msg.embeds[0]
                embed.color = discord.Color.gold()
                embed.title = Messages.Discord.IMMEDIATE_POST_SUCCESS
                embed.description = Messages.Discord.IMMEDIATE_POST_EXECUTED

                await processing_msg.edit(embed=embed)

                # Mark completed in state
                state = self._get_state(guild_id)
                state.mark_completed(str(request_msg_id))
                # Keep pending_requests entry as it maps to the processing msg which still exists
                state.pending_requests[str(request_msg_id)] = str(processing_msg_id)

                await self.save_state(guild_id)
            else:
                # Save state even on failure - the job was already cancelled
                await self.save_state(guild_id)
                await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(result.error))

        except Exception as e:
            logger.error(f"Error in immediate post: {e}")
            # Save state even on exception - the job was already cancelled
            await self.save_state(guild_id)
            await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(str(e)))

    def _is_timestamp_too_old(self, timestamp) -> bool:
        """Check if a timestamp is more than 1 hour in the past."""
        return timestamp < time.time() - 3600

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

    async def _process_approved_announcement(self, message):
        """Process an approved announcement request"""
        try:
            guild_id = str(message.guild.id)
            state = self._get_state(guild_id)

            # Send processing message
            processing_msg = await message.reply(Messages.Discord.PROCESSING)

            # Process with AI using the current message content
            result = await self.ai_processor.process_announcement(message.content)

            if not result.success:
                await processing_msg.edit(content=Messages.Discord.ERROR_OCCURRED.format(result.error))
                return

            # Check if timestamp is too far in the past
            if self._is_timestamp_too_old(result.timestamp):
                admin_role_id = self._get_admin_role_id(guild_id)
                role_mention = f"<@&{admin_role_id}>" if admin_role_id else ""
                author_mention = message.author.mention
                mentions = f"{role_mention} {author_mention}".strip()
                await processing_msg.edit(content=Messages.Discord.PAST_TIME_WARNING.format(mentions=mentions))
                return

            # Schedule the announcement
            job_id = await self.scheduler.schedule_announcement(
                result.announcement_timestamp,
                result.title,
                result.content,
                str(message.id),
                guild_id=guild_id,
                event_start_timestamp=result.event_start_timestamp,
                event_end_timestamp=result.event_end_timestamp,
                event_title=result.event_title,
            )

            # Build and send confirmation embed
            embed = self._build_booking_embed(result, job_id)
            await processing_msg.edit(content=None, embed=embed)

            # Update state
            state.mark_queued(str(message.id), str(processing_msg.id))

            # Add calendar and fast-forward reactions for quick access
            await processing_msg.add_reaction(self.calendar_emoji)
            await processing_msg.add_reaction(self.fast_forward_emoji)

            await self.save_state(guild_id)

        except Exception as e:
            logger.error(Messages.Log.APPROVED_ANNOUNCEMENT_ERROR.format(e))
            if 'processing_msg' in locals():
                await processing_msg.edit(content=Messages.Discord.PROCESSING_ERROR.format(str(e)))
            else:
                await message.reply(Messages.Discord.PROCESSING_ERROR.format(str(e)))
