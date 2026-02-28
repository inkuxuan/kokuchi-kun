import logging
import json
import re
import calendar
import openai
from datetime import datetime, timedelta
import pytz
from dateutil import parser
from kokuchi.common.messages import Messages
from kokuchi.common.models import AIProcessingResult

logger = logging.getLogger(__name__)


def _sanitize_datetime(date_str: str, time_str: str) -> tuple[str, str]:
    """Sanitize LLM-generated date/time strings before parsing.

    Handles:
    - Overflow hours: 26:00 → next day 02:00
    - Overflow days: 2026-02-29 → 2026-03-01 (carry-over arithmetic)
    """
    # Normalize overflow hours (e.g. 26:00 → extra_days=1, hour=2)
    extra_days = 0
    time_match = re.match(r'^(\d+):(\d{2})(?::\d{2})?$', time_str.strip())
    if time_match:
        hours = int(time_match.group(1))
        minutes = time_match.group(2)
        if hours >= 24:
            extra_days = hours // 24
            hours = hours % 24
            time_str = f"{hours:02d}:{minutes}"

    # Normalize overflow days in date (e.g. 2026-02-29, 2026-02-30)
    date_match = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', date_str.strip())
    if date_match:
        year, month, day = int(date_match.group(1)), int(date_match.group(2)), int(date_match.group(3))
        month = max(1, min(12, month))
        max_day = calendar.monthrange(year, month)[1]
        if day > max_day or extra_days:
            # Carry-over arithmetic via timedelta (handles month/year boundaries)
            dt = datetime(year, month, 1) + timedelta(days=day - 1 + extra_days)
            date_str = dt.strftime('%Y-%m-%d')
            extra_days = 0  # already applied

    if extra_days:
        # extra_days not consumed above (date didn't match pattern); best-effort skip
        logger.warning(f"Could not apply extra_days={extra_days} to date_str={date_str!r}")

    return date_str, time_str


class AIProcessor:
    def __init__(self, config):
        self.api_key = config['api_key']
        self.model = config['model']
        self.prompt = config['prompt']
        openai.api_key = self.api_key
        openai.api_base = "https://openrouter.ai/api/v1"
        
    async def process_announcement(self, message_content) -> AIProcessingResult:
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
                return AIProcessingResult(success=False, error=Messages.Error.AI_ANNOUNCEMENT_TIME_FAIL)

            ann_date, ann_time = _sanitize_datetime(parsed_response['announcement_date'], parsed_response['announcement_time'])
            ann_dt_str = f"{ann_date} {ann_time}"
            ann_dt = parser.parse(ann_dt_str)
            ann_dt = jst.localize(ann_dt.replace(tzinfo=None))
            announcement_timestamp = int(ann_dt.timestamp())

            # Extract Event Start Time
            if not parsed_response.get('event_start_date') or not parsed_response.get('event_start_time'):
                return AIProcessingResult(success=False, error=Messages.Error.AI_EVENT_TIME_FAIL)

            es_date, es_time = _sanitize_datetime(parsed_response['event_start_date'], parsed_response['event_start_time'])
            event_start_str = f"{es_date} {es_time}"
            event_start_dt = parser.parse(event_start_str)
            event_start_dt = jst.localize(event_start_dt.replace(tzinfo=None))
            event_start_timestamp = int(event_start_dt.timestamp())

            # Extract or Default Event End Time
            if parsed_response.get('event_end_date') and parsed_response.get('event_end_time'):
                ee_date, ee_time = _sanitize_datetime(parsed_response['event_end_date'], parsed_response['event_end_time'])
                event_end_str = f"{ee_date} {ee_time}"
                event_end_dt = parser.parse(event_end_str)
                event_end_dt = jst.localize(event_end_dt.replace(tzinfo=None))
                event_end_timestamp = int(event_end_dt.timestamp())
            else:
                # Default to 1 hour after start
                event_end_dt = event_start_dt + timedelta(hours=1)
                event_end_timestamp = int(event_end_dt.timestamp())

            # Extract title and event_title, applying truncation
            title = parsed_response["title"][:128]
            event_title = parsed_response.get("event_title", title)
            if not event_title:
                event_title = title
            event_title = event_title[:128]

            return AIProcessingResult(
                success=True,
                timestamp=announcement_timestamp,
                announcement_timestamp=announcement_timestamp,
                event_start_timestamp=event_start_timestamp,
                event_end_timestamp=event_end_timestamp,
                formatted_date_time=ann_dt.strftime('%Y年%m月%d日 %H:%M'),
                title=title,
                event_title=event_title,
                content=parsed_response["content"],
            )

        except Exception as e:
            logger.error(Messages.Log.AI_PROCESS_ERROR.format(e))
            return AIProcessingResult(success=False, error=Messages.Error.AI_ERROR.format(str(e)))
