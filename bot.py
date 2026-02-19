import asyncio
import logging
import yaml
import os
import shutil
import sys
import argparse
from dotenv import load_dotenv
import discord
from discord.ext import commands, tasks
import traceback

from utils.vrchat_api import VRChatAPI
from utils.ai_processor import AIProcessor
from utils.scheduler import Scheduler
from utils.persistence import Persistence
from cogs.announcement import AnnouncementCog
from cogs.admin import AdminCog
from cogs.general import GeneralCog
from utils.messages import Messages

def ensure_config_exists():
    """Create config.yaml from template if it is missing, then exit so the user can fill it in."""
    if not os.path.exists('config.yaml'):
        if os.path.exists('config.yaml.template'):
            shutil.copy('config.yaml.template', 'config.yaml')
            print("config.yaml was created from config.yaml.template.")
            print("Please edit config.yaml and fill in your values, then restart the bot.")
        else:
            print("ERROR: config.yaml is missing and no config.yaml.template was found.")
        sys.exit(1)


def ensure_env_exists(env_file):
    """Create the env file from .prd.env.template if it is missing, then exit so the user can fill it in."""
    if not os.path.exists(env_file):
        template = '.prd.env.template'
        if os.path.exists(template):
            shutil.copy(template, env_file)
            print(f"{env_file} was created from {template}.")
            print(f"Please edit {env_file} and fill in your credentials, then restart the bot.")
        else:
            print(f"ERROR: {env_file} is missing and no {template} was found.")
        sys.exit(1)


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

        # Add sensitive environment variables to config
        self._load_env_variables()
        
        # Initialize components
        firestore_config = self.config.get('firestore', {})
        self.persistence = Persistence(
            server_id=firestore_config.get('server_id', 'default'),
            servers_collection=firestore_config.get('servers_collection', 'servers'),
            shared_collection=firestore_config.get('shared_collection', 'shared'),
            state_subcollection=firestore_config.get('state_subcollection', 'state'),
        )
        self.vrchat_api = VRChatAPI(self.config['vrchat'], self.persistence)
        self.scheduler = Scheduler(self.vrchat_api)
        self.ai_processor = AIProcessor(self.config['openrouter'])

        # Start heartbeat loop
        heartbeat_interval = self.config['vrchat'].get('heartbeat_interval', 60)
        if heartbeat_interval > 0:
            self.heartbeat_check.change_interval(minutes=heartbeat_interval)
            self.heartbeat_check.start()
        
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
            # Add cogs (AnnouncementCog sets up its own OTP callback)
            await self.add_cog(AnnouncementCog(self, self.config, self.ai_processor, self.scheduler, self.persistence, self.vrchat_api))
            await self.add_cog(AdminCog(self, self.config, self.scheduler))
            await self.add_cog(GeneralCog(self))

            await self.tree.sync()
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
                await channel.send(Messages.Discord.BOT_ONLINE)

            # Initialize VRChat API after bot is ready
            auth_result = await self.vrchat_api.initialize()
            if not auth_result.success:
                logger.error(Messages.Log.VRC_API_INIT_FAIL.format(auth_result.error or 'Unknown error'))
                return

            logger.info(Messages.Log.VRC_API_INIT_SUCCESS)
            if channel:
                await channel.send(Messages.Discord.LOGGED_IN.format(auth_result.display_name or 'Unknown'))
            
        except Exception as e:
            logger.error(Messages.Log.VRC_API_INIT_ERROR.format(e))
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
    
    async def on_message(self, message):
        """Handle incoming messages"""
        if message.author.bot:
            return

        await self.process_commands(message)

    @tasks.loop(minutes=60)
    async def heartbeat_check(self):
        """Periodically check VRChat authentication status"""
        if not hasattr(self, 'vrchat_api'):
            return

        try:
            await self.vrchat_api.check_auth_status()
        except Exception as e:
            logger.error(Messages.Log.HEARTBEAT_FAIL.format(e))

    @heartbeat_check.before_loop
    async def before_heartbeat(self):
        await self.wait_until_ready()

async def main():
    # Parse command-line arguments
    args = parse_arguments()

    # Ensure required files exist before doing anything else
    ensure_env_exists(args.env)
    ensure_config_exists()

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
