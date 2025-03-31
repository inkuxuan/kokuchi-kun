import asyncio
import logging
import yaml
import os
import argparse
from dotenv import load_dotenv
import discord
from discord.ext import commands

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
    def __init__(self, config, args):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.reactions = True
        intents.members = True
        
        super().__init__(
            command_prefix=config['discord']['prefix'],
            intents=intents,
            help_command=None  # Disable the default help command
        )
        
        self.config = config
        self.args = args
        
        # Add sensitive environment variables to config
        self._load_env_variables()
        
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
        # Initialize VRChat API
        self.vrchat_api = VRChatAPI(self.config['vrchat'])
        auth_result = self.vrchat_api.initialize()
        
        if not auth_result.get('success', False):
            logger.warning(f"VRChat authentication failed: {auth_result.get('error', 'Unknown error')}")
            logger.warning("Bot will start, but VRChat posting will not work until authentication is successful")
        else:
            logger.info(f"Authenticated with VRChat as {auth_result.get('display_name', 'Unknown')}")
        
        # Initialize AI Processor
        self.ai_processor = AIProcessor(self.config['openrouter'])
        
        # Initialize Scheduler
        self.scheduler = Scheduler(self.vrchat_api)
        
        # Add cogs
        await self.add_cog(AnnouncementCog(self, self.config, self.ai_processor, self.scheduler))
        await self.add_cog(AdminCog(self, self.config, self.scheduler))
        
        # Always sync commands with Discord
        logger.info("Syncing application commands with Discord...")
        await self.tree.sync()
        logger.info("Command synchronization complete")
        
        logger.info("Bot setup complete")
    
    async def on_ready(self):
        logger.info(f"Logged in as {self.user.name} ({self.user.id})")
        logger.info(f"Monitoring channel IDs: {', '.join(map(str, self.config['discord']['channel_ids']))}")

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
        logger.error(f"Failed to load config: {e}")
        return
        
    # Create and run bot
    bot = VRChatAnnounceBot(config, args)
    
    try:
        logger.info("Starting bot...")
        if not bot.config['discord']['token']:
            logger.error("Discord token not found in environment variables!")
            return
        await bot.start(bot.config['discord']['token'])
    except Exception as e:
        logger.error(f"Bot error: {e}")
    finally:
        # Cleanup
        if hasattr(bot, 'scheduler'):
            bot.scheduler.shutdown()
        if hasattr(bot, 'vrchat_api'):
            bot.vrchat_api.close()

if __name__ == "__main__":
    asyncio.run(main()) 