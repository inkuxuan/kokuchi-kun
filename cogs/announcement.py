import logging
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import uuid
from utils.messages import Messages

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
        self.pending_requests = {}  # Store message IDs and their scheduled message IDs
        self.queued_announcements = set()  # Store message IDs that have been queued
        self.otp_requests = {}  # Store OTP requests and their futures
        
        # Set up OTP callback for VRChat API
        self.scheduler.vrchat_api.set_otp_callback(self._request_otp)
        
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
            # Check if this message has already been queued
            if str(message.id) in self.queued_announcements:
                await message.reply(Messages.Discord.ALREADY_BOOKED)
                return
                
            # Simply store the message ID and add reaction
            self.pending_requests[str(message.id)] = None  # Will store scheduled message ID later
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
    
    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload):
        """Handle reaction removals"""
        # Ignore own reactions
        if payload.user_id == self.bot.user.id:
            return
            
        # Check if this is a queued announcement
        if str(payload.message_id) not in self.queued_announcements:
            return
            
        # Check if the channel is correct
        if payload.channel_id not in self.channel_ids:
            return
            
        # Check if it was an approval reaction
        if str(payload.emoji) != self.approval_emoji:
            return
            
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
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
                
                # Clean up tracking - keep in pending_requests but clear scheduled message ID
                self.queued_announcements.remove(str(message.id))
                self.pending_requests[str(message.id)] = None
                
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
                self.queued_announcements.remove(str(request_msg_id))
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
                
            # Schedule the announcement
            job_id = await self.scheduler.schedule_announcement(
                result["timestamp"],
                result["title"],
                result["content"],
                str(message.id)
            )
            
            # Create confirmation embed
            embed = discord.Embed(
                title=Messages.Discord.BOOKING_COMPLETED_TITLE,
                color=discord.Color.green()
            )
            embed.add_field(name=Messages.Discord.FIELD_POST_TIME, value=f"<t:{int(result['timestamp'])}:F>", inline=False)
            embed.add_field(name=Messages.Discord.FIELD_TITLE, value=result["title"], inline=False)
            
            content = result["content"]
            if len(content) > 1024:
                content = content[:1021] + "..."
            embed.add_field(name=Messages.Discord.FIELD_CONTENT, value=content, inline=False)
            embed.add_field(name=Messages.Discord.FIELD_JOB_ID, value=job_id, inline=False)
            
            # Update the processing message with the final result
            await processing_msg.edit(content=None, embed=embed)
            
            # Store the processing message ID for potential cancellation
            self.pending_requests[str(message.id)] = str(processing_msg.id)
            self.queued_announcements.add(str(message.id))
            
        except Exception as e:
            logger.error(Messages.Log.APPROVED_ANNOUNCEMENT_ERROR.format(e))
            if 'processing_msg' in locals():
                await processing_msg.edit(content=Messages.Discord.PROCESSING_ERROR.format(str(e)))
            else:
                await message.reply(Messages.Discord.PROCESSING_ERROR.format(str(e)))