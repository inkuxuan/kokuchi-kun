import pytest
import discord
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os
import time

from cogs.admin import AdminCog
from cogs.announcement import AnnouncementCog
from utils.messages import Messages
from utils.models import AIProcessingResult, JobData

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
        scheduler.get_job = MagicMock(return_value=JobData(
            id='job1',
            title='Test Announcement',
            content='This is a test announcement content.',
            formatted_date_time='2023-03-27 12:00:00',
            timestamp=1679918400,
            message_id='123456789',
            guild_id=str(TEST_GUILD_ID),
        ))
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
        return persistence

    @pytest.fixture
    def mock_vrchat_api(self):
        """Create a mock VRChat API."""
        api = MagicMock()
        api.set_otp_callback = MagicMock()
        return api

    @pytest.fixture
    def admin_cog(self, mock_bot, mock_config, mock_scheduler):
        """Create an AdminCog instance with mocks."""
        return AdminCog(mock_bot, mock_config, mock_scheduler)

    @pytest.fixture
    def announcement_cog(self, mock_bot, mock_config, mock_ai_processor, mock_scheduler, mock_persistence, mock_vrchat_api):
        """Create an AnnouncementCog instance with mocks."""
        guild_persistences = {str(TEST_GUILD_ID): mock_persistence}
        cog = AnnouncementCog(mock_bot, mock_config, mock_ai_processor, mock_scheduler, guild_persistences, mock_vrchat_api)
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

    # AdminCog Tests - Updated to test commands directly

    @pytest.mark.asyncio
    async def test_admin_list_command(self, admin_cog, mock_context, mock_admin_member):
        """Test the list command in AdminCog."""
        # Setup context
        mock_context.author = mock_admin_member

        # Invoke command
        await admin_cog.list_jobs(admin_cog, mock_context)

        # Verify scheduler list_jobs was called
        admin_cog.scheduler.list_jobs.assert_called_once()

        # Verify reply/send was called
        # Note: In real execution, it sends an embed. We just check if it sent something.
        assert mock_context.send.called or mock_context.reply.called

    @pytest.mark.asyncio
    async def test_admin_cancel_command(self, admin_cog, mock_context, mock_admin_member, announcement_cog, mock_persistence):
        """Test the cancel command in AdminCog."""
        # Setup context
        mock_context.author = mock_admin_member

        # Mock bot.get_cog to return the announcement_cog
        admin_cog.bot.get_cog = MagicMock(return_value=announcement_cog)

        # Invoke command
        await admin_cog.cancel_job(admin_cog, mock_context, "job1")

        # Verify cancel_job was called
        admin_cog.scheduler.cancel_job.assert_called_once_with("job1")

        # Verify save_state was called on announcement cog (which calls persistence.save_data)
        mock_persistence.save_data.assert_called()

        # Verify success message
        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_CANCELLED.format("job1") in args[0]

    @pytest.mark.asyncio
    async def test_admin_cancel_cross_guild_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling a job belonging to a different guild is rejected."""
        mock_context.author = mock_admin_member

        # The mock scheduler returns a job with guild_id = str(TEST_GUILD_ID),
        # but the context guild is different.
        other_guild_id = 999999999
        mock_context.guild.id = other_guild_id

        await admin_cog.cancel_job(admin_cog, mock_context, "job1")

        # Verify cancel_job was NOT called on the scheduler
        admin_cog.scheduler.cancel_job.assert_not_called()

        # Verify the "not found" message was sent
        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_NOT_FOUND.format("job1") in args[0]

    @pytest.mark.asyncio
    async def test_admin_cancel_nonexistent_job_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling a nonexistent job is rejected."""
        mock_context.author = mock_admin_member

        # Make get_job return None for the requested job
        admin_cog.scheduler.get_job = MagicMock(return_value=None)

        await admin_cog.cancel_job(admin_cog, mock_context, "nonexistent_job")

        # Verify cancel_job was NOT called on the scheduler
        admin_cog.scheduler.cancel_job.assert_not_called()

        # Verify the "not found" message was sent
        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_NOT_FOUND.format("nonexistent_job") in args[0]

    @pytest.mark.asyncio
    async def test_admin_cancel_success_job_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling a successfully completed job is rejected."""
        mock_context.author = mock_admin_member

        # Make get_job return a completed job
        admin_cog.scheduler.get_job = MagicMock(return_value=JobData(
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

        # Verify cancel_job was NOT called on the scheduler
        admin_cog.scheduler.cancel_job.assert_not_called()

        # Verify the "not found" message was sent
        mock_context.reply.assert_called_once()

    @pytest.mark.asyncio
    async def test_admin_cancel_cancelled_job_rejected(self, admin_cog, mock_context, mock_admin_member):
        """Test that cancelling an already-cancelled job is rejected."""
        mock_context.author = mock_admin_member

        admin_cog.scheduler.get_job = MagicMock(return_value=JobData(
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

        admin_cog.scheduler.cancel_job.assert_not_called()
        mock_context.reply.assert_called_once()

    # AnnouncementCog Tests

    @pytest.mark.asyncio
    async def test_announcement_request_handling(self, announcement_cog, mock_message, mock_persistence):
        """Test handling of announcement requests."""
        # Set up message
        mock_message.content = "Test content"

        # Call handler directly since on_message listener might be tricky to trigger in isolation
        await announcement_cog._handle_announcement_request(mock_message)

        # Verify reaction was added
        mock_message.add_reaction.assert_called_once_with(announcement_cog.seen_emoji)

        # Verify message was stored in pending_requests via state manager
        guild_id = str(mock_message.guild.id)
        assert announcement_cog._get_state(guild_id).is_pending(str(mock_message.id))

        # Verify persistence save was called
        mock_persistence.save_data.assert_called()

    @pytest.mark.asyncio
    async def test_announcement_approval(self, announcement_cog, mock_message, mock_admin_member):
        """Test approval of announcements via reactions."""
        guild_id = str(mock_message.guild.id)

        # Store a pending request (via state manager)
        announcement_cog._get_state(guild_id).add_pending(str(mock_message.id))

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

        # Call on_raw_reaction_add
        await announcement_cog.on_raw_reaction_add(payload)

        # Verify AI processor was called
        announcement_cog.ai_processor.process_announcement.assert_called_once()

        # Verify scheduler was called
        announcement_cog.scheduler.schedule_announcement.assert_called_once()

        # Verify queued_announcements updated (via state manager)
        assert announcement_cog._get_state(guild_id).is_queued(str(mock_message.id))

    @pytest.mark.asyncio
    async def test_duplicate_prevention_history(self, announcement_cog, mock_message):
        """Test that history prevents duplicate bookings."""
        guild_id = str(mock_message.guild.id)

        # Add message ID to history (via state manager)
        announcement_cog._get_state(guild_id).history.append(str(mock_message.id))

        # Call handler
        await announcement_cog._handle_announcement_request(mock_message)

        # Verify already booked message
        mock_message.reply.assert_called_with(Messages.Discord.ALREADY_BOOKED)

        # Verify NOT added to pending
        assert not announcement_cog._get_state(guild_id).is_pending(str(mock_message.id))

    @pytest.mark.asyncio
    async def test_restoration_on_ready(self, announcement_cog, mock_persistence):
        """Test restoration logic on bot ready."""
        # Setup mocks - load_data is called 4 times per guild: pending, history, calendar, jobs
        mock_persistence.load_data.side_effect = [
            {'123': None}, # pending
            ['456'],       # history
            {},            # calendar
            [{'id': 'job1', 'timestamp': 1000}] # jobs
        ]

        # Mock scheduler restoration result
        skipped_job = {'id': 'job2', 'title': 'Skipped Job', 'timestamp': 900}
        announcement_cog.scheduler.restore_jobs.return_value = (1, [skipped_job])
        announcement_cog.scheduler.list_jobs.return_value = []

        # Mock channel for notification
        channel = AsyncMock()
        announcement_cog.bot.get_channel.return_value = channel

        # Call on_ready
        await announcement_cog.on_ready()

        # Verify load_data calls (4 per guild: pending, history, calendar, jobs)
        assert mock_persistence.load_data.call_count == 4

        # Verify save_state was called (to persist missed-job status updates)
        mock_persistence.save_data.assert_called()

        # Verify scheduler restoration call
        announcement_cog.scheduler.restore_jobs.assert_called_once()

        # Verify notifications
        assert channel.send.call_count == 2 # One for stats, one for skipped
        args_stats, _ = channel.send.call_args_list[0]
        assert "1 pending" in args_stats[0]
        assert "1 booked" in args_stats[0]

        args_skipped, _ = channel.send.call_args_list[1]
        assert "Skipped 1" in args_skipped[0]
        assert "Skipped Job" in args_skipped[0]

    @pytest.mark.asyncio
    async def test_job_completion_callback(self, announcement_cog, mock_persistence):
        """Test job completion callback logic."""
        # Setup state under str guild ID
        str_guild_id = str(TEST_GUILD_ID)
        announcement_cog._get_state(str_guild_id).queued_announcements.add('msg123')

        # Call callback with guild_id (always str)
        job_data = {'message_id': 'msg123', 'status': 'success', 'guild_id': str_guild_id}
        await announcement_cog._on_job_complete(job_data)

        # Verify history update
        assert announcement_cog._get_state(str_guild_id).is_in_history('msg123')

        # Verify removal from queue
        assert not announcement_cog._get_state(str_guild_id).is_queued('msg123')

        # Verify persistence save
        mock_persistence.save_data.assert_called()

    @pytest.mark.asyncio
    async def test_process_approved_announcement_past_time_warning(self, announcement_cog, mock_message):
        """Test that scheduling is blocked and warning sent for times > misfire_grace_time in past."""
        # Mock processing message
        processing_msg = AsyncMock()
        mock_message.reply.return_value = processing_msg

        # Mock AI result - timestamp 2 hours ago (beyond default 3600s grace)
        current_time = time.time()
        past_time = current_time - 7200 # 2 hours ago

        announcement_cog.ai_processor.process_announcement.return_value = AIProcessingResult(
            success=True,
            timestamp=past_time,
            title="Test Title",
            content="Test Content",
        )

        # Run method
        await announcement_cog._process_approved_announcement(mock_message)

        # Verify AI called
        announcement_cog.ai_processor.process_announcement.assert_called_with(mock_message.content)

        # Verify Warning was sent via edit (admin_role_id from None-keyed guild config)
        expected_mentions = f"<@&{TEST_ADMIN_ROLE_ID}> {mock_message.author.mention}"
        expected_content = Messages.Discord.PAST_TIME_WARNING.format(mentions=expected_mentions)
        processing_msg.edit.assert_called_with(content=expected_content)

        # Verify scheduler NOT called
        announcement_cog.scheduler.schedule_announcement.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_approved_announcement_recent_past_time_success(self, announcement_cog, mock_message):
        """Test that scheduling proceeds for times < misfire_grace_time in past."""
        # Mock processing message
        processing_msg = AsyncMock()
        mock_message.reply.return_value = processing_msg

        # Mock AI result - timestamp 30 minutes ago (within default 3600s grace)
        current_time = time.time()
        recent_past_time = current_time - 1800 # 30 mins ago

        announcement_cog.ai_processor.process_announcement.return_value = AIProcessingResult(
            success=True,
            timestamp=recent_past_time,
            announcement_timestamp=recent_past_time,
            event_start_timestamp=recent_past_time + 3600,
            event_end_timestamp=recent_past_time + 7200,
            title='Test Title',
            content='Test Content',
        )

        # Run method
        await announcement_cog._process_approved_announcement(mock_message)

        # Verify scheduler CALLED
        announcement_cog.scheduler.schedule_announcement.assert_called_once()

        # Verify success embed sent
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
        cog = AnnouncementCog(mock_bot, config, mock_ai_processor, mock_scheduler, guild_persistences, mock_vrchat_api)

        # Simulate on_message with bot mention on monitored channel
        mock_message.channel.id = TEST_CHANNEL_ID
        mock_bot.user.mentioned_in.return_value = True

        await cog.on_message(mock_message)

        # Should reply with disabled message
        mock_message.reply.assert_called_once_with(Messages.Discord.GUILD_DISABLED)

        # Should NOT have added to pending state
        assert not cog._get_state(str(TEST_GUILD_ID)).is_pending(str(mock_message.id))
