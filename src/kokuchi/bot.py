from __future__ import annotations

import asyncio
import logging
import warnings
import yaml
import os
import shutil
import sys
import argparse
from dotenv import load_dotenv

# Suppress SyntaxWarning from third-party vrchatapi package (invalid escape sequences in rest.py)
warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"vrchatapi\..*")

import discord
from discord.ext import commands, tasks
import traceback

from kokuchi.services.vrchat_api import VRChatAPI
from kokuchi.services.ai_processor import AIProcessor
from kokuchi.services.scheduler import Scheduler
from kokuchi.state.persistence import Persistence
from kokuchi.state.state_manager import StateManager
from kokuchi.cogs.announcement import AnnouncementCog
from kokuchi.cogs.admin import AdminCog
from kokuchi.cogs.auth import AuthCog
from kokuchi.cogs.general import GeneralCog
from kokuchi.common.messages import Messages

def ensure_config_exists() -> None:
    """Create config.yaml from template if it is missing, then exit so the user can fill it in."""
    if not os.path.exists('config.yaml'):
        if os.path.exists('config.yaml.template'):
            shutil.copy('config.yaml.template', 'config.yaml')
            print("config.yaml was created from config.yaml.template.")
            print("Please edit config.yaml and fill in your values, then restart the bot.")
        else:
            print("ERROR: config.yaml is missing and no config.yaml.template was found.")
        sys.exit(1)


def ensure_env_exists(env_file: str) -> None:
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
def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='VRChat Announce Discord Bot')
    parser.add_argument('--env', type=str, default='.env',
                      help='Environment file to load (default: .env)')
    return parser.parse_args()

# Load environment variables from specified file
def load_environment(env_file: str) -> bool:
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
    def __init__(self, config: dict, args: argparse.Namespace) -> None:
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

        # Validate and normalize config to ensure guilds list is present
        self._normalize_config()

        # Initialize components
        firestore_config = self.config.get('firestore', {})

        # Shared persistence for VRChat session (server_id is unused for shared ops)
        self.shared_persistence = Persistence(
            server_id='_shared',
            servers_collection=firestore_config.get('servers_collection', 'servers'),
            shared_collection=firestore_config.get('shared_collection', 'shared'),
            state_subcollection=firestore_config.get('state_subcollection', 'state'),
            database=firestore_config.get('database'),
        )

        # Per-guild persistences for announcement state
        self.guild_persistences = self._build_guild_persistences()

        self.vrchat_api = VRChatAPI(self.config['vrchat'], self.shared_persistence)
        self.scheduler = Scheduler(self.vrchat_api, self.config.get('scheduler', {}))
        self.ai_processor = AIProcessor(self.config['openrouter'])

        # Build per-guild config lookup for StateManager
        guild_configs = {}
        for guild_conf in self.config['discord'].get('guilds', []):
            guild_configs[guild_conf['guild_id']] = guild_conf

        self.state_manager = StateManager(
            scheduler=self.scheduler,
            vrchat_api=self.vrchat_api,
            guild_persistences=self.guild_persistences,
            guild_configs=guild_configs,
        )

        # Start heartbeat loop
        heartbeat_interval = self.config['vrchat'].get('heartbeat_interval', 60)
        if heartbeat_interval > 0:
            self.heartbeat_check.change_interval(minutes=heartbeat_interval)
            self.heartbeat_check.start()

    def _normalize_config(self) -> None:
        """Validate config and normalize all IDs to str."""
        discord_conf = self.config.get('discord', {})

        if 'guilds' not in discord_conf:
            logger.error(
                "Config is using old format (no 'guilds' key). "
                "Please update config.yaml to the new guilds format."
            )
            sys.exit(1)

        # Normalize admin_id to str
        if discord_conf.get('admin_id') is not None:
            discord_conf['admin_id'] = str(discord_conf['admin_id'])

        # Normalize per-guild IDs to str
        for guild_conf in discord_conf['guilds']:
            if guild_conf.get('guild_id') is None:
                logger.error("Each guild in config.yaml must have a guild_id.")
                sys.exit(1)
            if guild_conf.get('group_id') is None:
                logger.error("Each guild in config.yaml must have a group_id (VRChat group ID).")
                sys.exit(1)
            guild_conf['guild_id'] = str(guild_conf['guild_id'])
            guild_conf['channel_ids'] = [str(c) for c in guild_conf.get('channel_ids', [])]
            if guild_conf.get('admin_role_id') is not None:
                guild_conf['admin_role_id'] = str(guild_conf['admin_role_id'])

        self.config['discord'] = discord_conf

    def _build_guild_persistences(self) -> dict[str, Persistence]:
        """Build a mapping of guild_id (str) -> Persistence for each configured guild."""
        firestore_config = self.config.get('firestore', {})
        persistences = {}
        for guild_conf in self.config['discord']['guilds']:
            gid = guild_conf['guild_id']  # already str after normalization
            server_id = guild_conf.get('firestore_server_id', gid)
            persistences[gid] = Persistence(
                server_id=server_id,
                servers_collection=firestore_config.get('servers_collection', 'servers'),
                shared_collection=firestore_config.get('shared_collection', 'shared'),
                state_subcollection=firestore_config.get('state_subcollection', 'state'),
                database=firestore_config.get('database'),
            )
        return persistences

    def _load_env_variables(self) -> None:
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

    async def setup_hook(self) -> None:
        """Set up the bot's components"""
        try:
            # Add cogs
            await self.add_cog(AuthCog(self, self.config, self.vrchat_api))
            await self.add_cog(AnnouncementCog(self, self.config, self.ai_processor, self.state_manager, self.vrchat_api))
            await self.add_cog(AdminCog(self, self.config, self.state_manager))
            await self.add_cog(GeneralCog(self))

            await self.tree.sync()
            logger.info(Messages.Log.BOT_SETUP_SUCCESS)

        except Exception as e:
            logger.error(Messages.Log.BOT_SETUP_ERROR.format(e))
            logger.error(f"Stack trace:\n{traceback.format_exc()}")

    async def on_ready(self) -> None:
        """Called when the bot is ready and connected to Discord"""
        try:
            logger.info(Messages.Log.BOT_READY.format(self.user))

            # Send online message to the first channel of each configured guild
            for guild_conf in self.config['discord']['guilds']:
                channel_ids = guild_conf.get('channel_ids', [])
                if channel_ids:
                    channel = self.get_channel(int(channel_ids[0]))
                    if channel:
                        await channel.send(Messages.Discord.BOT_ONLINE)

            # Initialize VRChat API after bot is ready
            auth_result = await self.vrchat_api.initialize()
            if not auth_result.success:
                error_msg = auth_result.error or 'Unknown error'
                logger.error(Messages.Log.VRC_API_INIT_FAIL.format(error_msg))
                # DM the admin user about login failure
                admin_id = self.config['discord'].get('admin_id')
                if admin_id:
                    try:
                        admin_user = await self.fetch_user(int(admin_id))
                        await admin_user.send(Messages.Discord.LOGIN_FAIL.format(error_msg))
                    except Exception as dm_err:
                        logger.error(Messages.Log.LOGIN_FAIL_DM_ERROR.format(dm_err))
                return

            logger.info(Messages.Log.VRC_API_INIT_SUCCESS)

            # Send login confirmation to first channel of each guild, with group name
            display_name = auth_result.display_name or 'Unknown'
            for guild_conf in self.config['discord']['guilds']:
                channel_ids = guild_conf.get('channel_ids', [])
                if not channel_ids:
                    continue
                channel = self.get_channel(int(channel_ids[0]))
                if not channel:
                    continue

                group_id = guild_conf.get('group_id')
                group_name = group_id  # fallback to raw ID
                if group_id:
                    group_result = await self.vrchat_api.get_group(group_id)
                    if group_result.success:
                        group_name = group_result.data['name']

                await channel.send(Messages.Discord.LOGGED_IN.format(display_name, group_name))

        except Exception as e:
            logger.error(Messages.Log.VRC_API_INIT_ERROR.format(e))
            logger.error(f"Stack trace:\n{traceback.format_exc()}")

    async def on_message(self, message: discord.Message) -> None:
        """Handle incoming messages"""
        if message.author.bot:
            return

        await self.process_commands(message)

    @tasks.loop(minutes=60)
    async def heartbeat_check(self) -> None:
        """Periodically check VRChat authentication status"""
        if not hasattr(self, 'vrchat_api'):
            return

        try:
            await self.vrchat_api.check_auth_status()
        except Exception as e:
            logger.error(Messages.Log.HEARTBEAT_FAIL.format(e))

    @heartbeat_check.before_loop
    async def before_heartbeat(self) -> None:
        await self.wait_until_ready()

async def main() -> None:
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
