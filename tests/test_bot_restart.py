"""Tests for the __main__ restart-on-critical-error logic in bot.py."""

import time
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


def _run_main_block():
    """Execute the __main__ while-loop logic extracted from bot.py."""
    import asyncio
    import traceback
    import logging

    logger = logging.getLogger("kokuchi")

    from kokuchi.bot import main

    while True:
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Critical error, restarting in 3 seconds: {e}")
            logger.error(f"Stack trace:\n{traceback.format_exc()}")
        else:
            break
        time.sleep(3)


@patch("kokuchi.bot.main", new_callable=AsyncMock)
@patch("time.sleep")
def test_restart_on_exception(mock_sleep, mock_main):
    """Script retries after an exception, then exits cleanly on success."""
    mock_main.side_effect = [
        ConnectionError("DNS resolution failed"),
        None,  # succeeds on second attempt
    ]

    _run_main_block()

    assert mock_main.call_count == 2
    mock_sleep.assert_called_once_with(3)


@patch("kokuchi.bot.main", new_callable=AsyncMock)
@patch("time.sleep")
def test_no_restart_on_clean_exit(mock_sleep, mock_main):
    """Script does not retry when main() returns cleanly."""
    mock_main.return_value = None

    _run_main_block()

    assert mock_main.call_count == 1
    mock_sleep.assert_not_called()


@patch("kokuchi.bot.main", new_callable=AsyncMock)
@patch("time.sleep")
def test_keyboard_interrupt_exits_immediately(mock_sleep, mock_main):
    """KeyboardInterrupt breaks the loop without retrying."""
    mock_main.side_effect = KeyboardInterrupt

    _run_main_block()

    assert mock_main.call_count == 1
    mock_sleep.assert_not_called()


@patch("kokuchi.bot.main", new_callable=AsyncMock)
@patch("time.sleep")
def test_multiple_failures_before_success(mock_sleep, mock_main):
    """Script retries multiple times until main() succeeds."""
    mock_main.side_effect = [
        OSError("Network unreachable"),
        ConnectionError("DNS failed"),
        RuntimeError("Something else"),
        None,  # success
    ]

    _run_main_block()

    assert mock_main.call_count == 4
    assert mock_sleep.call_count == 3
