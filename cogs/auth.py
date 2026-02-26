import logging
import uuid
import asyncio
import discord
from discord.ext import commands
from utils.messages import Messages

logger = logging.getLogger(__name__)


class AuthCog(commands.Cog):
    """Handles VRChat authentication concerns (OTP requests via DM).

    This cog is responsible for bot-level admin interactions — specifically,
    relaying OTP codes from the configured admin user to the VRChat API.
    It is separate from AdminCog, which handles per-guild server admin commands.
    """

    def __init__(self, bot, config, vrchat_api):
        self.bot = bot
        self.vrchat_api = vrchat_api

        # Bot-level admin user ID (receives OTP DMs)
        self.admin_id = config['discord'].get('admin_id')

        self.otp_requests = {}  # request_id -> {'future': Future, 'message_id': int}

        # Set up OTP callback for VRChat API
        self.vrchat_api.set_otp_callback(self._request_otp)

    async def _request_otp(self, otp_type):
        """Request OTP from the configured admin user via DM"""
        if not self.admin_id:
            logger.error(Messages.Log.OTP_DM_USER_NOT_CONFIGURED)
            return None

        try:
            user = await self.bot.fetch_user(int(self.admin_id))
        except Exception:
            logger.error(Messages.Log.OTP_DM_USER_NOT_FOUND)
            return None

        # Create a unique request ID
        request_id = str(uuid.uuid4())

        # Create a future to wait for the response
        future = asyncio.Future()

        # Open DM channel and send request
        dm_channel = await user.create_dm()
        message = await dm_channel.send(Messages.Discord.OTP_REQUEST_DM.format(otp_type=otp_type))

        # Store request with the sent message ID for reply-to verification
        self.otp_requests[request_id] = {'future': future, 'message_id': message.id}

        try:
            # Wait for response with timeout
            otp = await asyncio.wait_for(future, timeout=300)  # 5 minute timeout
            return otp
        except asyncio.TimeoutError:
            await message.edit(content=Messages.Discord.OTP_TIMEOUT_DM)
            return None
        finally:
            # Clean up
            if request_id in self.otp_requests:
                del self.otp_requests[request_id]

    @commands.Cog.listener()
    async def on_message(self, message):
        """Handle DM messages for OTP responses (reply-to only)"""
        if message.author.bot:
            return

        # Only handle DMs from the configured admin
        if not isinstance(message.channel, discord.DMChannel):
            return

        if not self.admin_id or str(message.author.id) != self.admin_id:
            return

        # Only accept reply-to messages that match a pending OTP request
        if not message.reference or not message.reference.message_id:
            return

        for request_id, request in list(self.otp_requests.items()):
            if not request['future'].done() and message.reference.message_id == request['message_id']:
                request['future'].set_result(message.content.strip())
                return
