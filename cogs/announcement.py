import logging
import discord
from discord.ext import commands
from discord import app_commands

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
        self.pending_requests = {}  # Store message IDs and their scheduled message IDs
        self.queued_announcements = set()  # Store message IDs that have been queued
        
    @commands.Cog.listener()
    async def on_message(self, message):
        """Process messages in the announcement channels"""
        # Ignore own messages and messages from non-monitored channels
        if message.author.bot or message.channel.id not in self.channel_ids:
            return
        
        # Check if message mentions the bot and is an announcement request
        if self.bot.user.mentioned_in(message):
            await self._handle_announcement_request(message)
    
    async def _handle_announcement_request(self, message):
        """Handle a new announcement request"""
        try:
            # Check if this message has already been queued
            if str(message.id) in self.queued_announcements:
                await message.reply("この告知は既に予約されています。")
                return
                
            # Simply store the message ID and add reaction
            self.pending_requests[str(message.id)] = None  # Will store scheduled message ID later
            await message.add_reaction(self.seen_emoji)
            await message.reply("告知リクエストを確認しました。管理者の承認を待っています。")
            
        except Exception as e:
            logger.error(f"Error handling announcement request: {e}")
            await message.reply(f"エラーが発生しました: {str(e)}")
    
    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        """Process reactions to announcement requests"""
        # Ignore own reactions
        if payload.user_id == self.bot.user.id:
            return
            
        # Check if this is a pending request
        if str(payload.message_id) not in self.pending_requests:
            return
            
        # Check if the channel is correct
        if payload.channel_id not in self.channel_ids:
            return
            
        # Check for approval reaction and admin role
        if str(payload.emoji) != self.approval_emoji:
            return
            
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
            
        message = await channel.fetch_message(payload.message_id)
        if not message:
            return
            
        # Check if the user has admin role
        member = await message.guild.fetch_member(payload.user_id)
        if not member or self.admin_role_id not in [role.id for role in member.roles]:
            return
            
        # Check if this message has already been queued
        if str(message.id) in self.queued_announcements:
            return
            
        # Process the approved announcement
        await self._process_approved_announcement(message)
    
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
                        logger.error(f"Error deleting scheduled message: {e}")
                
                # Clean up tracking
                self.queued_announcements.remove(str(message.id))
                del self.pending_requests[str(message.id)]
                
                await message.reply("告知の予約がキャンセルされました。")
    
    async def _process_approved_announcement(self, message):
        """Process an approved announcement request"""
        try:
            # Send processing message
            processing_msg = await message.reply("処理中...")
            
            # Process with AI using the current message content
            result = await self.ai_processor.process_announcement(message.content)
            
            if not result["success"]:
                await processing_msg.edit(content=f"エラーが発生しました: {result['error']}")
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
                title="告知が予約されました",
                color=discord.Color.green()
            )
            embed.add_field(name="投稿日時", value=f"<t:{int(result['timestamp'])}:F>", inline=False)
            embed.add_field(name="タイトル", value=result["title"], inline=False)
            
            content = result["content"]
            if len(content) > 1024:
                content = content[:1021] + "..."
            embed.add_field(name="内容", value=content, inline=False)
            embed.add_field(name="ジョブID", value=job_id, inline=False)
            
            # Update the processing message with the final result
            await processing_msg.edit(content=None, embed=embed)
            
            # Store the processing message ID for potential cancellation
            self.pending_requests[str(message.id)] = str(processing_msg.id)
            self.queued_announcements.add(str(message.id))
            
        except Exception as e:
            logger.error(f"Error processing approved announcement: {e}")
            if 'processing_msg' in locals():
                await processing_msg.edit(content=f"告知の処理中にエラーが発生しました: {str(e)}")
            else:
                await message.reply(f"告知の処理中にエラーが発生しました: {str(e)}") 