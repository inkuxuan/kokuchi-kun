"""Retry transient VRChat write failures once after three seconds."""

from http.client import RemoteDisconnected
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from urllib3.exceptions import ProtocolError

from kokuchi.services.vrchat_api import VRChatAPI


def disconnected() -> ProtocolError:
    return ProtocolError("Connection aborted.", RemoteDisconnected("Remote end closed connection without response"))


class TestWriteConnectionRetry(IsolatedAsyncioTestCase):
    def setUp(self):
        self.api = VRChatAPI({"username": "user", "password": "password"}, MagicMock())
        self.api.api_client = MagicMock()
        self.api.authenticated = True

    @patch("kokuchi.services.vrchat_api.asyncio.sleep", new_callable=AsyncMock)
    @patch("kokuchi.services.vrchat_api.GroupsApi")
    async def test_post_retries_after_disconnect(self, groups_api_class, sleep):
        post = MagicMock(id="post-id")
        groups_api_class.return_value.add_group_post.side_effect = [disconnected(), post]

        result = await self.api.post_announcement("grp-id", "Title", "Content")

        self.assertTrue(result.success)
        self.assertIs(result.data["group_post"], post)
        self.assertEqual(groups_api_class.return_value.add_group_post.call_count, 2)
        sleep.assert_awaited_once_with(3)

    @patch("kokuchi.services.vrchat_api.asyncio.sleep", new_callable=AsyncMock)
    @patch("vrchatapi.api.calendar_api.CalendarApi")
    async def test_calendar_retries_after_disconnect(self, calendar_api_class, sleep):
        event = MagicMock(id="event-id")
        calendar_api_class.return_value.create_group_calendar_event.side_effect = [disconnected(), event]

        result = await self.api.create_group_calendar_event(
            "grp-id", "Title", "Content", 1_800_000_000, 1_800_003_600
        )

        self.assertTrue(result.success)
        self.assertEqual(result.data["event_id"], "event-id")
        self.assertEqual(calendar_api_class.return_value.create_group_calendar_event.call_count, 2)
        sleep.assert_awaited_once_with(3)

    @patch("kokuchi.services.vrchat_api.asyncio.sleep", new_callable=AsyncMock)
    @patch("kokuchi.services.vrchat_api.GroupsApi")
    async def test_second_disconnect_returns_failure(self, groups_api_class, sleep):
        groups_api_class.return_value.add_group_post.side_effect = [disconnected(), disconnected()]

        result = await self.api.post_announcement("grp-id", "Title", "Content")

        self.assertFalse(result.success)
        self.assertEqual(groups_api_class.return_value.add_group_post.call_count, 2)
        sleep.assert_awaited_once_with(3)

    @patch("kokuchi.services.vrchat_api.asyncio.sleep", new_callable=AsyncMock)
    @patch("kokuchi.services.vrchat_api.GroupsApi")
    async def test_other_errors_are_not_retried(self, groups_api_class, sleep):
        groups_api_class.return_value.add_group_post.side_effect = ValueError("invalid request")

        result = await self.api.post_announcement("grp-id", "Title", "Content")

        self.assertFalse(result.success)
        self.assertEqual(groups_api_class.return_value.add_group_post.call_count, 1)
        sleep.assert_not_awaited()
