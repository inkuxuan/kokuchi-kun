import discord
from discord.ext import commands
from kokuchi.common.version import get_version

class GeneralCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.version = get_version()

    @commands.hybrid_command(name="ping", description="Check if the bot is alive and get its version")
    async def ping(self, ctx: commands.Context) -> None:
        await ctx.reply(f"Kokuchi-kun Version {self.version}")

    @commands.hybrid_command(name="version", description="Get the current bot version")
    async def version(self, ctx: commands.Context) -> None:
        await ctx.reply(f"Kokuchi-kun Version {self.version}")
