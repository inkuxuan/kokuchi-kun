import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import Optional
import tomli

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot, config, scheduler):
        self.bot = bot
        self.config = config
        self.scheduler = scheduler
        self.channel_ids = config['discord']['channel_ids']  # List of channel IDs to monitor
        self.admin_role_id = config['discord']['admin_role_id']
        self.prefix = config['discord']['prefix']
        
        # Load version from pyproject.toml
        try:
            with open('pyproject.toml', 'rb') as f:
                pyproject = tomli.load(f)
                self.version = pyproject['project']['version']
        except Exception as e:
            logger.error(f"Failed to load version from pyproject.toml: {e}")
            self.version = "unknown"
    
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
            await ctx.reply("予約されている告知はありません。")
            return
            
        embed = discord.Embed(
            title="予約されている告知",
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
            await ctx.reply(f"ジョブID {job_id} の告知をキャンセルしました。")
        else:
            await ctx.reply(f"ジョブID {job_id} は見つかりませんでした。")
            
    @commands.hybrid_command(
        name="help",
        description="Display admin command help"
    )
    async def help_command(self, ctx):
        """Display help information"""
        embed = discord.Embed(
            title="コマンド一覧",
            color=discord.Color.blue()
        )
        
        prefix = self.prefix
        embed.add_field(name=f"{prefix}list または /list", value="予約されている告知の一覧を表示", inline=False)
        embed.add_field(name=f"{prefix}cancel [ジョブID] または /cancel", value="指定されたジョブIDの告知をキャンセル", inline=False)
        embed.add_field(name=f"{prefix}help または /help", value="このヘルプメッセージを表示", inline=False)
        
        # Add version information
        embed.set_footer(text=f"Version: {self.version}")
        
        await ctx.reply(embed=embed)
    
    async def cog_app_command_error(self, interaction, error):
        """Handle errors from slash commands"""
        if isinstance(error, app_commands.errors.CheckFailure):
            await interaction.response.send_message("このコマンドを実行する権限がありません。", ephemeral=True)
        else:
            logger.error(f"Error in admin command: {str(error)}")
            await interaction.response.send_message("コマンドの実行中にエラーが発生しました。", ephemeral=True) 