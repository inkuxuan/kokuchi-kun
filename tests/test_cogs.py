import pytest
import discord
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import time

from kokuchi.cogs.admin import AdminCog
from kokuchi.cogs.announcement import AnnouncementCog
from kokuchi.cogs.general import GeneralCog
from kokuchi.state.state_manager import StateManager
from kokuchi.common.messages import Messages
from kokuchi.common.models import AIProcessingResult, JobData

# Guild ID used consistently across all tests
TEST_GUILD_ID = 111111111
TEST_CHANNEL_ID = 987654321
TEST_ADMIN_ROLE_ID = 111222333

class TestCogs:
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 123456789
        bot.user.mentioned_in = MagicMock(return_value=True)
        bot.get_channel = MagicMock()
        bot.get_cog = MagicMock(return_value=None)
        return bot

    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration using the new guilds format with str IDs."""
        return {
            'discord': {
                'prefix': '!',
                'seen_reaction_emoji': "👀",
                'approval_reaction_emoji': "👍",
                'fast_forward_emoji': "⏩",
                'guilds': [{
                    'guild_id': str(TEST_GUILD_ID),
                    'group_id': 'grp_test',
                    'enabled': True,
                    'channel_ids': [str(TEST_CHANNEL_ID)],
                    'admin_role_id': str(TEST_ADMIN_ROLE_ID),
                    'firestore_server_id': 'test',
                }]
            }
        }

    @pytest.fixture
    def mock_scheduler(self):
        """Create a mock scheduler."""
        scheduler = MagicMock()
        scheduler.misfire_grace_time = 3600
        # Set up mock job list
        scheduler.list_jobs.return_value = [
            JobData(
                id='job1',
                title='Test Announcement',
                content='This is a test announcement content.',
                formatted_date_time='2023-03-27 12:00:00',
                timestamp=1679918400,
                message_id='123456789',
                guild_id=str(TEST_GUILD_ID),
            )
        ]
        scheduler.cancel_job = MagicMock(return_value=True)
        scheduler.cancel_job_by_message_id = MagicMock(return_value=True)
        scheduler.get_job = MagicMock(return_value=JobData(
            id='job1',
            title='Test Announcement',
            content='This is a test announcement content.',
            formatted_date_time='2023-03-27 12:00:00',
            timestamp=1679918400,
            message_id='123456789',
            guild_id=str(TEST_GUILD_ID),
        ))
        scheduler.get_job_by_message_id = MagicMock(return_value=None)
        scheduler.schedule_announcement = AsyncMock(return_value='new_job_id')
        scheduler.restore_jobs = MagicMock(return_value=(0, []))
        scheduler.get_jobs_data = MagicMock(return_value=[])
        scheduler.jobs = MagicMock()
        scheduler.jobs.values = MagicMock(return_value=[])
        return scheduler

    @pytest.fixture
    def mock_ai_processor(self):
        """Create a mock AI processor."""
        processor = MagicMock()
        # Make sure timestamp is in the future relative to time.time()
        # Using a very large timestamp to be safe
        processor.process_announcement = AsyncMock(return_value=AIProcessingResult(
            success=True,
            timestamp=4102444800, # 2100-01-01 00:00:00
            announcement_timestamp=4102444800,
            event_start_timestamp=4102444800 + 3600,
            event_end_timestamp=4102444800 + 7200,
            title='AI Processed Title',
            content='AI processed content for VRChat announcement',
            formatted_date_time='2100-01-01 00:00:00',
        ))
        return processor

    @pytest.fixture
    def mock_persistence(self):
        """Create a mock persistence object."""
        persistence = MagicMock()
        persistence.load_data = AsyncMock(return_value=[])  # Default for lists
        persistence.save_data = AsyncMock(return_value=True)
        persistence.load_shared = AsyncMock(return_value={})
        persistence.save_shared = AsyncMock(return_value=True)
        persistence.save_announcement = AsyncMock(return_value=True)
        persistence.load_announcements = AsyncMock(return_value={})
        return persistence

    @pytest.fixture
    def mock_vrchat_api(self):
        """Create a mock VRChat API."""
        api = MagicMock()
        api.set_otp_callback = MagicMock()
        api.delete_group_calendar_event = AsyncMock()
        return api

    @pytest.fixture
    def mock_state_manager(self, mock_scheduler, mock_vrchat_api, mock_persistence, mock_config):
        """Create a StateManager instance with mocks."""
        guild_persistences = {str(TEST_GUILD_ID): mock_persistence}
        guild_configs = {}
        for guild_conf in mock_config['discord'].get('guilds', []):
            guild_configs[guild_conf['guild_id']] = guild_conf
        return StateManager(
            scheduler=mock_scheduler,
            vrchat_api=mock_vrchat_api,
            guild_persistences=guild_persistences,
            guild_configs=guild_configs,
        )

    @pytest.fixture
    def admin_cog(self, mock_bot, mock_config, mock_state_manager):
        """Create an AdminCog instance with mocks."""
        return AdminCog(mock_bot, mock_config, mock_state_manager)

    @pytest.fixture
    def announcement_cog(self, mock_bot, mock_config, mock_ai_processor, mock_state_manager, mock_vrchat_api):
        """Create an AnnouncementCog instance with mocks."""
        cog = AnnouncementCog(mock_bot, mock_config, mock_ai_processor, mock_state_manager, mock_vrchat_api)
        return cog

    @pytest.fixture
    def mock_message(self):
        """Create a mock message."""
        message = AsyncMock()
        message.author = MagicMock()
        message.author.bot = False
        message.author.id = 987123456
        message.author.name = "Test User"
        message.author.mention = "<@987123456>"

        message.channel = MagicMock()
        message.channel.id = TEST_CHANNEL_ID

        message.guild = MagicMock()
        message.guild.id = TEST_GUILD_ID
        message.guild.fetch_member = AsyncMock()

        message.add_reaction = AsyncMock()
        message.reply = AsyncMock()
        message.id = 123456789
        message.content = "Test Message"

        return message

    @pytest.fixture
    def mock_context(self, mock_message, mock_bot):
        """Create a mock context."""
        ctx = MagicMock()
        ctx.message = mock_message
        ctx.author = mock_message.author
        ctx.channel = mock_message.channel
        ctx.guild = mock_message.guild
        ctx.bot = mock_bot
        ctx.send = AsyncMock()
        ctx.reply = AsyncMock()
        return ctx

    @pytest.fixture
    def mock_admin_member(self):
        """Create a mock member with admin role."""
        member = MagicMock()
        admin_role = MagicMock()
        admin_role.id = TEST_ADMIN_ROLE_ID
        member.roles = [admin_role]
        return member

    @pytest.fixture
    def mock_normal_member(self):
        """Create a mock member without admin role."""
        member = MagicMock()
        normal_role = MagicMock()
        normal_role.id = 444555666
        member.roles = [normal_role]
        return member

    # AdminCog Tests

    @pytest.mark.asyncio
    async def test_admin_list_command(self, admin_cog, mock_context, mock_admin_member):
        """Test the list command in AdminCog."""
        mock_context.author = mock_admin_member

        await admin_cog.list_jobs(admin_cog, mock_context)

        # Verify scheduler list_jobs was called via state_manager
        admin_cog.state_manager.scheduler.list_jobs.assert_called_once()

        assert mock_context.send.called or mock_context.reply.called

    @pytest.mark.asyncio
    async def test_admin_cancel_command(self, admin_cog, mock_context, mock_admin_member, mock_persistence):
        """Test the cancel command in AdminCog."""
        mock_context.author = mock_admin_member

        await admin_cog.cancel_job(admin_cog, mock_context, "job1")

        # Verify cancel_job was called with the exact job_id
        admin_cog.state_manager.scheduler.cancel_job.assert_called_with("job1")

        # Verify persistence save was called
        mock_persistence.save_announcement.assert_called()

        # Verify success message
        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_CANCELLED.format("job1") in args[0]

    @pytest.mark.asyncio
    async def test_admin_cancel_cross_guild_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling a job belonging to a different guild is rejected."""
        mock_context.author = mock_admin_member

        other_guild_id = 999999999
        mock_context.guild.id = other_guild_id

        await admin_cog.cancel_job(admin_cog, mock_context, "job1")

        admin_cog.state_manager.scheduler.cancel_job_by_message_id.assert_not_called()

        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_NOT_FOUND.format("job1") in args[0]

    @pytest.mark.asyncio
    async def test_admin_cancel_nonexistent_job_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling a nonexistent job is rejected."""
        mock_context.author = mock_admin_member

        admin_cog.state_manager.scheduler.get_job = MagicMock(return_value=None)

        await admin_cog.cancel_job(admin_cog, mock_context, "nonexistent_job")

        admin_cog.state_manager.scheduler.cancel_job_by_message_id.assert_not_called()

        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_NOT_FOUND.format("nonexistent_job") in args[0]

    @pytest.mark.asyncio
    async def test_admin_cancel_success_job_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling a successfully completed job is rejected."""
        mock_context.author = mock_admin_member

        admin_cog.state_manager.scheduler.get_job = MagicMock(return_value=JobData(
            id='job_done',
            title='Done Job',
            content='Content',
            formatted_date_time='2023-03-27 12:00:00',
            timestamp=1679918400,
            message_id='123456789',
            guild_id=str(TEST_GUILD_ID),
            status='success',
        ))

        await admin_cog.cancel_job(admin_cog, mock_context, "job_done")

        admin_cog.state_manager.scheduler.cancel_job_by_message_id.assert_not_called()
        mock_context.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_cancel_cancelled_job_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling an already-cancelled job is rejected."""
        mock_context.author = mock_admin_member

        admin_cog.state_manager.scheduler.get_job = MagicMock(return_value=JobData(
            id='job_cancelled',
            title='Cancelled Job',
            content='Content',
            formatted_date_time='2023-03-27 12:00:00',
            timestamp=1679918400,
            message_id='123456789',
            guild_id=str(TEST_GUILD_ID),
            status='cancelled',
        ))

        await admin_cog.cancel_job(admin_cog, mock_context, "job_cancelled")

        admin_cog.state_manager.scheduler.cancel_job_by_message_id.assert_not_called()
        mock_context.reply.assert_called_once()

    # AnnouncementCog Tests

    @pytest.mark.asyncio
    async def test_announcement_request_handling(self, announcement_cog, mock_message, mock_persistence):
        """Test handling of announcement requests."""
        mock_message.content = "Test content"

        await announcement_cog._handle_announcement_request(
            mock_message,
            announcement_cog.state_manager.get_guild_context(str(mock_message.guild.id)),
        )

        mock_message.add_reaction.assert_called_once_with(announcement_cog.seen_emoji)

        guild_id = str(mock_message.guild.id)
        assert announcement_cog.state_manager.get_state(guild_id).is_pending(str(mock_message.id))

        mock_persistence.save_announcement.assert_called()

    @pytest.mark.asyncio
    async def test_announcement_approval(self, announcement_cog, mock_message, mock_admin_member):
        """Test approval of announcements via reactions."""
        guild_id = str(mock_message.guild.id)

        # Store a pending request (via state manager)
        announcement_cog.state_manager.get_state(guild_id).add_pending(str(mock_message.id))

        # Create a payload for the reaction
        payload = MagicMock()
        payload.user_id = 987123456  # Not the bot
        payload.message_id = mock_message.id
        payload.channel_id = mock_message.channel.id
        payload.guild_id = guild_id
        payload.emoji = MagicMock()
        payload.emoji.__str__ = MagicMock(return_value=announcement_cog.approval_emoji)

        # Mock channel and message fetching
        channel = MagicMock()
        channel.fetch_message = AsyncMock(return_value=mock_message)
        channel.guild.fetch_member = AsyncMock(return_value=mock_admin_member)
        announcement_cog.bot.get_channel = MagicMock(return_value=channel)

        await announcement_cog.on_raw_reaction_add(payload)

        announcement_cog.ai_processor.process_announcement.assert_called_once()
        announcement_cog.state_manager.scheduler.schedule_announcement.assert_called_once()
        assert announcement_cog.state_manager.get_state(guild_id).is_queued(str(mock_message.id))

    @pytest.mark.asyncio
    async def test_duplicate_prevention_history(self, announcement_cog, mock_message):
        """Test that history prevents duplicate bookings."""
        guild_id = str(mock_message.guild.id)

        announcement_cog.state_manager.get_state(guild_id).history.append(str(mock_message.id))

        await announcement_cog._handle_announcement_request(
            mock_message,
            announcement_cog.state_manager.get_guild_context(guild_id),
        )

        mock_message.reply.assert_called_with(Messages.Discord.ALREADY_BOOKED)
        assert not announcement_cog.state_manager.get_state(guild_id).is_pending(str(mock_message.id))

    @pytest.mark.asyncio
    async def test_restoration_on_ready(self, announcement_cog, mock_persistence):
        """Test restoration logic on bot ready."""
        str_guild_id = str(TEST_GUILD_ID)
        mock_persistence.load_announcements.return_value = {
            '123': {
                'guild_id': str_guild_id,
                'bot_reply_id': None,
                'calendar_event_id': None,
                'completed': False,
                'job': None,
            }
        }

        skipped_job = {'id': 'job2', 'title': 'Skipped Job', 'timestamp': 900}
        announcement_cog.state_manager.scheduler.restore_jobs.return_value = (1, [skipped_job])
        announcement_cog.state_manager.scheduler.list_jobs.return_value = []

        channel = AsyncMock()
        announcement_cog.bot.get_channel.return_value = channel

        await announcement_cog.on_ready()

        mock_persistence.load_announcements.assert_called_once()
        mock_persistence.save_announcement.assert_called()
        announcement_cog.state_manager.scheduler.restore_jobs.assert_called_once()

        assert channel.send.call_count == 2
        args_stats, _ = channel.send.call_args_list[0]
        assert "1 pending" in args_stats[0]
        assert "1 booked" in args_stats[0]

        args_skipped, _ = channel.send.call_args_list[1]
        assert "Skipped 1" in args_skipped[0]
        assert "Skipped Job" in args_skipped[0]

    @pytest.mark.asyncio
    async def test_job_completion_callback(self, announcement_cog, mock_persistence):
        """Test job completion callback logic."""
        str_guild_id = str(TEST_GUILD_ID)
        announcement_cog.state_manager.get_state(str_guild_id).queued_announcements.add('msg123')

        job_data = {'message_id': 'msg123', 'status': 'success', 'guild_id': str_guild_id}
        await announcement_cog._on_job_complete(job_data)

        assert announcement_cog.state_manager.get_state(str_guild_id).is_in_history('msg123')
        assert not announcement_cog.state_manager.get_state(str_guild_id).is_queued('msg123')
        mock_persistence.save_announcement.assert_called()

    @pytest.mark.asyncio
    async def test_process_approved_announcement_past_time_warning(self, announcement_cog, mock_message):
        """Test that scheduling is blocked and warning sent for times > misfire_grace_time in past."""
        processing_msg = AsyncMock()
        mock_message.reply.return_value = processing_msg

        current_time = time.time()
        past_time = current_time - 7200

        announcement_cog.ai_processor.process_announcement.return_value = AIProcessingResult(
            success=True,
            timestamp=past_time,
            title="Test Title",
            content="Test Content",
        )

        guild_id = str(mock_message.guild.id)
        gctx = announcement_cog.state_manager.get_guild_context(guild_id)
        await announcement_cog._process_approved_announcement(mock_message, gctx)

        announcement_cog.ai_processor.process_announcement.assert_called_with(mock_message.content)

        expected_mentions = f"<@&{TEST_ADMIN_ROLE_ID}> {mock_message.author.mention}"
        expected_content = Messages.Discord.PAST_TIME_WARNING.format(mentions=expected_mentions)
        processing_msg.edit.assert_called_with(content=expected_content)

        announcement_cog.state_manager.scheduler.schedule_announcement.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_approved_announcement_recent_past_time_success(self, announcement_cog, mock_message):
        """Test that scheduling proceeds for times < misfire_grace_time in past."""
        processing_msg = AsyncMock()
        mock_message.reply.return_value = processing_msg

        current_time = time.time()
        recent_past_time = current_time - 1800

        announcement_cog.ai_processor.process_announcement.return_value = AIProcessingResult(
            success=True,
            timestamp=recent_past_time,
            announcement_timestamp=recent_past_time,
            event_start_timestamp=recent_past_time + 3600,
            event_end_timestamp=recent_past_time + 7200,
            title='Test Title',
            content='Test Content',
        )

        guild_id = str(mock_message.guild.id)
        gctx = announcement_cog.state_manager.get_guild_context(guild_id)
        await announcement_cog._process_approved_announcement(mock_message, gctx)

        announcement_cog.state_manager.scheduler.schedule_announcement.assert_called_once()

        call_kwargs = processing_msg.edit.call_args[1]
        assert 'embed' in call_kwargs
        assert call_kwargs.get('content') is None

    @pytest.mark.asyncio
    async def test_guild_disabled_rejects_new_requests(self, mock_bot, mock_ai_processor, mock_scheduler, mock_persistence, mock_vrchat_api, mock_message):
        """Test that a disabled guild rejects new announcement requests."""
        config = {
            'discord': {
                'prefix': '!',
                'seen_reaction_emoji': "👀",
                'approval_reaction_emoji': "👍",
                'fast_forward_emoji': "⏩",
                'guilds': [{
                    'guild_id': str(TEST_GUILD_ID),
                    'group_id': 'grp_test',
                    'enabled': False,  # Disabled
                    'channel_ids': [str(TEST_CHANNEL_ID)],
                    'admin_role_id': str(TEST_ADMIN_ROLE_ID),
                    'firestore_server_id': 'test',
                }]
            }
        }
        guild_persistences = {str(TEST_GUILD_ID): mock_persistence}
        guild_configs = {str(TEST_GUILD_ID): config['discord']['guilds'][0]}
        state_manager = StateManager(
            scheduler=mock_scheduler,
            vrchat_api=mock_vrchat_api,
            guild_persistences=guild_persistences,
            guild_configs=guild_configs,
        )
        cog = AnnouncementCog(mock_bot, config, mock_ai_processor, state_manager, mock_vrchat_api)

        mock_message.channel.id = TEST_CHANNEL_ID
        mock_bot.user.mentioned_in.return_value = True

        await cog.on_message(mock_message)

        mock_message.reply.assert_called_once_with(Messages.Discord.GUILD_DISABLED)
        assert not state_manager.get_state(str(TEST_GUILD_ID)).is_pending(str(mock_message.id))

    # GeneralCog Tests

    TEST_ADMIN_USER_ID = 555000555

    @pytest.fixture
    def mock_bot_with_admin(self, mock_bot, mock_config):
        """Bot mock with admin_id set in config."""
        mock_config['discord']['admin_id'] = str(self.TEST_ADMIN_USER_ID)
        mock_bot.config = mock_config
        mock_bot.command_prefix = "!"
        return mock_bot

    @pytest.fixture
    def general_cog(self, mock_bot_with_admin, mock_state_manager, mock_vrchat_api):
        """Create a GeneralCog instance with mocks."""
        return GeneralCog(mock_bot_with_admin, mock_vrchat_api, mock_state_manager)

    def _make_dm_context(self, user_id: int, reply_mock):
        ctx = MagicMock()
        ctx.channel = MagicMock(spec=discord.DMChannel)
        ctx.author = MagicMock()
        ctx.author.id = user_id
        ctx.reply = reply_mock
        return ctx

    def _make_guild_context(self, user_id: int, reply_mock):
        ctx = MagicMock()
        ctx.channel = MagicMock()  # not a DMChannel
        ctx.author = MagicMock()
        ctx.author.id = user_id
        ctx.reply = reply_mock
        return ctx

    @pytest.mark.asyncio
    async def test_listall_ignored_in_guild_channel(self, general_cog):
        """listall should silently do nothing when not in a DM."""
        reply = AsyncMock()
        ctx = self._make_guild_context(self.TEST_ADMIN_USER_ID, reply)
        await general_cog.list_all_jobs(general_cog, ctx)
        reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_listall_rejected_for_non_admin(self, general_cog):
        """listall should reject non-admin users in DMs."""
        reply = AsyncMock()
        ctx = self._make_dm_context(user_id=999888777, reply_mock=reply)
        await general_cog.list_all_jobs(general_cog, ctx)
        reply.assert_called_once()
        args, _ = reply.call_args
        assert "管理者" in args[0]

    @pytest.mark.asyncio
    async def test_listall_returns_all_jobs_for_admin(self, general_cog, mock_scheduler):
        """listall should return all jobs across guilds when called by bot admin in DM."""
        second_guild_id = "222222222"
        mock_scheduler.list_jobs.return_value = [
            JobData(
                id="job1", title="Alpha", content="content a",
                formatted_date_time="2024-01-01 10:00", timestamp=1704067200,
                message_id="111", guild_id=str(TEST_GUILD_ID),
            ),
            JobData(
                id="job2", title="Beta", content="content b",
                formatted_date_time="2024-01-02 10:00", timestamp=1704153600,
                message_id="222", guild_id=second_guild_id,
            ),
        ]
        general_cog.bot.get_guild = MagicMock(return_value=None)

        reply = AsyncMock()
        ctx = self._make_dm_context(user_id=self.TEST_ADMIN_USER_ID, reply_mock=reply)
        await general_cog.list_all_jobs(general_cog, ctx)

        # Called with no guild_id filter
        mock_scheduler.list_jobs.assert_called_once_with()
        reply.assert_called_once()
        _, kwargs = reply.call_args
        embed = kwargs.get("embed") or reply.call_args[0][0] if reply.call_args[0] else None
        # embed is passed as keyword arg
        call_kwargs = reply.call_args[1] if reply.call_args[1] else {}
        assert "embed" in call_kwargs
        embed = call_kwargs["embed"]
        assert len(embed.fields) == 2

    @pytest.mark.asyncio
    async def test_listall_no_jobs_message(self, general_cog, mock_scheduler):
        """listall should reply with a no-jobs message when scheduler is empty."""
        mock_scheduler.list_jobs.return_value = []
        reply = AsyncMock()
        ctx = self._make_dm_context(user_id=self.TEST_ADMIN_USER_ID, reply_mock=reply)
        await general_cog.list_all_jobs(general_cog, ctx)
        reply.assert_called_once()
        args, _ = reply.call_args
        assert "ありません" in args[0]
    @pytest.mark.asyncio
    async def test_on_job_complete_success_updates_embed(self, announcement_cog, mock_persistence):
        """Test that a successful job completion updates the booking embed with a checkmark."""
        guild_id = str(TEST_GUILD_ID)
        msg_id = "msg_posted"

        # Set up state with a bot reply
        gctx = announcement_cog.state_manager.get_guild_context(guild_id)
        gctx.state.add_pending(msg_id)
        gctx.state.mark_queued(msg_id, "999")

        # Mock the channel and bot reply message
        mock_embed = MagicMock()
        mock_embed.title = "告知が予約されました"
        mock_embed.copy = MagicMock(return_value=mock_embed)
        bot_reply_msg = AsyncMock()
        bot_reply_msg.embeds = [mock_embed]

        channel = AsyncMock()
        channel.fetch_message = AsyncMock(return_value=bot_reply_msg)
        announcement_cog.bot.get_channel = MagicMock(return_value=channel)

        job_data = {'message_id': msg_id, 'status': 'success', 'guild_id': guild_id}
        await announcement_cog._on_job_complete(job_data)

        bot_reply_msg.edit.assert_called_once()
        edited_embed = bot_reply_msg.edit.call_args[1]['embed']
        assert edited_embed.title.startswith("✅")

