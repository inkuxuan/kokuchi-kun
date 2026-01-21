import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
import pytz
from utils.ai_processor import AIProcessor

@pytest.fixture
def mock_config():
    return {
        'api_key': 'test_key',
        'model': 'test_model',
        'prompt': 'test_prompt'
    }

@pytest.fixture
def ai_processor(mock_config):
    return AIProcessor(mock_config)

@pytest.mark.asyncio
async def test_process_announcement_success(ai_processor):
    # Mock OpenAI response
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '''
    {
      "announcement_date": "2023-10-27",
      "announcement_time": "20:00",
      "event_start_date": "2023-10-28",
      "event_start_time": "21:00",
      "event_end_date": "2023-10-28",
      "event_end_time": "22:00",
      "title": "Test Event",
      "content": "Test Content"
    }
    '''

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result['success'] is True
        assert result['title'] == "Test Event"
        assert result['content'] == "Test Content"

        # Verify timestamps (approximate check due to timezone complexity in test env vs implementation)
        # Just check relative order
        assert result['announcement_timestamp'] < result['event_start_timestamp']
        assert result['event_start_timestamp'] < result['event_end_timestamp']

        # Check specific values (JST is UTC+9)
        # Announcement: 2023-10-27 20:00 JST -> 2023-10-27 11:00 UTC
        # Event Start: 2023-10-28 21:00 JST -> 2023-10-28 12:00 UTC

        jst = pytz.timezone('Asia/Tokyo')
        ann_dt = jst.localize(datetime(2023, 10, 27, 20, 0))
        assert result['announcement_timestamp'] == int(ann_dt.timestamp())

@pytest.mark.asyncio
async def test_process_announcement_missing_end_time(ai_processor):
    # Mock OpenAI response without end time
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '''
    {
      "announcement_date": "2023-10-27",
      "announcement_time": "20:00",
      "event_start_date": "2023-10-28",
      "event_start_time": "21:00",
      "title": "Test Event",
      "content": "Test Content"
    }
    '''

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result['success'] is True
        # Check if end time is start time + 1 hour
        assert result['event_end_timestamp'] == result['event_start_timestamp'] + 3600

@pytest.mark.asyncio
async def test_process_announcement_missing_required_fields(ai_processor):
    # Mock OpenAI response missing required fields
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '''
    {
      "title": "Test Event",
      "content": "Test Content"
    }
    '''

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result['success'] is False
        assert "抽出が失敗しました" in result['error']
