import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime
import pytz
from kokuchi.services.ai_processor import AIProcessor, _sanitize_datetime

# ── _sanitize_datetime unit tests ────────────────────────────────────────────

@pytest.mark.parametrize("date_str,time_str,expected_date,expected_time", [
    # Valid inputs → unchanged
    ("2026-02-28", "20:00", "2026-02-28", "20:00"),
    ("2026-12-31", "23:59", "2026-12-31", "23:59"),
    # Overflow day: Feb 29 in non-leap year → Mar 1
    ("2026-02-29", "01:00", "2026-03-01", "01:00"),
    # Overflow day: Feb 30 in non-leap year → Mar 2
    ("2026-02-30", "01:00", "2026-03-02", "01:00"),
    # Overflow day: Apr 31 → May 1
    ("2026-04-31", "12:00", "2026-05-01", "12:00"),
    # Overflow day: Dec 32 → Jan 1 of next year
    ("2026-12-32", "00:00", "2027-01-01", "00:00"),
    # Overflow hours: 24:00 → next day 00:00
    ("2026-02-28", "24:00", "2026-03-01", "00:00"),
    # Overflow hours: 26:00 → next day 02:00
    ("2026-02-28", "26:00", "2026-03-01", "02:00"),
    # Overflow hours crossing month boundary: Feb 28 + 25h → Mar 1 01:00
    ("2026-02-28", "25:00", "2026-03-01", "01:00"),
    # Overflow hours crossing year boundary: Dec 31 + 24h → Jan 1 next year
    ("2026-12-31", "24:00", "2027-01-01", "00:00"),
    # Combined: invalid day + overflow hours
    ("2026-02-29", "25:00", "2026-03-02", "01:00"),
    # Leap year: Feb 29 is valid in 2024 → unchanged
    ("2024-02-29", "12:00", "2024-02-29", "12:00"),
])
def test_sanitize_datetime(date_str, time_str, expected_date, expected_time):
    result_date, result_time = _sanitize_datetime(date_str, time_str)
    assert result_date == expected_date
    assert result_time == expected_time


# ── AIProcessor integration tests ────────────────────────────────────────────

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

        assert result.success is True
        assert result.title == "Test Event"
        assert result.content == "Test Content"
        assert result.event_title == "Test Event" # Fallback check

        # Verify timestamps (approximate check due to timezone complexity in test env vs implementation)
        # Just check relative order
        assert result.announcement_timestamp < result.event_start_timestamp
        assert result.event_start_timestamp < result.event_end_timestamp

        # Check specific values (JST is UTC+9)
        # Announcement: 2023-10-27 20:00 JST -> 2023-10-27 11:00 UTC
        # Event Start: 2023-10-28 21:00 JST -> 2023-10-28 12:00 UTC

        jst = pytz.timezone('Asia/Tokyo')
        ann_dt = jst.localize(datetime(2023, 10, 27, 20, 0))
        assert result.announcement_timestamp == int(ann_dt.timestamp())

@pytest.mark.asyncio
async def test_process_announcement_with_event_title(ai_processor):
    # Mock OpenAI response with event_title
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '''
    {
      "announcement_date": "2023-10-27",
      "announcement_time": "20:00",
      "event_start_date": "2023-10-28",
      "event_start_time": "21:00",
      "event_end_date": "2023-10-28",
      "event_end_time": "22:00",
      "title": "Application Title",
      "event_title": "Event Title",
      "content": "Test Content"
    }
    '''

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result.success is True
        assert result.title == "Application Title"
        assert result.event_title == "Event Title"

@pytest.mark.asyncio
async def test_process_announcement_truncation(ai_processor):
    # Mock OpenAI response with long titles
    long_title = "A" * 150
    long_event_title = "B" * 150
    mock_response = MagicMock()
    mock_response.choices[0].message.content = f'''
    {{
      "announcement_date": "2023-10-27",
      "announcement_time": "20:00",
      "event_start_date": "2023-10-28",
      "event_start_time": "21:00",
      "title": "{long_title}",
      "event_title": "{long_event_title}",
      "content": "Test Content"
    }}
    '''

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result.success is True
        assert len(result.title) == 128
        assert len(result.event_title) == 128
        assert result.title == "A" * 128
        assert result.event_title == "B" * 128

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

        assert result.success is True
        # Check if end time is start time + 1 hour
        assert result.event_end_timestamp == result.event_start_timestamp + 3600

@pytest.mark.asyncio
async def test_process_announcement_overflow_end_time(ai_processor):
    """LLM outputs 24:00 for an event ending at midnight of the next day.
    The sanitizer must carry the date forward instead of producing 00:00 on the same day."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '''
    {
      "announcement_date": "2026-02-28",
      "announcement_time": "23:00",
      "event_start_date": "2026-02-28",
      "event_start_time": "23:00",
      "event_end_date": "2026-02-28",
      "event_end_time": "24:00",
      "title": "テストテスト",
      "content": "今日23時から24時まで釣りたい！（テスト）"
    }
    '''

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result.success is True
        jst = pytz.timezone('Asia/Tokyo')
        expected_end = jst.localize(datetime(2026, 3, 1, 0, 0))
        assert result.event_end_timestamp == int(expected_end.timestamp())
        # end must be after start
        assert result.event_end_timestamp > result.event_start_timestamp


@pytest.mark.asyncio
async def test_process_announcement_unescaped_quotes_in_content(ai_processor):
    """AI sometimes returns unescaped double quotes inside JSON string values,
    e.g. content: "テーマは"あなたの好きな食べ物"です" — json-repair must fix this."""
    mock_response = MagicMock()
    # Intentionally malformed: unescaped ASCII double quotes around the topic name
    mock_response.choices[0].message.content = (
        '{'
        '"announcement_date": "2026-03-12",'
        '"announcement_time": "21:00",'
        '"event_start_date": "2026-03-13",'
        '"event_start_time": "22:00",'
        '"event_end_date": "2026-03-13",'
        '"event_end_time": "23:00",'
        '"title": "活動予告",'
        '"event_title": "第136回中日交流会",'
        '"content": "这次的主题是"你小时候最喜欢吃的零食"。到时见！"'
        '}'
    )

    with patch('openai.resources.chat.completions.AsyncCompletions.create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response

        result = await ai_processor.process_announcement("Test message")

        assert result.success is True
        assert result.title == "活動予告"
        assert result.event_title == "第136回中日交流会"
        assert "你小时候最喜欢吃的零食" in result.content


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

        assert result.success is False
        assert "抽出が失敗しました" in result.error
