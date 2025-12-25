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
from utils.messages import Messages

# Parse command-line arguments
def parse_arguments():
    parser = argparse.ArgumentParser(description='VRChat Announce Discord Bot')
    parser.add_argument('--env', type=str, default='.env',
                      help='Environment file to load (default: .env)')
    return parser.parse_args()

# Load environment variables from specified file
def load_environment(env_file):
    if os.path.exists(env_file):
        logger.info(Messages.Log.LOADING_ENV.format(env_file))
        load_dotenv(env_file)
        return True
    else:
        logger.warning(Messages.Log.ENV_NOT_FOUND.format(env_file))
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
    def __init__(self, config, args):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        
        super().__init__(
            command_prefix=config['discord']['prefix'],
            intents=intents,
            help_command=None  # Disable default help command
        )
        
        self.config = config
        self.args = args
        self.otp_requests = {}  # Store OTP requests and their futures
        
        # Add sensitive environment variables to config
        self._load_env_variables()
        
        # Initialize components
        self.vrchat_api = VRChatAPI(self.config['vrchat'])
        self.scheduler = Scheduler(self.vrchat_api)
        self.ai_processor = AIProcessor(self.config['openrouter'])
        
    def _load_env_variables(self):
        """Load sensitive data from environment variables into config"""
        # Discord
        self.config['discord']['token'] = os.getenv('DISCORD_TOKEN')
        
        # OpenRouter - only load the API key, keep model in config
        if 'openrouter' not in self.config:
            self.config['openrouter'] = {}
        self.config['openrouter']['api_key'] = os.getenv('OPENROUTER_API_KEY')
        # Model remains in config.yaml
        
        # VRChat
        if 'vrchat' not in self.config:
            self.config['vrchat'] = {}
        self.config['vrchat']['username'] = os.getenv('VRCHAT_USERNAME')
        self.config['vrchat']['password'] = os.getenv('VRCHAT_PASSWORD')
        # group_id is now loaded from config.yaml
        
    async def setup_hook(self):
        """Set up the bot's components"""
        try:
            # Set up OTP callback before initializing VRChat API
            self.vrchat_api.set_otp_callback(self._request_otp)
            
            # Add cogs first
            await self.add_cog(AnnouncementCog(self, self.config, self.ai_processor, self.scheduler))
            await self.add_cog(AdminCog(self, self.config, self.scheduler))
            
            logger.info(Messages.Log.BOT_SETUP_SUCCESS)
            
        except Exception as e:
            logger.error(Messages.Log.BOT_SETUP_ERROR.format(e))
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
    
    async def on_ready(self):
        """Called when the bot is ready and connected to Discord"""
        try:
            logger.info(Messages.Log.BOT_READY.format(self.user))
            
            # Send online message
            channel = self.get_channel(self.config['discord']['channel_ids'][0])
            if channel:
                await channel.send("Bot is online! 🟢")

            # Initialize VRChat API after bot is ready
            auth_result = await self.vrchat_api.initialize()
            if not auth_result.get('success', False):
                error_msg = auth_result.get('error', 'Unknown error')
                logger.error(Messages.Log.VRC_API_INIT_FAIL.format(error_msg))
                return
                
            logger.info(Messages.Log.VRC_API_INIT_SUCCESS)
            if channel:
                display_name = auth_result.get('display_name', 'Unknown')
                await channel.send(f"Logged into VRChat as {display_name} ✅")
            
        except Exception as e:
            logger.error(Messages.Log.VRC_API_INIT_ERROR.format(e))
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
    
    async def _request_otp(self, otp_type):
        """Request OTP from admin through Discord"""
        # Get the first channel from config
        channel = self.get_channel(self.config['discord']['channel_ids'][0])
        if not channel:
            logger.error(Messages.Log.OTP_CHANNEL_NOT_FOUND)
            return None
            
        # Create a unique request ID
        request_id = str(uuid.uuid4())
        
        # Create a future to wait for the response
        future = asyncio.Future()
        self.otp_requests[request_id] = future
        
        # Send OTP request message with role mention
        role_mention = f"<@&{self.config['discord']['admin_role_id']}>"
        message = await channel.send(Messages.Discord.OTP_REQUEST.format(role_mention=role_mention, otp_type=otp_type))
        
        try:
            # Wait for response with timeout
            otp = await asyncio.wait_for(future, timeout=300)  # 5 minute timeout
            if otp:
                # Edit the original message to remove the mention
                await message.edit(content=Messages.Discord.OTP_REQUEST_EDITED.format(otp_type=otp_type))
            return otp
        except asyncio.TimeoutError:
            await message.edit(content=Messages.Discord.OTP_TIMEOUT.format(role_mention=role_mention))
            return None
        finally:
            # Clean up
            if request_id in self.otp_requests:
                del self.otp_requests[request_id]
    
    async def on_message(self, message):
        """Handle incoming messages"""
        # Ignore bot messages
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
        
        # Process all commands regardless of mentions
        # This allows admin commands like !list and !cancel to work without a mention
        # Note: Announcement requests still require a mention as that's handled in AnnouncementCog
        await self.process_commands(message)

async def main():
    # Parse command-line arguments
    args = parse_arguments()
    
    # Load environment from specified file
    load_environment(args.env)
    
    # Load configuration
    try:
        with open('config.yaml', 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except Exception as e:
        logger.error(Messages.Log.CONFIG_LOAD_FAIL.format(e))
        return
    
    # Create and start the bot
    bot = VRChatAnnounceBot(config, args)
    try:
        if not bot.config['discord']['token']:
            logger.error(Messages.Log.DISCORD_TOKEN_NOT_FOUND)
            return
        await bot.start(bot.config['discord']['token'])
    except Exception as e:
        logger.error(Messages.Log.BOT_START_ERROR.format(e))
        logger.error(f"Stack trace:\n{traceback.format_exc()}")
    finally:
        # Clean up
        if hasattr(bot, 'vrchat_api'):
            bot.vrchat_api.close()

if __name__ == "__main__":
    asyncio.run(main())
