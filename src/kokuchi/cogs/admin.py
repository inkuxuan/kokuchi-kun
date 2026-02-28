import discord
from discord.ext import commands
from discord import app_commands
import logging
from kokuchi.common.messages import Messages
from kokuchi.common.version import get_version

logger = logging.getLogger(__name__)

class AdminCog(commands.Cog):
    def __init__(self, bot, config, state_manager):
        self.bot = bot
        self.config = config
        self.state_manager = state_manager

        # Per-guild config lookup: guild_id (str) -> config dict
        self.guild_configs = {}
        for guild_conf in config['discord'].get('guilds', []):
            gid = guild_conf['guild_id']  # str after normalization
            self.guild_configs[gid] = guild_conf

        # Flat set of all monitored channel IDs (str) for quick permission checks
        self._all_channel_ids = set()
        for guild_conf in self.guild_configs.values():
            self._all_channel_ids.update(guild_conf.get('channel_ids', []))

        self.prefix = config['discord']['prefix']
        self.version = get_version()

    def _get_guild_config(self, guild_id):
        """Return the config for a guild, or None if not configured."""
        return self.guild_configs.get(guild_id)

    async def cog_check(self, ctx):
        """Permission check that applies to all commands in this cog"""
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
    async def list_jobs(self, ctx):
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

        for job in jobs:
            # Trim content if too long
            content = job.content
            if len(content) > 100:
                content = content[:97] + "..."

            embed.add_field(
                name=f"メッセージID: {job.id} - <t:{int(job.timestamp)}:F>",
                value=f"タイトル: {job.title}\n内容: {content}",
                inline=False
            )

        await ctx.reply(embed=embed)

    @commands.hybrid_command(
        name="cancel",
        description="Cancel a scheduled announcement"
    )
    async def cancel_job(self, ctx, message_id: str):
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
        embed.add_field(name=f"{prefix}cancel [メッセージID] または /cancel", value=Messages.Discord.CMD_CANCEL_DESC, inline=False)
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
