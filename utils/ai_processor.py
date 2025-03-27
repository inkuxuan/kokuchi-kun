import logging
import json
import openai
from datetime import datetime
import pytz
from dateutil import parser

logger = logging.getLogger(__name__)

class AIProcessor:
    def __init__(self, config):
        self.api_key = config['api_key']
        self.model = config['model']
        openai.api_key = self.api_key
        openai.api_base = "https://openrouter.ai/api/v1"
        
    async def process_announcement(self, message_content):
        """Process the announcement message and extract details"""
        try:
            logger.info("Processing announcement with AI")
            
            # Prepare the prompt
            prompt = f"""
以下のDiscordメッセージから告知情報を抽出してください：
1. 告知予定の日時（日本時間）
2. 告知のタイトル
3. 告知の内容

メッセージ:
{message_content}

結果は以下のJSONフォーマットのみで返してください。マークダウンや説明は不要です：
{{
  "date": "YYYY-MM-DD",
  "time": "HH:MM",
  "title": "タイトル",
  "content": "内容"
}}
            """
            
            # Call OpenRouter API
            headers = {
                "HTTP-Referer": "https://vrchat-announce-bot.example.com",
                "X-Title": "VRChat Announcement Bot"
            }
            
            response = await openai.AsyncOpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.api_key,
                default_headers=headers
            ).chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            # Extract the response
            ai_response = response.choices[0].message.content
            logger.info(f"Raw AI response: {ai_response}")
            
            # Clean up markdown if present
            if "```" in ai_response:
                # Extract content between code blocks
                for block in ai_response.split("```"):
                    if "{" in block and "}" in block:
                        ai_response = block.strip()
                        if ai_response.startswith("json"):
                            ai_response = ai_response[4:].strip()
                        break
            
            # Parse the JSON
            parsed_response = json.loads(ai_response)
            logger.info(f"Parsed response: {parsed_response}")
            
            # Convert to timestamp
            jst = pytz.timezone('Asia/Tokyo')
            
            # Parse date and time with flexible format detection
            date_time_str = f"{parsed_response['date']} {parsed_response['time']}"
            date_time = parser.parse(date_time_str)
            
            # Continue with timezone handling
            date_time = jst.localize(date_time.replace(tzinfo=None))
            timestamp = int(date_time.timestamp())
            
            return {
                "success": True,
                "timestamp": timestamp,
                "formatted_date_time": date_time.strftime('%Y年%m月%d日 %H:%M'),
                "title": parsed_response["title"],
                "content": parsed_response["content"]
            }
            
        except Exception as e:
            logger.error(f"Error processing with AI: {e}")
            return {"success": False, "error": f"AI処理中にエラーが発生しました。{str(e)}"} 