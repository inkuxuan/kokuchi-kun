import pytest
import json
import os
import sys
from unittest.mock import patch, AsyncMock
from dotenv import load_dotenv
from utils.ai_processor import AIProcessor
import logging

# Configure logging to output to console
logging.basicConfig(
    level=logging.INFO,
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv(".test.env")


class TestAIProcessor:  # Note: removed unittest.TestCase
    def setup_method(self):  # pytest setup method
        # Create AI processor with test config
        self.ai_config = {
            'api_key': os.getenv('OPENROUTER_TEST_API_KEY', 'dummy-key'),
            'model': os.getenv('OPENROUTER_TEST_MODEL', 'test-model')
        }
        self.ai_processor = AIProcessor(self.ai_config)
        
    @pytest.mark.asyncio  # Mark test as async
    @patch('openai.AsyncOpenAI')
    async def test_process_valid_announcement(self, mock_openai):
        """Test if AI can extract data from a valid announcement message"""
        # Setup mock response
        mock_instance = AsyncMock()
        mock_openai.return_value = mock_instance
        
        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(
                message=AsyncMock(
                    content=json.dumps({
                        "date": "2025-01-01",
                        "time": "16:00",
                        "title": "テストイベント開催のお知らせ",
                        "content": "テストイベントを開催します！\n途中参加、退室自由です。"
                    })
                )
            )
        ]
        mock_instance.chat.completions.create.return_value = mock_response
        
        # Test message
        test_message = """
===VRCグループ告知リクエスト テンプレート===
@vrchat-announce-bot （必ずメンションしてください）
告知日付：2025年1月1日 16:00

告知タイトル：テストイベント開催のお知らせ

告知内容（できれば前後単独の行で" ``` "で囲んでください）：
テストイベントを開催します！
途中参加、退室自由です。
        """
        
        # Process the message
        result = await self.ai_processor.process_announcement(test_message)
        
        # Check result
        assert result['success']
        assert result['title'] == "テストイベント開催のお知らせ"
        assert "テストイベント" in result['content']
        assert "途中参加" in result['content']
        assert result['formatted_date_time'] == "2025年01月01日 16:00"
        
        # Verify AI was called with correct prompt
        mock_instance.chat.completions.create.assert_called_once()
        call_args = mock_instance.chat.completions.create.call_args[1]
        assert call_args['model'] == self.ai_config['model']
        assert '以下のDiscordメッセージから告知情報を抽出してください' in call_args['messages'][0]['content']

    @pytest.mark.asyncio
    @patch('openai.AsyncOpenAI')
    async def test_process_markdown_response(self, mock_openai):
        """Test if AI processor can handle markdown formatted responses"""
        # Setup mock response with markdown code blocks
        mock_instance = AsyncMock()
        mock_openai.return_value = mock_instance
        
        markdown_response = """
```json
{
  "date": "2025-02-15",
  "time": "18:30",
  "title": "週末パーティー",
  "content": "週末パーティーを開催します。ぜひご参加ください！"
}
```
        """
        
        mock_response = AsyncMock()
        mock_response.choices = [AsyncMock(message=AsyncMock(content=markdown_response))]
        mock_instance.chat.completions.create.return_value = mock_response
        
        # Test message
        test_message = """
===VRCグループ告知リクエスト テンプレート===
@vrchat-announce-bot
告知日付：2025年2月15日 18:30

告知タイトル：週末パーティー

告知内容：
週末パーティーを開催します。ぜひご参加ください！
        """
        
        # Process the message
        result = await self.ai_processor.process_announcement(test_message)
        
        # Check result
        assert result['success']
        assert result['title'] == "週末パーティー"
        assert "週末パーティー" in result['content']
        assert result['formatted_date_time'] == "2025年02月15日 18:30"

    @pytest.mark.asyncio
    @patch('openai.AsyncOpenAI')
    async def test_process_invalid_date_format(self, mock_openai):
        """Test if AI can handle unusual date formats"""
        # Setup mock response with unusual date format
        mock_instance = AsyncMock()
        mock_openai.return_value = mock_instance
        
        mock_response = AsyncMock()
        mock_response.choices = [
            AsyncMock(
                message=AsyncMock(
                    content=json.dumps({
                        "date": "2025/03/20",  # Format with slashes
                        "time": "20:45",
                        "title": "特別イベント",
                        "content": "特別イベントを開催します。"
                    })
                )
            )
        ]
        mock_instance.chat.completions.create.return_value = mock_response
        
        # Test message with unusual date format
        test_message = """
===VRCグループ告知リクエスト テンプレート===
@vrchat-announce-bot
告知日付：2025/3/20 20:45分

告知タイトル：特別イベント

告知内容：
特別イベントを開催します。
        """
        
        # Process the message
        result = await self.ai_processor.process_announcement(test_message)
        
        # Since we're mocking the AI response, we should get a valid result
        # even though the input format is unusual
        assert result['success']
        assert result['title'] == "特別イベント"
        
        # Since we're passing "2025/03/20" to the mocked AI, make sure our processor
        # handles this format correctly
        try:
            assert result['formatted_date_time'] == "2025年03月20日 20:45"
        except AssertionError:
            # If our processor can't handle it, update it to support more formats
            assert False, "AI processor should handle date format with slashes"

    @pytest.mark.asyncio
    @patch('openai.AsyncOpenAI')
    async def test_ai_error_handling(self, mock_openai):
        """Test how AI processor handles API errors"""
        # Setup mock to raise an exception
        mock_instance = AsyncMock()
        mock_openai.return_value = mock_instance
        mock_instance.chat.completions.create.side_effect = Exception("API error")
        
        # Test message
        test_message = """
===VRCグループ告知リクエスト テンプレート===
@vrchat-announce-bot
告知日付：2025年4月1日 12:00

告知タイトル：エイプリルフール

告知内容：
エイプリルフールのイベントです。
        """
        
        # Process the message
        result = await self.ai_processor.process_announcement(test_message)
        
        # Check error handling
        assert not result['success']
        assert "error" in result
        assert "API error" in result['error']

    @pytest.mark.asyncio
    async def test_real_llm_extraction(self):
        """Test if the actual LLM can correctly extract announcement data"""
        # Use the real AI processor (no mocks)
        ai_processor = AIProcessor({
            'api_key': os.getenv('OPENROUTER_TEST_API_KEY'),
            'model': os.getenv('OPENROUTER_TEST_MODEL')
        })
        
        # Skip test if no API key is available
        if not os.getenv('OPENROUTER_TEST_API_KEY'):
            pytest.skip("OpenRouter API key not available")
        
        # Test message with known expected output
        test_message = """
===VRCグループ告知リクエスト テンプレート===
@vrchat-announce-bot
告知日付：2025年1月1日 16:00

告知タイトル：テストイベント開催のお知らせ

告知内容：
テストイベントを開催します！
途中参加、退室自由です。
        """
        
        logger.info(f"Testing with content: {test_message}")
        
        # Process with real LLM
        result = await ai_processor.process_announcement(test_message)
        
        logger.info(f"Raw LLM result: {result}")
        
        # Check actual LLM extraction results
        assert result['success']
        assert result['title'] == "テストイベント開催のお知らせ"
        assert "テストイベント" in result['content']
        assert "途中参加" in result['content']
        assert result['formatted_date_time'] == "2025年01月01日 16:00" 