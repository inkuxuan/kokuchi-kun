from __future__ import annotations

import discord
from discord.ext import commands
from kokuchi.common.version import get_version
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kokuchi.services.vrchat_api import VRChatAPI
    from kokuchi.state.state_manager import StateManager

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
