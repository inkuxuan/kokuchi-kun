import logging
import json
import openai
from datetime import datetime, timedelta
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
            
            jst = pytz.timezone('Asia/Tokyo')
            
            # Extract Announcement Time
            if not parsed_response.get('announcement_date') or not parsed_response.get('announcement_time'):
                 return {"success": False, "error": Messages.Error.AI_ANNOUNCEMENT_TIME_FAIL}

            ann_dt_str = f"{parsed_response['announcement_date']} {parsed_response['announcement_time']}"
            ann_dt = parser.parse(ann_dt_str)
            ann_dt = jst.localize(ann_dt.replace(tzinfo=None))
            announcement_timestamp = int(ann_dt.timestamp())

            # Extract Event Start Time
            if not parsed_response.get('event_start_date') or not parsed_response.get('event_start_time'):
                 return {"success": False, "error": Messages.Error.AI_EVENT_TIME_FAIL}

            event_start_str = f"{parsed_response['event_start_date']} {parsed_response['event_start_time']}"
            event_start_dt = parser.parse(event_start_str)
            event_start_dt = jst.localize(event_start_dt.replace(tzinfo=None))
            event_start_timestamp = int(event_start_dt.timestamp())

            # Extract or Default Event End Time
            if parsed_response.get('event_end_date') and parsed_response.get('event_end_time'):
                event_end_str = f"{parsed_response['event_end_date']} {parsed_response['event_end_time']}"
                event_end_dt = parser.parse(event_end_str)
                event_end_dt = jst.localize(event_end_dt.replace(tzinfo=None))
                event_end_timestamp = int(event_end_dt.timestamp())
            else:
                # Default to 1 hour after start
                event_end_dt = event_start_dt + timedelta(hours=1)
                event_end_timestamp = int(event_end_dt.timestamp())

            return {
                "success": True,
                "timestamp": announcement_timestamp, # Kept for backward compatibility logic in cog
                "announcement_timestamp": announcement_timestamp,
                "event_start_timestamp": event_start_timestamp,
                "event_end_timestamp": event_end_timestamp,
                "formatted_date_time": ann_dt.strftime('%Y年%m月%d日 %H:%M'),
                "title": parsed_response["title"],
                "content": parsed_response["content"]
            }
            
        except Exception as e:
            logger.error(Messages.Log.AI_PROCESS_ERROR.format(e))
            return {"success": False, "error": Messages.Error.AI_ERROR.format(str(e))}
