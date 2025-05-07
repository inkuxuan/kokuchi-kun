import asyncio
import logging
import yaml
import os
import argparse
from dotenv import load_dotenv
import discord
from discord.ext import commands
import traceback
import uuid

from utils.vrchat_api import VRChatAPI
from utils.ai_processor import AIProcessor
from utils.scheduler import Scheduler
from cogs.announcement import AnnouncementCog
from cogs.admin import AdminCog

# Parse command-line arguments
def parse_arguments():
    parser = argparse.ArgumentParser(description='VRChat Announce Discord Bot')
    parser.add_argument('--env', type=str, default='.env',
                      help='Environment file to load (default: .env)')
    return parser.parse_args()

# Load environment variables from specified file
def load_environment(env_file):
    if os.path.exists(env_file):
        logger.info(f"Loading environment from: {env_file}")
        load_dotenv(env_file)
        return True
    else:
        logger.warning(f"Environment file not found: {env_file}, using default environment")
        load_dotenv()
        return False

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log")
    ]
)
logger = logging.getLogger(__name__)

class VRChatAnnounceBot(commands.Bot):
    def __init__(self, config):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        
        super().__init__(
            command_prefix=config['discord']['prefix'],
            intents=intents
        )
        
        self.config = config
        self.otp_requests = {}  # Store OTP requests and their futures
        
        # Initialize components
        self.vrchat_api = VRChatAPI(config['vrchat'])
        self.scheduler = Scheduler(self.vrchat_api)
        self.ai_processor = AIProcessor(config['openrouter'])
        
    async def setup_hook(self):
        """Set up the bot's components"""
        try:
            # Set up OTP callback before initializing VRChat API
            self.vrchat_api.set_otp_callback(self._request_otp)
            
            # Initialize VRChat API
            auth_result = await self.vrchat_api.initialize()
            if not auth_result.get('success', False):
                logger.error(f"Failed to initialize VRChat API: {auth_result.get('error', 'Unknown error')}")
                return
            
            # Add cogs
            await self.add_cog(AnnouncementCog(self, self.config, self.ai_processor, self.scheduler))
            await self.add_cog(AdminCog(self, self.config, self.scheduler))
            
            logger.info("Bot setup completed successfully")
            
        except Exception as e:
            logger.error(f"Error during bot setup: {e}")
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
    
    async def _request_otp(self, otp_type):
        """Request OTP from admin through Discord"""
        # Get the first channel from config
        channel = self.get_channel(self.config['discord']['channel_ids'][0])
        if not channel:
            logger.error("Could not find channel for OTP request")
            return None
            
        # Create a unique request ID
        request_id = str(uuid.uuid4())
        
        # Create a future to wait for the response
        future = asyncio.Future()
        self.otp_requests[request_id] = future
        
        # Send OTP request message
        role_mention = f"<@&{self.config['discord']['admin_role_id']}>"
        message = await channel.send(
            f"{role_mention} VRChatの認証に{otp_type}が必要です。"
            f"認証コードを入力してください。"
        )
        
        try:
            # Wait for response with timeout
            otp = await asyncio.wait_for(future, timeout=300)  # 5 minute timeout
            return otp
        except asyncio.TimeoutError:
            await message.edit(content=f"{role_mention} OTPリクエストがタイムアウトしました。")
            return None
        finally:
            # Clean up
            if request_id in self.otp_requests:
                del self.otp_requests[request_id]
    
    async def on_message(self, message):
        """Handle incoming messages"""
        # Check for OTP response
        if message.author.bot:
            return
            
        # Check if this is an OTP response
        if message.channel.id in self.config['discord']['channel_ids']:
            # Check if the user has admin role
            member = await message.guild.fetch_member(message.author.id)
            if member and self.config['discord']['admin_role_id'] in [role.id for role in member.roles]:
                # Check if this is a response to an OTP request
                for request_id, future in list(self.otp_requests.items()):
                    if not future.done():
                        # Set the OTP value
                        future.set_result(message.content.strip())
                        # Delete the message for security
                        await message.delete()
                        return
        
        # Process other messages
        await self.process_commands(message)

async def main():
    # Load configuration
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    # Create and start the bot
    bot = VRChatAnnounceBot(config)
    try:
        await bot.start(config['discord']['token'])
    except Exception as e:
        logger.error(f"Error starting bot: {e}")
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
    finally:
        # Clean up
        if hasattr(bot, 'vrchat_api'):
            bot.vrchat_api.close()

if __name__ == "__main__":
    asyncio.run(main()) 