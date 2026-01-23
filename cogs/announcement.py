import logging
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import uuid
import time
from utils.messages import Messages
from utils.persistence import Persistence

logger = logging.getLogger(__name__)

class AnnouncementCog(commands.Cog):
    def __init__(self, bot, config, ai_processor, scheduler):
        self.bot = bot
        self.config = config
        self.ai_processor = ai_processor
        self.scheduler = scheduler
        self.channel_ids = config['discord']['channel_ids']  # List of channel IDs to monitor
        self.admin_role_id = config['discord']['admin_role_id']
        self.seen_emoji = config['discord'].get('seen_reaction_emoji', "👀")
        self.approval_emoji = config['discord'].get('approval_reaction_emoji', "👍")
        self.fast_forward_emoji = config['discord'].get('fast_forward_emoji', "⏩")
        self.calendar_emoji = config['discord'].get('calendar_emoji', "📅")
        self.pending_requests = {}  # Store message IDs and their scheduled message IDs
        self.calendar_events = {} # Store message IDs and their calendar event IDs
        self.queued_announcements = set()  # Store message IDs that have been queued
        self.history = [] # List of completed message IDs (limit 1000)
        self.otp_requests = {}  # Store OTP requests and their futures
        self.persistence = Persistence()
        
        # Set up OTP callback for VRChat API
        self.scheduler.vrchat_api.set_otp_callback(self._request_otp)
        
        # Set up job completion callback
        self.scheduler.set_on_job_completion(self._on_job_complete)

        # Load state will be called in on_ready

    async def _on_job_complete(self, job_data):
        """Callback for when a job completes successfully"""
        try:
            message_id = job_data.get('message_id')
            if message_id:
                # Add to history
                if message_id not in self.history:
                    self.history.append(message_id)
                    # Limit history to 1000 items
                    if len(self.history) > 1000:
                        self.history = self.history[-1000:]

                # Remove from queued list
                if message_id in self.queued_announcements:
                    self.queued_announcements.remove(message_id)

                # Remove from pending requests (request complete)
                if message_id in self.pending_requests:
                    del self.pending_requests[message_id]

                # Save state
                self.save_state()
                logger.info(f"Job completed and saved to history: {message_id}")
        except Exception as e:
            logger.error(f"Error in job completion callback: {e}")

    def save_state(self):
        """Save the current state to disk"""
        self.persistence.save_data('pending.json', self.pending_requests)
        self.persistence.save_data('history.json', self.history)
        self.persistence.save_data('jobs.json', self.scheduler.get_jobs_data())
        self.persistence.save_data('calendar_events.json', self.calendar_events)

    def load_state(self):
        """Load state from disk"""
        self.pending_requests = self.persistence.load_data('pending.json', {})
        self.history = self.persistence.load_data('history.json', [])
        self.calendar_events = self.persistence.load_data('calendar_events.json', {})

        jobs_data = self.persistence.load_data('jobs.json', [])
        restored_count, skipped_jobs = self.scheduler.restore_jobs(jobs_data)

        # Rebuild queued_announcements from restored jobs
        self.queued_announcements = set()
        for job in self.scheduler.list_jobs():
            if 'message_id' in job:
                self.queued_announcements.add(job['message_id'])

        return restored_count, len(self.pending_requests), skipped_jobs

    @commands.Cog.listener()
    async def on_ready(self):
        """Called when the bot is ready"""
        try:
            # Load state
            restored_jobs, pending_count, skipped_jobs = self.load_state()

            # Immediately save state to clean up any skipped jobs from jobs.json
            self.save_state()

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
            # Check if this message has already been queued or sent
            if str(message.id) in self.queued_announcements:
                await message.reply(Messages.Discord.ALREADY_BOOKED)
                return

            if str(message.id) in self.history:
                await message.reply(Messages.Discord.ALREADY_BOOKED)
                return
                
            # Simply store the message ID and add reaction
            self.pending_requests[str(message.id)] = None  # Will store scheduled message ID later
            self.save_state()
            await message.add_reaction(self.seen_emoji)
            await message.reply(Messages.Discord.REQUEST_CONFIRMED)
            
        except Exception as e:
            logger.error(Messages.Log.ANNOUNCEMENT_REQUEST_ERROR.format(e))
            await message.reply(Messages.Discord.ERROR_OCCURRED.format(str(e)))
    
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
            
        # Get member to check roles
        try:
            member = await channel.guild.fetch_member(payload.user_id)
        except:
            return

        # Case 1: Approval of pending request (Reaction to User's message)
        if str(payload.message_id) in self.pending_requests:
            # Check for approval reaction and admin role
            if str(payload.emoji) == self.approval_emoji:
                if not member or self.admin_role_id not in [role.id for role in member.roles]:
                    return

                message = await channel.fetch_message(payload.message_id)
                if not message:
                    return

                # Check if this message has already been queued
                if str(message.id) in self.queued_announcements:
                    return

                # Check if this message has already been sent (history)
                if str(message.id) in self.history:
                    return

                # Process the approved announcement
                await self._process_approved_announcement(message)
                return

        # Case 2: Immediate posting of queued announcement (Reaction to Bot's message)
        if str(payload.emoji) == self.fast_forward_emoji:
            # Find the original request ID based on the bot's message ID (queued message)
            request_msg_id = None
            for req_id, queued_msg_id in self.pending_requests.items():
                if queued_msg_id == str(payload.message_id):
                    request_msg_id = req_id
                    break
            
            if request_msg_id:
                # Get the original request message to check author
                try:
                    request_message = await channel.fetch_message(int(request_msg_id))

                    # Check permissions: Admin or Original Author
                    is_admin = member and self.admin_role_id in [role.id for role in member.roles]
                    is_author = request_message.author.id == payload.user_id

                    if is_admin or is_author:
                        await self._process_immediate_post(request_msg_id, payload.channel_id, payload.message_id)
                except Exception as e:
                    logger.error(f"Error handling immediate post request: {e}")

        # Case 3: Create Calendar Event (Reaction to Bot's message)
        if str(payload.emoji) == self.calendar_emoji:
            # Find the original request ID based on the bot's message ID (booked message)
            request_msg_id = None
            for req_id, queued_msg_id in self.pending_requests.items():
                if queued_msg_id == str(payload.message_id):
                    request_msg_id = req_id
                    break

            if request_msg_id:
                # Check if event already exists
                if str(request_msg_id) in self.calendar_events:
                    return

                # Get the original request message to check author
                try:
                    request_message = await channel.fetch_message(int(request_msg_id))

                    # Verify user is Author or Admin
                    is_admin = member and self.admin_role_id in [role.id for role in member.roles]
                    is_author = request_message.author.id == payload.user_id

                    if is_admin or is_author:
                        await self._process_calendar_event_creation(request_message, channel)
                except Exception as e:
                    logger.error(f"Error handling calendar event creation: {e}")

    async def _process_calendar_event_creation(self, message, channel):
        """Process the creation of a VRChat calendar event"""
        try:
            job = self.scheduler.get_job_by_message_id(str(message.id))
            if not job:
                logger.warning(Messages.Log.CALENDAR_EVENT_CREATE_WARNING.format(message.id))
                return

            # Retrieve event details from job
            title = job.get('event_title', job['title'])
            content = job['content']
            start_at = job.get('event_start_timestamp')
            end_at = job.get('event_end_timestamp')

            if not start_at or not end_at:
                await channel.send(Messages.Discord.CALENDAR_MISSING_TIME)
                return

            # Call VRChat API
            result = await self.scheduler.vrchat_api.create_group_calendar_event(title, content, start_at, end_at)

            if result['success']:
                calendar_id = result['event_id']
                group_id = self.scheduler.vrchat_api.group_id

                # Store event ID
                self.calendar_events[str(message.id)] = calendar_id
                self.save_state()

                # Send success message
                calendar_url = f"https://vrchat.com/home/group/{group_id}/calendar/{calendar_id}"
                await channel.send(Messages.Discord.CALENDAR_CREATED.format(calendar_url))
            else:
                error_msg = result.get('error', 'Unknown error')
                await channel.send(Messages.Discord.CALENDAR_CREATE_FAIL.format(error_msg))
                logger.error(Messages.Log.CALENDAR_EVENT_CREATE_FAIL.format(error_msg))

        except Exception as e:
            logger.error(Messages.Log.CALENDAR_EVENT_CREATE_EXCEPTION.format(e))
            await channel.send(Messages.Discord.ERROR_OCCURRED.format(str(e)))

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

        # Case: Removal of Calendar reaction
        if str(payload.emoji) == self.calendar_emoji:
            # The reaction is removed from the bot's message.
            # We need to find the original request ID.
            request_msg_id = None
            for req_id, queued_msg_id in self.pending_requests.items():
                if queued_msg_id == str(payload.message_id):
                    request_msg_id = req_id
                    break

            if request_msg_id and str(request_msg_id) in self.calendar_events:
                try:
                     member = await channel.guild.fetch_member(payload.user_id)
                     # Get original request message to check permissions
                     request_message = await channel.fetch_message(int(request_msg_id))

                     is_admin = member and self.admin_role_id in [role.id for role in member.roles]
                     is_author = request_message.author.id == payload.user_id

                     if is_admin or is_author:
                        calendar_event_id = self.calendar_events[str(request_msg_id)]
                        result = await self.scheduler.vrchat_api.delete_group_calendar_event(calendar_event_id)
                        del self.calendar_events[str(request_msg_id)]
                        self.save_state()
                        if result['success']:
                            await channel.send(Messages.Discord.CALENDAR_DELETED)
                        else:
                            await channel.send(result['error'])
                except Exception as e:
                    logger.error(Messages.Log.CALENDAR_EVENT_DELETE_ERROR.format(e))

        # Case: Removal of Approval reaction (on User's message)
        # Note: pending_requests keys are user's message IDs (as strings)
        elif str(payload.emoji) == self.approval_emoji:
            # Check if this message (user's message) is in queued announcements
            if str(payload.message_id) not in self.queued_announcements:
                return

            message = await channel.fetch_message(payload.message_id)
            if not message:
                return
                
            # Check if there are any approval reactions left
            approval_reactions = [r for r in message.reactions if str(r.emoji) == self.approval_emoji]
            if not approval_reactions or approval_reactions[0].count == 0:
                # Cancel the job and delete the scheduled message
                if self.scheduler.cancel_job_by_message_id(str(message.id)):
                    scheduled_msg_id = self.pending_requests.get(str(message.id))
                    if scheduled_msg_id:
                        try:
                            scheduled_msg = await channel.fetch_message(scheduled_msg_id)
                            if scheduled_msg:
                                await scheduled_msg.delete()
                        except Exception as e:
                            logger.error(Messages.Log.SCHEDULED_MSG_DELETE_ERROR.format(e))

                    # Also delete calendar event if exists
                    if str(message.id) in self.calendar_events:
                        calendar_event_id = self.calendar_events[str(message.id)]
                        await self.scheduler.vrchat_api.delete_group_calendar_event(calendar_event_id)
                        del self.calendar_events[str(message.id)]
                        await channel.send(Messages.Discord.CALENDAR_DELETED_WITH_CANCEL)

                    # Clean up tracking - keep in pending_requests but clear scheduled message ID
                    if str(message.id) in self.queued_announcements:
                        self.queued_announcements.remove(str(message.id))
                    self.pending_requests[str(message.id)] = None

                    self.save_state()
                    await message.reply(Messages.Discord.BOOKING_CANCELLED)

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
        self.scheduler.cancel_job(job['id'])

        # Post immediately
        try:
            result = await self.scheduler.vrchat_api.post_announcement(job['title'], job['content'])

            if result['success']:
                # Update embed to show success
                embed = processing_msg.embeds[0]
                embed.color = discord.Color.gold()
                embed.title = Messages.Discord.IMMEDIATE_POST_SUCCESS
                embed.description = Messages.Discord.IMMEDIATE_POST_EXECUTED
                # Remove timestamp field if needed, or update it
                # For now just updating title and color

                await processing_msg.edit(embed=embed)

                # Clean up tracking
                if str(request_msg_id) in self.queued_announcements:
                    self.queued_announcements.remove(str(request_msg_id))

                # Add to history
                if str(request_msg_id) not in self.history:
                    self.history.append(str(request_msg_id))
                    if len(self.history) > 1000:
                        self.history = self.history[-1000:]

                self.save_state()
                # We keep pending_requests as it maps to the processing msg which still exists
            else:
                await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(result['error']))

        except Exception as e:
            logger.error(f"Error in immediate post: {e}")
            await channel.send(Messages.Discord.IMMEDIATE_POST_FAIL.format(str(e)))
    
    async def _process_approved_announcement(self, message):
        """Process an approved announcement request"""
        try:
            # Send processing message
            processing_msg = await message.reply(Messages.Discord.PROCESSING)
            
            # Process with AI using the current message content
            result = await self.ai_processor.process_announcement(message.content)
            
            if not result["success"]:
                await processing_msg.edit(content=Messages.Discord.ERROR_OCCURRED.format(result['error']))
                return

            # Check if timestamp is in the past (more than 1 hour ago)
            current_timestamp = time.time()
            if result["timestamp"] < current_timestamp - 3600:
                role_mention = f"<@&{self.admin_role_id}>"
                author_mention = message.author.mention
                mentions = f"{role_mention} {author_mention}"

                await processing_msg.edit(content=Messages.Discord.PAST_TIME_WARNING.format(mentions=mentions))
                return
                
            # Schedule the announcement
            job_id = await self.scheduler.schedule_announcement(
                result["announcement_timestamp"],
                result["title"],
                result["content"],
                str(message.id),
                event_start_timestamp=result["event_start_timestamp"],
                event_end_timestamp=result["event_end_timestamp"],
                event_title=result.get("event_title")
            )
            
            # Create confirmation embed
            embed = discord.Embed(
                title=Messages.Discord.BOOKING_COMPLETED_TITLE,
                color=discord.Color.green()
            )
            embed.add_field(name="告知予定時刻", value=f"<t:{int(result['announcement_timestamp'])}:F>", inline=False)
            embed.add_field(name="イベント開始", value=f"<t:{int(result['event_start_timestamp'])}:F>", inline=False)
            embed.add_field(name="イベント終了", value=f"<t:{int(result['event_end_timestamp'])}:F>", inline=False)

            embed.add_field(name=Messages.Discord.FIELD_TITLE, value=result["title"], inline=False)
            
            content = result["content"]
            if len(content) > 1024:
                content = content[:1021] + "..."
            embed.add_field(name=Messages.Discord.FIELD_CONTENT, value=content, inline=False)
            embed.add_field(name=Messages.Discord.FIELD_JOB_ID, value=job_id, inline=False)
            embed.add_field(name=Messages.Discord.FIELD_HINTS, value=Messages.Discord.FIELD_HINTS_CONTENTS, inline=False)
            
            # Update the processing message with the final result
            await processing_msg.edit(content=None, embed=embed)
            
            # Store the processing message ID for potential cancellation
            self.pending_requests[str(message.id)] = str(processing_msg.id)
            self.queued_announcements.add(str(message.id))
            
            # Add calendar reaction for quick access
            await processing_msg.add_reaction(self.calendar_emoji)

            # Add fast forward reaction for quick access
            await processing_msg.add_reaction(self.fast_forward_emoji)

            self.save_state()

        except Exception as e:
            logger.error(Messages.Log.APPROVED_ANNOUNCEMENT_ERROR.format(e))
            if 'processing_msg' in locals():
                await processing_msg.edit(content=Messages.Discord.PROCESSING_ERROR.format(str(e)))
            else:
                await message.reply(Messages.Discord.PROCESSING_ERROR.format(str(e)))
