import pytest
import discord
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

from cogs.admin import AdminCog
from cogs.announcement import AnnouncementCog
from utils.messages import Messages

class TestCogs:
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 123456789
        bot.user.mentioned_in = MagicMock(return_value=True)
        bot.get_channel = MagicMock()
        return bot
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        return {
            'discord': {
                'channel_ids': [987654321],
                'admin_role_id': 111222333,
                'prefix': '!',
                'seen_reaction_emoji': "👀",
                'approval_reaction_emoji': "👍",
                'fast_forward_emoji': "⏩"
            }
        }
    
    @pytest.fixture
    def mock_scheduler(self):
        """Create a mock scheduler."""
        scheduler = MagicMock()
        # Set up mock job list
        scheduler.list_jobs.return_value = [
            {
                'id': 'job1',
                'title': 'Test Announcement',
                'content': 'This is a test announcement content.',
                'formatted_date_time': '2023-03-27 12:00:00',
                'timestamp': 1679918400,
                'message_id': '123456789'
            }
        ]
        scheduler.cancel_job = MagicMock(return_value=True)
        scheduler.schedule_announcement = AsyncMock(return_value='new_job_id')
        scheduler.restore_jobs = MagicMock(return_value=(0, []))
        scheduler.get_jobs_data = MagicMock(return_value=[])
        scheduler.vrchat_api = MagicMock()
        return scheduler
    
    @pytest.fixture
    def mock_ai_processor(self):
        """Create a mock AI processor."""
        processor = MagicMock()
        processor.process_announcement = AsyncMock(return_value={
            'success': True,
            'timestamp': 1679990400, # 2023-03-28 15:00:00
            'title': 'AI Processed Title',
            'content': 'AI processed content for VRChat announcement',
            'formatted_date_time': '2023-03-28 15:00:00'
        })
        return processor

    @pytest.fixture
    def mock_persistence(self):
        """Create a mock persistence object."""
        persistence = MagicMock()
        persistence.load_data.return_value = [] # Default for lists
        persistence.save_data.return_value = True
        return persistence

    @pytest.fixture
    def admin_cog(self, mock_bot, mock_config, mock_scheduler):
        """Create an AdminCog instance with mocks."""
        return AdminCog(mock_bot, mock_config, mock_scheduler)
    
    @pytest.fixture
    def announcement_cog(self, mock_bot, mock_config, mock_ai_processor, mock_scheduler, mock_persistence):
        """Create an AnnouncementCog instance with mocks."""
        with patch('cogs.announcement.Persistence', return_value=mock_persistence):
            cog = AnnouncementCog(mock_bot, mock_config, mock_ai_processor, mock_scheduler)
            cog.history = [] # Explicitly init history for tests
            return cog
    
    @pytest.fixture
    def mock_message(self):
        """Create a mock message."""
        message = AsyncMock()
        message.author = MagicMock()
        message.author.bot = False
        message.author.id = 987123456
        message.author.name = "Test User"
        
        message.channel = MagicMock()
        message.channel.id = 987654321
        
        message.guild = MagicMock()
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
        admin_role.id = 111222333
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
    async def test_admin_cancel_command(self, admin_cog, mock_context, mock_admin_member):
        """Test the cancel command in AdminCog."""
        # Setup context
        mock_context.author = mock_admin_member
        
        # Invoke command
        await admin_cog.cancel_job(admin_cog, mock_context, "job1")
        
        # Verify cancel_job was called
        admin_cog.scheduler.cancel_job.assert_called_once_with("job1")
        
        # Verify success message
        mock_context.reply.assert_called_once()
        args, _ = mock_context.reply.call_args
        assert Messages.Discord.JOB_CANCELLED.format("job1") in args[0]
    
    # AnnouncementCog Tests
    
    @pytest.mark.asyncio
    async def test_announcement_request_handling(self, announcement_cog, mock_message):
        """Test handling of announcement requests."""
        # Set up message
        mock_message.content = "Test content"
        
        # Call handler directly since on_message listener might be tricky to trigger in isolation
        await announcement_cog._handle_announcement_request(mock_message)
        
        # Verify reaction was added
        mock_message.add_reaction.assert_called_once_with(announcement_cog.seen_emoji)
        
        # Verify message was stored in pending_requests
        assert str(mock_message.id) in announcement_cog.pending_requests
        
        # Verify persistence save was called
        announcement_cog.persistence.save_data.assert_called()
    
    @pytest.mark.asyncio
    async def test_announcement_approval(self, announcement_cog, mock_message, mock_admin_member):
        """Test approval of announcements via reactions."""
        # Store a pending request
        announcement_cog.pending_requests[str(mock_message.id)] = None
        
        # Create a payload for the reaction
        payload = MagicMock()
        payload.user_id = 987123456  # Not the bot
        payload.message_id = mock_message.id
        payload.channel_id = mock_message.channel.id
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
        
        # Verify persistence save was called
        announcement_cog.persistence.save_data.assert_called()
        
        # Verify queued_announcements updated
        assert str(mock_message.id) in announcement_cog.queued_announcements

    @pytest.mark.asyncio
    async def test_duplicate_prevention_history(self, announcement_cog, mock_message):
        """Test that history prevents duplicate bookings."""
        # Add message ID to history
        announcement_cog.history.append(str(mock_message.id))
        
        # Call handler
        await announcement_cog._handle_announcement_request(mock_message)
        
        # Verify already booked message
        mock_message.reply.assert_called_with(Messages.Discord.ALREADY_BOOKED)
        
        # Verify NOT added to pending
        assert str(mock_message.id) not in announcement_cog.pending_requests

    @pytest.mark.asyncio
    async def test_restoration_on_ready(self, announcement_cog):
        """Test restoration logic on bot ready."""
        # Setup mocks
        announcement_cog.persistence.load_data.side_effect = [
            {'123': None}, # pending.json
            ['456'],       # history.json
            [{'id': 'job1', 'timestamp': 1000}] # jobs.json
        ]
        
        # Mock scheduler restoration result
        skipped_job = {'id': 'job2', 'title': 'Skipped Job', 'timestamp': 900}
        announcement_cog.scheduler.restore_jobs.return_value = (1, [skipped_job])
        
        # Mock channel for notification
        channel = AsyncMock()
        announcement_cog.bot.get_channel.return_value = channel
        
        # Call on_ready
        await announcement_cog.on_ready()
        
        # Verify load_data calls
        assert announcement_cog.persistence.load_data.call_count == 3
        
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
    async def test_job_completion_callback(self, announcement_cog):
        """Test job completion callback logic."""
        # Setup
        job_data = {'message_id': 'msg123'}
        announcement_cog.queued_announcements.add('msg123')

        # Call callback
        await announcement_cog._on_job_complete(job_data)

        # Verify history update
        assert 'msg123' in announcement_cog.history

        # Verify removal from queue
        assert 'msg123' not in announcement_cog.queued_announcements

        # Verify persistence save
        announcement_cog.persistence.save_data.assert_called()
