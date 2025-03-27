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
        self.channel_id = config['discord']['channel_id']
        self.admin_role_id = config['discord']['admin_role_id']
        self.seen_emoji = config['discord'].get('seen_reaction_emoji', "👀")
        self.approval_emoji = config['discord'].get('approval_reaction_emoji', "👍")
        self.pending_requests = {}
        
    @commands.Cog.listener()
    async def on_message(self, message):
        """Process messages in the announcement channel"""
        # Ignore own messages and messages from other channels
        if message.author.bot or message.channel.id != self.channel_id:
            return
        
        # Check if message mentions the bot and is an announcement request
        if self.bot.user.mentioned_in(message):
            await self._handle_announcement_request(message)
    
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
        if payload.channel_id != self.channel_id:
            return
            
        # Fetch the message and guild
        channel = self.bot.get_channel(payload.channel_id)
        if not channel:
            return
            
        message = await channel.fetch_message(payload.message_id)
        if not message:
            return
            
        # Check for approval reaction and admin role
        if str(payload.emoji) != self.approval_emoji:
            return
            
        # Check if the user has admin role
        member = await message.guild.fetch_member(payload.user_id)
        if not member or self.admin_role_id not in [role.id for role in member.roles]:
            return
            
        # Process the approved announcement
        await self._process_approved_announcement(message)
    
    async def _handle_announcement_request(self, message):
        """Handle a new announcement request"""
        try:
            logger.info(f"Received announcement request from {message.author.name}")
            
            # React to show we've seen it
            await message.add_reaction(self.seen_emoji)
            
            # Store the request
            self.pending_requests[str(message.id)] = {
                "content": message.content,
                "author_id": message.author.id
            }
            
            # Reply to confirm
            await message.reply("告知リクエストを確認しました。管理者の承認を待っています。")
            
        except Exception as e:
            logger.error(f"Error handling announcement request: {e}")
            await message.reply(f"エラーが発生しました: {str(e)}")
    
    async def _process_approved_announcement(self, message):
        """Process an approved announcement request"""
        try:
            request_id = str(message.id)
            if request_id not in self.pending_requests:
                return
                
            request = self.pending_requests[request_id]
            
            # Process with AI
            result = await self.ai_processor.process_announcement(request["content"])
            
            if not result["success"]:
                await message.reply(f"エラーが発生しました: {result['error']}")
                return
                
            # Schedule the announcement
            job_id = await self.scheduler.schedule_announcement(
                result["timestamp"],
                result["title"],
                result["content"]
            )
            
            # Confirm the scheduled announcement
            embed = discord.Embed(
                title="告知が予約されました",
                color=discord.Color.green()
            )
            embed.add_field(name="投稿日時", value=result["formatted_date_time"], inline=False)
            embed.add_field(name="タイトル", value=result["title"], inline=False)
            
            # Trim content if too long
            content = result["content"]
            if len(content) > 1024:
                content = content[:1021] + "..."
            embed.add_field(name="内容", value=content, inline=False)
            embed.add_field(name="ジョブID", value=job_id, inline=False)
            
            await message.reply(embed=embed)
            
            # Remove from pending requests
            del self.pending_requests[request_id]
            
        except Exception as e:
            logger.error(f"Error processing approved announcement: {e}")
            await message.reply(f"告知の処理中にエラーが発生しました: {str(e)}") 