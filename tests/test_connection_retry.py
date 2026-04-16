"""Tests for the connection retry logic in main()."""

import asyncio
import os
from unittest.mock import patch, MagicMock, AsyncMock, mock_open

import pytest
import yaml

from kokuchi.bot import main


def _make_config():
    return {
        'discord': {
            'token': 'fake-token',
            'guild_id': 123,
            'admin_role_id': 456,
            'admin_user_ids': [],
        },
        'openrouter': {
            'prompt_file': 'prompt.txt',
            'prompt': 'test prompt',
        },
        'vrchat': {},
        'database': {'path': ':memory:'},
    }


@pytest.fixture
def mock_main_preamble():
    """Mock everything before the retry loop: arg parsing, env loading, config."""
    args = MagicMock()
    args.env = '.env'
    config = _make_config()
    with (
        patch('kokuchi.bot.parse_arguments', return_value=args),
        patch('kokuchi.bot.ensure_env_exists'),
        patch('kokuchi.bot.ensure_config_exists'),
        patch('kokuchi.bot.load_environment'),
        patch('kokuchi.bot.yaml.safe_load', return_value=config),
        patch('builtins.open', MagicMock()),
    ):
        yield


@pytest.fixture
def mock_bot_class():
    with patch('kokuchi.bot.VRChatAnnounceBot') as cls:
        cls.return_value.config = _make_config()
        cls.return_value.close = AsyncMock()
        yield cls


class TestRetryLogic:
    """Unit tests for the retry loop using a fully mocked bot."""

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self, mock_main_preamble, mock_bot_class):
        """bot.start() is retried on transient OSError (e.g. DNS failure)."""
        bot = mock_bot_class.return_value
        bot.start = AsyncMock(side_effect=[OSError("DNS resolution failed"), None])

        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            await main()

        # First bot fails, second bot succeeds
        assert mock_bot_class.call_count == 2
        mock_sleep.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_exponential_backoff(self, mock_main_preamble, mock_bot_class):
        """Retry delay doubles each time."""
        bot = mock_bot_class.return_value
        bot.start = AsyncMock(
            side_effect=[
                OSError("fail 1"),
                OSError("fail 2"),
                OSError("fail 3"),
                OSError("fail 4"),
                None,
            ]
        )

        sleep_delays = []

        async def capture_sleep(delay):
            sleep_delays.append(delay)

        with patch('asyncio.sleep', side_effect=capture_sleep):
            await main()

        assert sleep_delays == [5, 10, 20, 40]

    @pytest.mark.asyncio
    async def test_backoff_caps_at_60s(self, mock_main_preamble, mock_bot_class):
        """Retry delay is capped at 60 seconds."""
        bot = mock_bot_class.return_value
        bot.start = AsyncMock(
            side_effect=[OSError(f"fail {i}") for i in range(6)] + [None]
        )

        sleep_delays = []

        async def capture_sleep(delay):
            sleep_delays.append(delay)

        with patch('asyncio.sleep', side_effect=capture_sleep):
            await main()

        assert sleep_delays == [5, 10, 20, 40, 60, 60]

    @pytest.mark.asyncio
    async def test_login_failure_propagates(self, mock_main_preamble, mock_bot_class):
        """discord.LoginFailure is NOT retried — it propagates immediately."""
        import discord

        bot = mock_bot_class.return_value
        bot.start = AsyncMock(side_effect=discord.LoginFailure("Improper token"))

        with pytest.raises(discord.LoginFailure):
            with patch('asyncio.sleep', new_callable=AsyncMock):
                await main()

        assert bot.start.call_count == 1

    @pytest.mark.asyncio
    async def test_close_called_on_connection_error(self, mock_main_preamble, mock_bot_class):
        """bot.close() is called between retry attempts to clean up the session."""
        bot = mock_bot_class.return_value
        bot.start = AsyncMock(side_effect=[OSError("DNS failure"), None])

        with patch('asyncio.sleep', new_callable=AsyncMock):
            await main()

        bot.close.assert_called()

    @pytest.mark.asyncio
    async def test_no_retry_on_clean_exit(self, mock_main_preamble, mock_bot_class):
        """When bot.start() returns cleanly, no retry happens."""
        bot = mock_bot_class.return_value
        bot.start = AsyncMock(return_value=None)

        with patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            await main()

        assert mock_bot_class.call_count == 1
        mock_sleep.assert_not_called()


class TestSmokeMainFunction:
    """Smoke tests that exercise main() with real config parsing.

    These use the real config.yaml.template and only mock external I/O
    (Firestore, Discord network calls, env files) to catch config-shape
    bugs like missing keys.
    """

    @pytest.fixture
    def template_config(self):
        """Load the real config.yaml.template."""
        with open('config.yaml.template', 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def smoke_env(self):
        """Set environment variables the bot expects, clean up after."""
        env_vars = {
            'DISCORD_TOKEN': 'smoke-test-token',
            'OPENROUTER_API_KEY': 'smoke-test-key',
            'VRCHAT_USERNAME': 'smoke-user',
            'VRCHAT_PASSWORD': 'smoke-pass',
        }
        old_values = {}
        for k, v in env_vars.items():
            old_values[k] = os.environ.get(k)
            os.environ[k] = v
        yield
        for k, v in old_values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    @pytest.fixture
    def mock_externals(self, template_config):
        """Mock external I/O while letting the bot init run with real config."""
        args = MagicMock()
        args.env = '.env'

        # Build a mock open that returns real config/prompt content
        real_open = open
        config_yaml = yaml.dump(template_config)

        def fake_open(path, *a, **kw):
            if isinstance(path, str):
                if 'config.yaml' in path:
                    return mock_open(read_data=config_yaml)()
                if 'prompt' in path:
                    return mock_open(read_data='You are a test prompt.')()
            return real_open(path, *a, **kw)

        with (
            patch('kokuchi.bot.parse_arguments', return_value=args),
            patch('kokuchi.bot.ensure_env_exists'),
            patch('kokuchi.bot.ensure_config_exists'),
            patch('kokuchi.bot.load_environment'),
            patch('builtins.open', side_effect=fake_open),
            patch('kokuchi.state.persistence.AsyncClient'),  # no real Firestore
            patch('kokuchi.services.vrchat_api.VRChatAPI.close'),  # no real VRChat cleanup
        ):
            yield

    @pytest.mark.asyncio
    async def test_main_with_template_config_starts_and_retries(
        self, mock_externals, smoke_env,
    ):
        """main() can construct a real bot from config.yaml.template and retry on OSError."""
        with (
            patch.object(
                __import__('kokuchi.bot', fromlist=['VRChatAnnounceBot']).VRChatAnnounceBot,
                'start',
                new_callable=AsyncMock,
                side_effect=[OSError("DNS failure"), None],
            ),
            patch.object(
                __import__('kokuchi.bot', fromlist=['VRChatAnnounceBot']).VRChatAnnounceBot,
                'close',
                new_callable=AsyncMock,
            ),
            patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep,
        ):
            await main()

        # Retried once then succeeded
        mock_sleep.assert_called_once_with(5)

    @pytest.mark.asyncio
    async def test_main_with_template_config_clean_start(
        self, mock_externals, smoke_env,
    ):
        """main() starts cleanly with no connection errors."""
        with patch.object(
            __import__('kokuchi.bot', fromlist=['VRChatAnnounceBot']).VRChatAnnounceBot,
            'start',
            new_callable=AsyncMock,
            return_value=None,
        ):
            await main()

    @pytest.mark.asyncio
    async def test_main_with_no_token_exits_cleanly(self, mock_externals):
        """main() exits without crashing when DISCORD_TOKEN is not set."""
        # Don't set smoke_env — no DISCORD_TOKEN in environment
        with patch.object(
            __import__('kokuchi.bot', fromlist=['VRChatAnnounceBot']).VRChatAnnounceBot,
            'start',
            new_callable=AsyncMock,
        ) as mock_start:
            await main()

        # start() should never be called since token is empty
        mock_start.assert_not_called()
