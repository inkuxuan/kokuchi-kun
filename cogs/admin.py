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

        # Per-guild config lookup: guild_id (int or None) -> config dict
        self.guild_configs = {}
        for guild_conf in config['discord'].get('guilds', []):
            gid = guild_conf.get('guild_id')
            self.guild_configs[gid] = guild_conf

        # Flat set of all monitored channel IDs for quick permission checks
        self._all_channel_ids = set()
        for guild_conf in self.guild_configs.values():
            self._all_channel_ids.update(guild_conf.get('channel_ids', []))

        self.prefix = config['discord']['prefix']
        self.version = get_version()

    def _get_guild_config(self, guild_id):
        """Return the config for a guild, or None if not configured."""
        if guild_id in self.guild_configs:
            return self.guild_configs[guild_id]
        # Fallback: None-keyed entry (old single-guild compat)
        if None in self.guild_configs:
            return self.guild_configs[None]
        return None

    async def cog_check(self, ctx):
        """Permission check that applies to all commands in this cog"""
        # Check if in one of the monitored channels
        if ctx.channel.id not in self._all_channel_ids:
            return False

        # Get the guild-specific admin_role_id
        guild_id = ctx.guild.id if ctx.guild else None
        guild_conf = self._get_guild_config(guild_id)
        if not guild_conf:
            return False

        admin_role_id = guild_conf.get('admin_role_id')
        if admin_role_id is None:
            return False

        return discord.utils.get(ctx.author.roles, id=admin_role_id) is not None

    @commands.hybrid_command(
        name="list",
        description="List all scheduled announcements"
    )
    async def list_jobs(self, ctx):
        """List all scheduled announcements for the current guild"""
        guild_id = ctx.guild.id if ctx.guild else None
        # Convert guild_id to str to match how jobs store it
        str_guild_id = str(guild_id) if guild_id else None
        jobs = self.scheduler.list_jobs(guild_id=str_guild_id)

        if not jobs:
            await ctx.reply(Messages.Discord.NO_SCHEDULED_JOBS)
            return

        embed = discord.Embed(
            title=Messages.Discord.SCHEDULED_JOBS_TITLE,
            color=discord.Color.blue()
        )

        for job in jobs:
            # Trim content if too long
            content = job.content
            if len(content) > 100:
                content = content[:97] + "..."

            embed.add_field(
                name=f"ID: {job.id} - <t:{int(job.timestamp)}:F>",
                value=f"タイトル: {job.title}\n内容: {content}",
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
            # Persist the cancellation to Firestore
            announcement_cog = self.bot.get_cog('AnnouncementCog')
            if announcement_cog:
                guild_id = ctx.guild.id if ctx.guild else None
                await announcement_cog.save_state(guild_id)
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
