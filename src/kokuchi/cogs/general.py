from __future__ import annotations

import logging
import discord
from discord.ext import commands
from kokuchi.common.version import get_version
from kokuchi.common.messages import Messages
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kokuchi.services.vrchat_api import VRChatAPI
    from kokuchi.state.state_manager import StateManager

logger = logging.getLogger(__name__)

class GeneralCog(commands.Cog):
    def __init__(self, bot: commands.Bot, vrchat_api: VRChatAPI, state_manager: StateManager) -> None:
        self.bot = bot
        self.vrchat_api = vrchat_api
        self.state_manager = state_manager
        self.version = get_version()

    @commands.hybrid_command(name="ping", description="Check if the bot is alive and get its version")
    async def ping(self, ctx: commands.Context) -> None:
        lines = [f"Kokuchi-kun Version {self.version}"]

        if self.vrchat_api.authenticated and self.vrchat_api.current_user:
            display_name = self.vrchat_api.current_user.display_name
            lines.append(f"VRChat: {display_name} ✅")
        else:
            lines.append("VRChat: not logged in ❌")

        if ctx.guild:
            gctx = self.state_manager.get_guild_context(str(ctx.guild.id))
            group_id = gctx.group_id if gctx else None
            if group_id:
                group_result = await self.vrchat_api.get_group(group_id)
                if group_result.success:
                    lines.append(f"Group: {group_result.data['name']}")

        await ctx.reply("\n".join(lines))

    @commands.hybrid_command(name="version", description="Get the current bot version")
    async def version_cmd(self, ctx: commands.Context) -> None:
        await ctx.reply(f"Kokuchi-kun Version {self.version}")

    @commands.command(name="listall")
    async def list_all_jobs(self, ctx: commands.Context) -> None:
        """DM-only: list all scheduled jobs across all guilds (bot admin only)"""
        if not isinstance(ctx.channel, discord.DMChannel):
            return

        admin_id = self.bot.config.get('discord', {}).get('admin_id')
        if not admin_id or str(ctx.author.id) != admin_id:
            await ctx.reply("このコマンドはBotの管理者専用です。")
            return

        jobs = self.state_manager.scheduler.list_jobs()
        if not jobs:
            await ctx.reply("予約されている告知はありません。")
            return

        embed = discord.Embed(title="全サーバー 予約告知一覧", color=discord.Color.blue())
        for job in jobs:
            content = job.content
            if len(content) > 100:
                content = content[:97] + "..."
            guild = self.bot.get_guild(int(job.guild_id)) if job.guild_id else None
            guild_name = guild.name if guild else job.guild_id
            embed.add_field(
                name=f"**{job.title}** — <t:{int(job.timestamp)}:F>",
                value=f"サーバー: {guild_name}\nID: {job.id}\n{content}",
                inline=False
            )
        await ctx.reply(embed=embed)

    @commands.hybrid_command(name="reload", description="Reload config and prompt (bot admin only)")
    async def reload_config(self, ctx: commands.Context) -> None:
        """Reload config.yaml and prompt file without restarting the bot."""
        admin_id = self.bot.config.get('discord', {}).get('admin_id')
        if not admin_id or str(ctx.author.id) != admin_id:
            await ctx.reply(Messages.Discord.NO_PERMISSION, ephemeral=True)
            return

        try:
            self.bot.reload_config()
            await ctx.reply("設定とプロンプトを再読み込みしました。 ✅")
            logger.info(f"Config reloaded by admin {ctx.author.id}/{ctx.author.name}")
        except Exception as e:
            logger.error(f"Failed to reload config: {e}", exc_info=True)
            await ctx.reply(f"設定の再読み込みに失敗しました: {e}")

    @commands.hybrid_command(name="help", description="Display command help")
    async def help_command(self, ctx: commands.Context) -> None:
        prefix = self.bot.command_prefix
        embed = discord.Embed(
            title=Messages.Discord.CMD_LIST_TITLE,
            color=discord.Color.blue()
        )
        embed.add_field(name=f"{prefix}list または /list", value=Messages.Discord.CMD_LIST_DESC, inline=False)
        embed.add_field(name=f"{prefix}cancel [メッセージID] または /cancel", value=Messages.Discord.CMD_CANCEL_DESC, inline=False)
        embed.add_field(name=f"{prefix}reload または /reload", value=Messages.Discord.CMD_RELOAD_DESC, inline=False)
        embed.add_field(name=f"{prefix}help または /help", value=Messages.Discord.CMD_HELP_DESC, inline=False)
        embed.set_footer(text=f"Version: {self.version} | マニュアル: https://inkuxuan.github.io/kokuchi-kun/")
        await ctx.reply(embed=embed)
