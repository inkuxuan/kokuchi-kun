import pytest
import discord
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Add the parent directory to sys.path to import the cogs

from cogs.admin import AdminCog
from cogs.announcement import AnnouncementCog

class TestCogs:
    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot."""
        bot = MagicMock()
        bot.user = MagicMock()
        bot.user.id = 123456789
        bot.user.mentioned_in = MagicMock(return_value=True)
        return bot
    
    @pytest.fixture
    def mock_config(self):
        """Create a mock configuration."""
        return {
            'discord': {
                'channel_id': 987654321,
                'admin_role_id': 111222333,
                'prefix': '!',
                'seen_reaction_emoji': "👀",
                'approval_reaction_emoji': "👍"
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
                'formatted_date_time': '2023-03-27 12:00:00'
            }
        ]
        scheduler.cancel_job = MagicMock(return_value=True)
        scheduler.schedule_announcement = AsyncMock(return_value='new_job_id')
        return scheduler
    
    @pytest.fixture
    def mock_ai_processor(self):
        """Create a mock AI processor."""
        processor = MagicMock()
        processor.process_announcement = AsyncMock(return_value={
            'success': True,
            'timestamp': '2023-03-28T15:00:00',
            'title': 'AI Processed Title',
            'content': 'AI processed content for VRChat announcement',
            'formatted_date_time': '2023-03-28 15:00:00'
        })
        return processor
    
    @pytest.fixture
    def admin_cog(self, mock_bot, mock_config, mock_scheduler):
        """Create an AdminCog instance with mocks."""
        return AdminCog(mock_bot, mock_config, mock_scheduler)
    
    @pytest.fixture
    def announcement_cog(self, mock_bot, mock_config, mock_ai_processor, mock_scheduler):
        """Create an AnnouncementCog instance with mocks."""
        return AnnouncementCog(mock_bot, mock_config, mock_ai_processor, mock_scheduler)
    
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
        
        return message
    
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
    
    @pytest.mark.asyncio
    async def test_admin_list_command(self, admin_cog, mock_message, mock_admin_member):
        """Test the list command in AdminCog."""
        # Set up message
        mock_message.content = "!list"
        
        # Set up admin check
        discord.utils.get = MagicMock(return_value=mock_admin_member)
        
        # Call on_message
        await admin_cog.on_message(mock_message)
        
        # Verify list_jobs was called
        admin_cog.scheduler.list_jobs.assert_called_once()
        
        # Verify reply was called with an embed
        mock_message.reply.assert_called_once()
        args, kwargs = mock_message.reply.call_args
        assert "embed" in kwargs
    
    @pytest.mark.asyncio
    async def test_admin_cancel_command(self, admin_cog, mock_message, mock_admin_member):
        """Test the cancel command in AdminCog."""
        # Set up message
        mock_message.content = "!cancel job1"
        
        # Set up admin check
        discord.utils.get = MagicMock(return_value=mock_admin_member)
        
        # Call on_message
        await admin_cog.on_message(mock_message)
        
        # Verify cancel_job was called with correct job ID
        admin_cog.scheduler.cancel_job.assert_called_once_with("job1")
        
        # Verify reply was called with success message
        mock_message.reply.assert_called_once()
        args, kwargs = mock_message.reply.call_args
        assert "キャンセルしました" in args[0]
    
    @pytest.mark.asyncio
    async def test_admin_help_command(self, admin_cog, mock_message, mock_admin_member):
        """Test the help command in AdminCog."""
        # Set up message
        mock_message.content = "!help"
        
        # Set up admin check
        discord.utils.get = MagicMock(return_value=mock_admin_member)
        
        # Call on_message
        await admin_cog.on_message(mock_message)
        
        # Verify reply was called with an embed
        mock_message.reply.assert_called_once()
        args, kwargs = mock_message.reply.call_args
        assert "embed" in kwargs
        assert kwargs["embed"].title == "コマンド一覧"
    
    @pytest.mark.asyncio
    async def test_admin_non_admin_access(self, admin_cog, mock_message, mock_normal_member):
        """Test that non-admins cannot use admin commands."""
        # Set up message
        mock_message.content = "!list"
        
        # Set up admin check to return None (no admin role)
        discord.utils.get = MagicMock(return_value=None)
        
        # Call on_message
        await admin_cog.on_message(mock_message)
        
        # Verify scheduler methods were NOT called
        admin_cog.scheduler.list_jobs.assert_not_called()
        
        # Verify reply was called with permission denied message
        mock_message.reply.assert_called_once()
        args, kwargs = mock_message.reply.call_args
        assert "権限がありません" in args[0]
    
    @pytest.mark.asyncio
    async def test_announcement_request_handling(self, announcement_cog, mock_message):
        """Test handling of announcement requests."""
        # Set up message
        mock_message.content = "@bot ===VRCグループ告知リクエスト テンプレート===\nTest content"
        
        # Call on_message
        await announcement_cog.on_message(mock_message)
        
        # Verify reaction was added
        mock_message.add_reaction.assert_called_once_with(announcement_cog.seen_emoji)
        
        # Verify message was stored in pending_requests
        assert str(mock_message.id) in announcement_cog.pending_requests
        
        # Verify reply was sent
        mock_message.reply.assert_called_once()
        args, kwargs = mock_message.reply.call_args
        assert "確認しました" in args[0]
    
    @pytest.mark.asyncio
    async def test_announcement_approval(self, announcement_cog, mock_message, mock_admin_member):
        """Test approval of announcements via reactions."""
        # Store a pending request
        announcement_cog.pending_requests[str(mock_message.id)] = {
            "content": "===VRCグループ告知リクエスト テンプレート===\nTest content",
            "author_id": mock_message.author.id
        }
        
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
        announcement_cog.bot.get_channel = MagicMock(return_value=channel)
        
        # Mock admin role check
        mock_message.guild.fetch_member = AsyncMock(return_value=mock_admin_member)
        
        # Call on_raw_reaction_add
        await announcement_cog.on_raw_reaction_add(payload)
        
        # Verify AI processor was called
        announcement_cog.ai_processor.process_announcement.assert_called_once()
        
        # Verify scheduler was called
        announcement_cog.scheduler.schedule_announcement.assert_called_once()
        
        # Verify reply was sent with embed
        mock_message.reply.assert_called_once()
        args, kwargs = mock_message.reply.call_args
        assert "embed" in kwargs
        assert kwargs["embed"].title == "告知が予約されました"
        
        # Verify request was removed from pending
        assert str(mock_message.id) not in announcement_cog.pending_requests

    @pytest.mark.asyncio
    async def test_mention_recognition(self, announcement_cog, mock_message):
        """Test if the bot recognizes mentions but ignores non-announcement requests."""
        # Set up message with mention but without template
        mock_message.content = "Hey @bot, how are you doing?"
        
        # Call on_message
        await announcement_cog.on_message(mock_message)
        
        # Verify no reaction was added (not an announcement request)
        mock_message.add_reaction.assert_not_called()
        
        # Verify no reply was sent
        mock_message.reply.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_non_admin_reaction(self, announcement_cog, mock_message, mock_normal_member):
        """Test that non-admins cannot approve announcements."""
        # Store a pending request
        announcement_cog.pending_requests[str(mock_message.id)] = {
            "content": "===VRCグループ告知リクエスト テンプレート===\nTest content",
            "author_id": mock_message.author.id
        }
        
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
        announcement_cog.bot.get_channel = MagicMock(return_value=channel)
        
        # Mock non-admin member fetch
        mock_message.guild.fetch_member = AsyncMock(return_value=mock_normal_member)
        
        # Call on_raw_reaction_add
        await announcement_cog.on_raw_reaction_add(payload)
        
        # Verify AI processor was NOT called
        announcement_cog.ai_processor.process_announcement.assert_not_called()
        
        # Verify scheduler was NOT called
        announcement_cog.scheduler.schedule_announcement.assert_not_called()
        
        # Verify request is still in pending
        assert str(mock_message.id) in announcement_cog.pending_requests 