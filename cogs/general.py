import discord
from discord.ext import commands
from utils.version import get_version

class GeneralCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.version = get_version()

    @commands.hybrid_command(name="ping", description="Check if the bot is alive and get its version")
    async def ping(self, ctx):
        await ctx.reply(f"VSPC-bot Version {self.version}")

    @commands.hybrid_command(name="version", description="Get the current bot version")
    async def version(self, ctx):
        await ctx.reply(f"VSPC-bot Version {self.version}")
