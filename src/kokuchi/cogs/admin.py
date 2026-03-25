from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands
import logging
from typing import TYPE_CHECKING

from kokuchi.common.messages import Messages
from kokuchi.common.version import get_version

if TYPE_CHECKING:
    from kokuchi.state.state_manager import StateManager

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot, config: dict, state_manager: StateManager) -> None:
        self.bot = bot
        self.config = config
        self.state_manager = state_manager

        # Per-guild config lookup: guild_id (str) -> config dict
        self.guild_configs: dict[str, dict] = {}
        for guild_conf in config['discord'].get('guilds', []):
            gid = guild_conf['guild_id']  # str after normalization
            self.guild_configs[gid] = guild_conf

        # Flat set of all monitored channel IDs (str) for quick permission checks
        self._all_channel_ids: set[str] = set()
        for guild_conf in self.guild_configs.values():
            self._all_channel_ids.update(guild_conf.get('channel_ids', []))

        self.prefix: str = config['discord']['prefix']
        self.version: str = get_version()

        # Bot-level admin user ID
        self.admin_id: str | None = config['discord'].get('admin_id')

    def _get_guild_config(self, guild_id: str) -> dict | None:
        """Return the config for a guild, or None if not configured."""
        return self.guild_configs.get(guild_id)

    def _is_bot_admin(self, user_id: int) -> bool:
        """Check if a user is the bot-level admin."""
        return self.admin_id is not None and str(user_id) == self.admin_id

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Permission check that applies to all commands in this cog"""
        # Bot admin bypasses all checks
        if self._is_bot_admin(ctx.author.id):
            return True

        # Check if in one of the monitored channels
        if str(ctx.channel.id) not in self._all_channel_ids:
            return False

        # Get the guild-specific admin_role_id
        guild_id = str(ctx.guild.id)
        guild_conf = self._get_guild_config(guild_id)
        if not guild_conf:
            return False

        admin_role_id = guild_conf.get('admin_role_id')
        if admin_role_id is None:
            return False

        return admin_role_id in [str(role.id) for role in ctx.author.roles]

    @commands.hybrid_command(
        name="list",
        description="List all scheduled announcements"
    )
    async def list_jobs(self, ctx: commands.Context) -> None:
        """List all scheduled announcements for the current guild"""
        guild_id = str(ctx.guild.id)
        jobs = self.state_manager.scheduler.list_jobs(guild_id=guild_id)

        if not jobs:
            await ctx.reply(Messages.Discord.NO_SCHEDULED_JOBS)
            return

        embed = discord.Embed(
            title=Messages.Discord.SCHEDULED_JOBS_TITLE,
            color=discord.Color.blue()
        )

        gctx = self.state_manager.get_guild_context(guild_id)
        for job in jobs:
            # Trim content if too long
            content = job.content
            if len(content) > 100:
                content = content[:97] + "..."

            has_calendar = gctx.state.has_calendar_event(job.message_id)
            calendar_indicator = " 📅" if has_calendar else ""
            embed.add_field(
                name=f"**{job.title}**{calendar_indicator} — <t:{int(job.timestamp)}:F>",
                value=f"ID: {job.id}\n{content}",
                inline=False
            )

        await ctx.reply(embed=embed)

    @commands.hybrid_command(
        name="cancel",
        description="Cancel a scheduled announcement"
    )
    async def cancel_job(self, ctx: commands.Context, message_id: str) -> None:
        """Cancel a scheduled announcement by message ID"""
        # Verify the job belongs to this guild before cancelling
        guild_id = str(ctx.guild.id)
        job = self.state_manager.scheduler.get_job(message_id)
        if job is None or job.guild_id != guild_id:
            await ctx.reply(Messages.Discord.JOB_NOT_FOUND.format(message_id))
            return

        # Only allow cancelling active, missed, or failed jobs
        if job.status not in ('pending', 'missed', 'failed'):
            await ctx.reply(Messages.Discord.JOB_NOT_FOUND.format(message_id))
            return

        # Read bot reply and channel info before cancelling
        state = self.state_manager.get_state(guild_id)
        bot_reply_id = state.get_bot_reply_id(job.message_id)
        channel_id = job.channel_id

        success, deleted_calendar = await self.state_manager.cancel_specific_job(
            guild_id, message_id
        )

        if success:
            # Delete the bot's reply embed
            if bot_reply_id and channel_id:
                channel = self.bot.get_channel(int(channel_id))
                if channel:
                    try:
                        msg = await channel.fetch_message(int(bot_reply_id))
                        await msg.delete()
                    except Exception as e:
                        logger.error(f"Failed to delete bot reply {bot_reply_id} on cancel: {e}")
            if deleted_calendar:
                await ctx.send(Messages.Discord.CALENDAR_DELETED_WITH_CANCEL)
            await ctx.reply(Messages.Discord.JOB_CANCELLED.format(message_id))
        else:
            await ctx.reply(Messages.Discord.JOB_NOT_FOUND.format(message_id))

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Handle errors from slash commands"""
        if isinstance(error, app_commands.errors.CheckFailure):
            await interaction.response.send_message(Messages.Discord.NO_PERMISSION, ephemeral=True)
        else:
            logger.error(Messages.Log.ADMIN_CMD_ERROR.format(str(error)))
            await interaction.response.send_message(Messages.Discord.CMD_EXEC_ERROR, ephemeral=True)
