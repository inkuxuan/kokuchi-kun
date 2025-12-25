import logging
import json
import openai
from datetime import datetime
import pytz
from dateutil import parser
from utils.messages import Messages

logger = logging.getLogger(__name__)

class AIProcessor:
    def __init__(self, config):
        self.api_key = config['api_key']
        self.model = config['model']
        self.prompt = config['prompt']
        openai.api_key = self.api_key
        openai.api_base = "https://openrouter.ai/api/v1"
        
    async def process_announcement(self, message_content):
        """Process the announcement message and extract details"""
        try:
            logger.info(Messages.Log.AI_PROCESSING)
            
            # Prepare the prompt
            prompt = self.prompt.replace("__message_content__", message_content)
            
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
            logger.info(Messages.Log.AI_RAW_RESPONSE.format(ai_response))
            
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
            logger.info(Messages.Log.AI_PARSED_RESPONSE.format(parsed_response))
            
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
            logger.error(Messages.Log.AI_PROCESS_ERROR.format(e))
            return {"success": False, "error": Messages.Error.AI_ERROR.format(str(e))}