import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from utils.vrchat_api import VRChatAPI
from vrchatapi.exceptions import UnauthorizedException, ApiException
from utils.messages import Messages

class TestVRChatAPIAuth(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            'username': 'user',
            'password': 'password',
            'group_id': 'group_id',
            'cookie_file': 'test_cookies.json'
        }
        self.api = VRChatAPI(self.config)
        self.api.api_client = MagicMock()
        self.api.authenticated = True
        self.api.otp_callback = AsyncMock()

    @patch('utils.vrchat_api.AuthenticationApi')
    async def test_authenticate_totp_retry(self, MockAuthApi):
        # Setup mock
        auth_api = MockAuthApi.return_value

        # Scenario:
        # 1. get_current_user raises UnauthorizedException (trigger 2FA)
        # 2. verify2_fa raises ApiException(400) (Wrong code)
        # 3. verify2_fa succeeds (Correct code)
        # 4. get_current_user succeeds

        unauth_exc = UnauthorizedException(status=200, reason="2 Factor Authentication")

        # Side effect for get_current_user:
        # First call: Unauthorized (triggers 2FA flow)
        # Second call (after 2FA): Success
        auth_api.get_current_user.side_effect = [unauth_exc, MagicMock(id='user_id', display_name='User')]

        # Side effect for verify2_fa:
        # First call: 400 Bad Request
        # Second call: Success
        bad_req = ApiException(status=400, reason="Bad Request")
        auth_api.verify2_fa.side_effect = [bad_req, None]

        # OTP callback returns "wrong" then "correct"
        self.api.otp_callback.side_effect = ["wrong", "correct"]

        # Mock _save_cookies to avoid file IO
        self.api._save_cookies = MagicMock()

        # Run
        result = await self.api._authenticate()

        # Verify
        self.assertTrue(result['success'])
        self.assertEqual(auth_api.verify2_fa.call_count, 2)
        self.assertEqual(self.api.otp_callback.call_count, 2)

    @patch('utils.vrchat_api.AuthenticationApi')
    async def test_check_auth_status_reauth(self, MockAuthApi):
        # Setup mock
        auth_api = MockAuthApi.return_value

        # get_current_user raises UnauthorizedException
        unauth_exc = UnauthorizedException(status=401, reason="Unauthorized")
        auth_api.get_current_user.side_effect = unauth_exc

        # Mock _authenticate to succeed
        self.api._authenticate = AsyncMock(return_value={'success': True, 'reauthenticated': True})

        # Run
        result = await self.api.check_auth_status()

        # Verify
        self.assertTrue(result['success'])
        self.assertTrue(result.get('reauthenticated'))
        self.api._authenticate.assert_called_once()

    @patch('utils.vrchat_api.GroupsApi')
    @patch('utils.vrchat_api.AuthenticationApi')
    async def test_post_announcement_reauth_retry(self, MockAuthApi, MockGroupsApi):
        # Setup mock
        groups_api = MockGroupsApi.return_value

        # add_group_post raises UnauthorizedException first, then succeeds
        unauth_exc = UnauthorizedException(status=401, reason="Unauthorized")
        groups_api.add_group_post.side_effect = [
            unauth_exc,
            MagicMock(id='post_id')
        ]

        # Mock _authenticate to succeed
        self.api._authenticate = AsyncMock(return_value={'success': True})

        # Run
        result = await self.api.post_announcement("Title", "Content")

        # Verify
        self.assertTrue(result['success'])
        self.assertEqual(groups_api.add_group_post.call_count, 2)
        self.api._authenticate.assert_called_once()

if __name__ == '__main__':
    unittest.main()
