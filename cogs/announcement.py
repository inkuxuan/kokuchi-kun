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
    def __init__(self, bot, config, ai_processor, scheduler, persistence, vrchat_api):
        self.bot = bot
        self.config = config
        self.ai_processor = ai_processor
        self.scheduler = scheduler
        self.vrchat_api = vrchat_api
        self.channel_ids = config['discord']['channel_ids']  # List of channel IDs to monitor
        self.admin_role_id = config['discord']['admin_role_id']
        self.seen_emoji = config['discord'].get('seen_reaction_emoji', "👀")
        self.approval_emoji = config['discord'].get('approval_reaction_emoji', "👍")
        self.fast_forward_emoji = config['discord'].get('fast_forward_emoji', "⏩")
        self.calendar_emoji = config['discord'].get('calendar_emoji', "📅")
        self.state = AnnouncementState()
        self.otp_requests = {}  # Store OTP requests and their futures
        self.persistence = persistence

        # Set up OTP callback for VRChat API
        self.vrchat_api.set_otp_callback(self._request_otp)

        # Set up job completion callback
        self.scheduler.set_on_job_completion(self._on_job_complete)

        # Load state will be called in on_ready

    # --- State persistence ---

    async def save_state(self):
        """Save the current state to Firestore"""
        await self.state.save(self.persistence)
        await self.persistence.save_data('jobs', self.scheduler.get_jobs_data())

    async def load_state(self):
        """Load state from Firestore"""
        await self.state.load(self.persistence)

        jobs_data = await self.persistence.load_data('jobs', [])
        restored_count, skipped_jobs = self.scheduler.restore_jobs(jobs_data)

        # Rebuild queued_announcements from restored jobs
        self.state.queued_announcements = set()
        for job in self.scheduler.list_jobs():
            if job.message_id:
                self.state.queued_announcements.add(job.message_id)

        return restored_count, len(self.state.pending_requests), skipped_jobs

    # --- Callbacks ---

    async def _on_job_complete(self, job_data):
        """Callback for when a job completes (success or failure)"""
        try:
            message_id = job_data.get('message_id')
            status = job_data.get('status', 'success')

            if message_id and status == 'success':
                self.state.mark_completed(message_id)

            # Save state for both success and failure
            await self.save_state()
            logger.info(f"Job {status} and state saved: {message_id}")
        except Exception as e:
            logger.error(f"Error in job completion callback: {e}")

    # --- OTP handling ---

    async def _request_otp(self, otp_type):
        """Request OTP from admin through Discord"""
        # Get the first channel from config
        channel = self.bot.get_channel(self.channel_ids[0])
        if not channel:
            logger.error(Messages.Log.OTP_CHANNEL_NOT_FOUND)
            return None

        # Create a unique request ID
        request_id = str(uuid.uuid4())

        # Create a future to wait for the response
        future = asyncio.Future()
        self.otp_requests[request_id] = future

        # Send OTP request message
        role_mention = f"<@&{self.admin_role_id}>"
        message = await channel.send(Messages.Discord.OTP_REQUEST.format(role_mention=role_mention, otp_type=otp_type))

        try:
            # Wait for response with timeout
            otp = await asyncio.wait_for(future, timeout=300)  # 5 minute timeout
            return otp
        except asyncio.TimeoutError:
            await message.edit(content=Messages.Discord.OTP_TIMEOUT.format(role_mention=role_mention))
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
            # Load state
            restored_jobs, pending_count, skipped_jobs = await self.load_state()

            # Immediately save state to clean up any skipped jobs from jobs
            await self.save_state()

            # Send restoration message
            channel = self.bot.get_channel(self.channel_ids[0])
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
        """Process messages in the announcement channels"""
        # Check for OTP response
        if message.author.bot:
            return

        # Check if this is an OTP response
        if message.channel.id in self.channel_ids:
            # Check if the user has admin role
            member = await message.guild.fetch_member(message.author.id)
            if member and self.admin_role_id in [role.id for role in member.roles]:
                # Check if this is a response to an OTP request
                for request_id, future in list(self.otp_requests.items()):
                    if not future.done():
                        # Set the OTP value
                        future.set_result(message.content.strip())
                        # Delete the message for security
                        await message.delete()
                        return

        # Ignore messages from non-monitored channels
        if message.channel.id not in self.channel_ids:
            return

        # Check if message mentions the bot and is an announcement request
        if self.bot.user.mentioned_in(message):
            await self._handle_announcement_request(message)

    async def _handle_announcement_request(self, message):
        """Handle a new announcement request"""
        try:
            msg_id = str(message.id)

            # Check if this message has already been queued or sent
            if self.state.is_queued(msg_id) or self.state.is_in_history(msg_id):
                await message.reply(Messages.Discord.ALREADY_BOOKED)
                return

            # Simply store the message ID and add reaction
            self.state.add_pending(msg_id)
            await self.save_state()
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

        # Check if the channel is correct
        if payload.channel_id not in self.channel_ids:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        emoji = str(payload.emoji)
        msg_id = str(payload.message_id)

        # Case 1: Approval of pending request (Reaction to User's message)
        if emoji == self.approval_emoji and self.state.is_pending(msg_id):
            member = await self._fetch_member_safe(channel, payload.user_id)
            if not self._is_admin(member):
                return

            if self.state.is_queued(msg_id) or self.state.is_in_history(msg_id):
                return

            message = await channel.fetch_message(payload.message_id)
            if message:
                await self._process_approved_announcement(message)
            return

        # Case 2: Immediate posting of queued announcement (Reaction to Bot's message)
        if emoji == self.fast_forward_emoji:
            await self._handle_fast_forward_reaction(channel, payload)
            return

        # Case 3: Create Calendar Event (Reaction to Bot's message)
        if emoji == self.calendar_emoji:
            await self._handle_calendar_reaction(channel, payload)

    async def _handle_fast_forward_reaction(self, channel, payload):
        """Handle fast-forward reaction to immediately post a queued announcement"""
        request_msg_id = self.state.find_request_id_by_bot_message(str(payload.message_id))
        if not request_msg_id:
            return

        try:
            request_message = await channel.fetch_message(int(request_msg_id))
            member = await self._fetch_member_safe(channel, payload.user_id)

            if self._is_admin(member) or request_message.author.id == payload.user_id:
                await self._process_immediate_post(request_msg_id, payload.channel_id, payload.message_id)
        except Exception as e:
            logger.error(f"Error handling immediate post request: {e}")

    async def _handle_calendar_reaction(self, channel, payload):
        """Handle calendar reaction to create a VRChat calendar event"""
        request_msg_id = self.state.find_request_id_by_bot_message(str(payload.message_id))
        if not request_msg_id:
            return

        # Check if event already exists
        if self.state.has_calendar_event(request_msg_id):
            return

        try:
            request_message = await channel.fetch_message(int(request_msg_id))
            member = await self._fetch_member_safe(channel, payload.user_id)

            if self._is_admin(member) or request_message.author.id == payload.user_id:
                await self._process_calendar_event_creation(request_message, channel)
        except Exception as e:
            logger.error(f"Error handling calendar event creation: {e}")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Handle reaction removals"""
        # Ignore own reactions
        if payload.user_id == self.bot.user.id:
            return

        # Check if the channel is correct
        if payload.channel_id not in self.channel_ids:
            return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return

        emoji = str(payload.emoji)

        # Case: Removal of Calendar reaction
        if emoji == self.calendar_emoji:
            await self._handle_calendar_reaction_remove(channel, payload)

        # Case: Removal of Approval reaction (on User's message)
        elif emoji == self.approval_emoji:
            await self._handle_approval_reaction_remove(channel, payload)

    async def _handle_calendar_reaction_remove(self, channel, payload):
        """Handle removal of calendar reaction to delete the VRChat calendar event"""
        request_msg_id = self.state.find_request_id_by_bot_message(str(payload.message_id))
        if not request_msg_id or not self.state.has_calendar_event(request_msg_id):
            return

        try:
            member = await channel.guild.fetch_member(payload.user_id)
            request_message = await channel.fetch_message(int(request_msg_id))

            if not (self._is_admin(member) or request_message.author.id == payload.user_id):
                return

            calendar_event_id = self.state.remove_calendar_event(request_msg_id)
            result = await self.vrchat_api.delete_group_calendar_event(calendar_event_id)
            await self.save_state()
            if result.success:
                await channel.send(Messages.Discord.CALENDAR_DELETED)
            else:
                await channel.send(result.error)
        except Exception as e:
            logger.error(Messages.Log.CALENDAR_EVENT_DELETE_ERROR.format(e))

    async def _handle_approval_reaction_remove(self, channel, payload):
        """Handle removal of approval reaction to cancel a queued announcement"""
        msg_id = str(payload.message_id)
        if not self.state.is_queued(msg_id):
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

        bot_reply_id = self.state.get_bot_reply_id(msg_id)
        if bot_reply_id:
            try:
                scheduled_msg = await channel.fetch_message(bot_reply_id)
                if scheduled_msg:
                    await scheduled_msg.delete()
            except Exception as e:
                logger.error(Messages.Log.SCHEDULED_MSG_DELETE_ERROR.format(e))

        # Also delete calendar event if exists
        calendar_event_id = self.state.cancel(msg_id)
        if calendar_event_id:
            await self.vrchat_api.delete_group_calendar_event(calendar_event_id)
            await channel.send(Messages.Discord.CALENDAR_DELETED_WITH_CANCEL)

        await self.save_state()
        await message.reply(Messages.Discord.BOOKING_CANCELLED)

    # --- Permission helpers ---

    async def _fetch_member_safe(self, channel, user_id):
        """Fetch a guild member, returning None on failure."""
        try:
            return await channel.guild.fetch_member(user_id)
        except Exception:
            return None

    def _is_admin(self, member) -> bool:
        """Check if a member has the admin role."""
        if not member:
            return False
        return self.admin_role_id in [role.id for role in member.roles]

    # --- Business logic ---

    async def _process_calendar_event_creation(self, message, channel):
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
                self.state.set_calendar_event(str(message.id), calendar_id)
                await self.save_state()

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

    async def _process_immediate_post(self, request_msg_id, channel_id, processing_msg_id):
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
                self.state.mark_completed(str(request_msg_id))
                # Keep pending_requests entry as it maps to the processing msg which still exists
                self.state.pending_requests[str(request_msg_id)] = str(processing_msg_id)

                await self.save_state()
            else:
                # Save state even on failure - the job was already cancelled
                await self.save_state()
                await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(result.error))

        except Exception as e:
            logger.error(f"Error in immediate post: {e}")
            # Save state even on exception - the job was already cancelled
            await self.save_state()
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
            # Send processing message
            processing_msg = await message.reply(Messages.Discord.PROCESSING)

            # Process with AI using the current message content
            result = await self.ai_processor.process_announcement(message.content)

            if not result.success:
                await processing_msg.edit(content=Messages.Discord.ERROR_OCCURRED.format(result.error))
                return

            # Check if timestamp is too far in the past
            if self._is_timestamp_too_old(result.timestamp):
                role_mention = f"<@&{self.admin_role_id}>"
                author_mention = message.author.mention
                mentions = f"{role_mention} {author_mention}"
                await processing_msg.edit(content=Messages.Discord.PAST_TIME_WARNING.format(mentions=mentions))
                return

            # Schedule the announcement
            job_id = await self.scheduler.schedule_announcement(
                result.announcement_timestamp,
                result.title,
                result.content,
                str(message.id),
                event_start_timestamp=result.event_start_timestamp,
                event_end_timestamp=result.event_end_timestamp,
                event_title=result.event_title,
            )

            # Build and send confirmation embed
            embed = self._build_booking_embed(result, job_id)
            await processing_msg.edit(content=None, embed=embed)

            # Update state
            self.state.mark_queued(str(message.id), str(processing_msg.id))

            # Add calendar and fast-forward reactions for quick access
            await processing_msg.add_reaction(self.calendar_emoji)
            await processing_msg.add_reaction(self.fast_forward_emoji)

            await self.save_state()

        except Exception as e:
            logger.error(Messages.Log.APPROVED_ANNOUNCEMENT_ERROR.format(e))
            if 'processing_msg' in locals():
                await processing_msg.edit(content=Messages.Discord.PROCESSING_ERROR.format(str(e)))
            else:
                await message.reply(Messages.Discord.PROCESSING_ERROR.format(str(e)))
