import os
import pytest
import discord
from discord.ext import commands
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv(".test.env")

# Configuration (Replace with environment variables in production)
TOKEN = os.getenv("DISCORD_TEST_TOKEN")  # Use a test bot token
TEST_CHANNEL_ID = int(os.getenv("DISCORD_TEST_CHANNEL_ID", "0"))  # Channel to check access

class TestDiscordAuth:
    @classmethod
    def setup_class(cls):
        """Set up the event loop for all tests."""
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)

    @classmethod
    def teardown_class(cls):
        """Clean up after all tests."""
        cls.loop.close()

    def setup_method(self):
        """Create a fresh bot instance for each test."""
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        self.bot = commands.Bot(command_prefix="!", intents=intents)
        
    def teardown_method(self):
        """Clean up after each test."""
        # Bot cleanup is handled within each test

    def test_bot_authentication(self):
        """Test if the bot can authenticate with Discord."""
        if not TOKEN:
            pytest.skip("No Discord token provided")
        
        # Create an event for signaling when the bot is ready
        ready_event = asyncio.Event()
        
        @self.bot.event
        async def on_ready():
            ready_event.set()
        
        async def run_test():
            login_task = None
            try:
                # Start the bot
                login_task = asyncio.create_task(self.bot.start(TOKEN))
                
                # Wait for the bot to be ready
                await asyncio.wait_for(ready_event.wait(), timeout=30)
                
                # Check if the bot is authenticated
                assert self.bot.is_ready(), "Bot failed to authenticate with Discord"
                print(f"✅ Successfully authenticated as {self.bot.user.name}")
                
                # Check channel access
                channel = self.bot.get_channel(TEST_CHANNEL_ID)
                assert channel is not None, f"Bot cannot see channel with ID {TEST_CHANNEL_ID}"
                print(f"✅ Successfully accessed channel: {channel.name}")
                
            except asyncio.TimeoutError:
                pytest.fail("Authentication timed out")
            finally:
                # Ensure the bot is closed
                if login_task and not login_task.done():
                    login_task.cancel()
                
                if not self.bot.is_closed():
                    await self.bot.close()
        
        # Run the async test in the event loop
        self.loop.run_until_complete(run_test())

    def test_channel_permissions(self):
        """Test if the bot has correct permissions in the test channel."""
        if not TOKEN:
            pytest.skip("No Discord token provided")
        
        # Create an event for signaling when the bot is ready
        ready_event = asyncio.Event()
        
        @self.bot.event
        async def on_ready():
            ready_event.set()
        
        async def run_test():
            login_task = None
            try:
                # Start the bot
                login_task = asyncio.create_task(self.bot.start(TOKEN))
                
                # Wait for the bot to be ready
                await asyncio.wait_for(ready_event.wait(), timeout=30)
                
                # Get the channel
                channel = self.bot.get_channel(TEST_CHANNEL_ID)
                assert channel is not None, f"Channel {TEST_CHANNEL_ID} not found"
                
                # Check permissions
                bot_permissions = channel.permissions_for(channel.guild.me)
                assert bot_permissions.send_messages, "Bot cannot send messages in the test channel"
                assert bot_permissions.read_messages, "Bot cannot read messages in the test channel"
                print(f"✅ Bot has proper permissions in channel: {channel.name}")
                
            finally:
                # Ensure the bot is closed
                if login_task and not login_task.done():
                    login_task.cancel()
                
                if not self.bot.is_closed():
                    await self.bot.close()
        
        # Run the async test in the event loop
        self.loop.run_until_complete(run_test()) 