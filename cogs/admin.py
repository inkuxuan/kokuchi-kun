import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional
from utils.messages import Messages
from utils.version import get_version

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot, config, scheduler):
        self.bot = bot
        self.config = config
        self.scheduler = scheduler
        self.channel_ids = config['discord']['channel_ids']  # List of channel IDs to monitor
        self.admin_role_id = config['discord']['admin_role_id']
        self.prefix = config['discord']['prefix']
        self.version = get_version()
    
    async def cog_check(self, ctx):
        """Permission check that applies to all commands in this cog"""
        # Check if in one of the monitored channels
        if ctx.channel.id not in self.channel_ids:
            return False
            
        # Check for admin role
        member = ctx.author
        return discord.utils.get(member.roles, id=self.admin_role_id) is not None
    
    @commands.hybrid_command(
        name="list",
        description="List all scheduled announcements"
    )
    async def list_jobs(self, ctx):
        """List all scheduled announcements"""
        jobs = self.scheduler.list_jobs()
        
        if not jobs:
            await ctx.reply(Messages.Discord.NO_SCHEDULED_JOBS)
            return
            
        embed = discord.Embed(
            title=Messages.Discord.SCHEDULED_JOBS_TITLE,
            color=discord.Color.blue()
        )
        
        for job in jobs:
            # Trim content if too long
            content = job["content"]
            if len(content) > 100:
                content = content[:97] + "..."
                
            embed.add_field(
                name=f"ID: {job['id']} - <t:{int(job['timestamp'])}:F>",
                value=f"タイトル: {job['title']}\n内容: {content}",
                inline=False
            )
            
        await ctx.reply(embed=embed)
        
    @commands.hybrid_command(
        name="cancel",
        description="Cancel a scheduled announcement"
    )
    async def cancel_job(self, ctx, job_id: str):
        """Cancel a scheduled announcement"""
        result = self.scheduler.cancel_job(job_id)
        
        if result:
            await ctx.reply(Messages.Discord.JOB_CANCELLED.format(job_id))
        else:
            await ctx.reply(Messages.Discord.JOB_NOT_FOUND.format(job_id))
            
    @commands.hybrid_command(
        name="help",
        description="Display admin command help"
    )
    async def help_command(self, ctx):
        """Display help information"""
        embed = discord.Embed(
            title=Messages.Discord.CMD_LIST_TITLE,
            color=discord.Color.blue()
        )
        
        prefix = self.prefix
        embed.add_field(name=f"{prefix}list または /list", value=Messages.Discord.CMD_LIST_DESC, inline=False)
        embed.add_field(name=f"{prefix}cancel [ジョブID] または /cancel", value=Messages.Discord.CMD_CANCEL_DESC, inline=False)
        embed.add_field(name=f"{prefix}help または /help", value=Messages.Discord.CMD_HELP_DESC, inline=False)
        
        # Add version information
        embed.set_footer(text=f"Version: {self.version}")
        
        await ctx.reply(embed=embed)
    
    async def cog_app_command_error(self, interaction, error):
        """Handle errors from slash commands"""
        if isinstance(error, app_commands.errors.CheckFailure):
            await interaction.response.send_message(Messages.Discord.NO_PERMISSION, ephemeral=True)
        else:
            logger.error(Messages.Log.ADMIN_CMD_ERROR.format(str(error)))
            await interaction.response.send_message(Messages.Discord.CMD_EXEC_ERROR, ephemeral=True)