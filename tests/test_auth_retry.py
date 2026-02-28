import asyncio
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
from kokuchi.services.vrchat_api import VRChatAPI
from kokuchi.common.models import AuthResult, ApiResult
from vrchatapi.exceptions import UnauthorizedException, ApiException
from kokuchi.common.messages import Messages

class TestVRChatAPIAuth(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {
            'username': 'user',
            'password': 'password',
        }
        self.mock_persistence = MagicMock()
        self.mock_persistence.load_shared = AsyncMock(return_value={})
        self.mock_persistence.save_shared = AsyncMock(return_value=True)
        self.api = VRChatAPI(self.config, self.mock_persistence)
        self.api.api_client = MagicMock()
        self.api.authenticated = True
        self.api.otp_callback = AsyncMock()

    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
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
        auth_api.get_current_user.side_effect = [unauth_exc, MagicMock(id='user_id', username='user', display_name='User')]

        # Side effect for verify2_fa:
        # First call: 400 Bad Request
        # Second call: Success
        bad_req = ApiException(status=400, reason="Bad Request")
        auth_api.verify2_fa.side_effect = [bad_req, None]

        # OTP callback returns "wrong" then "correct"
        self.api.otp_callback.side_effect = ["wrong", "correct"]

        # Run
        result = await self.api._authenticate()

        # Verify
        self.assertTrue(result.success)
        self.assertEqual(auth_api.verify2_fa.call_count, 2)
        self.assertEqual(self.api.otp_callback.call_count, 2)

    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
    async def test_check_auth_status_reauth(self, MockAuthApi):
        # Setup mock
        auth_api = MockAuthApi.return_value

        # get_current_user raises UnauthorizedException
        unauth_exc = UnauthorizedException(status=401, reason="Unauthorized")
        auth_api.get_current_user.side_effect = unauth_exc

        # Mock _authenticate to succeed
        self.api._authenticate = AsyncMock(return_value=AuthResult(success=True, reauthenticated=True))

        # Run
        result = await self.api.check_auth_status()

        # Verify
        self.assertTrue(result.success)
        self.assertTrue(result.reauthenticated)
        self.api._authenticate.assert_called_once()

    @patch('kokuchi.services.vrchat_api.GroupsApi')
    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
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
        self.api._authenticate = AsyncMock(return_value=AuthResult(success=True))

        # Run
        result = await self.api.post_announcement("grp_test", "Title", "Content")

        # Verify
        self.assertTrue(result.success)
        self.assertEqual(groups_api.add_group_post.call_count, 2)
        self.api._authenticate.assert_called_once()

    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
    async def test_initialize_cookie_username_mismatch(self, MockAuthApi):
        """When cached cookie belongs to a different user, invalidate and re-auth with credentials"""
        auth_api = MockAuthApi.return_value

        # Cookie auth succeeds but returns a different username
        wrong_user = MagicMock(id='wrong_id', username='wrong_user', display_name='Wrong')
        correct_user = MagicMock(id='correct_id', username='user', display_name='User')

        # First call (cookie auth) returns wrong user, second call (credential auth) returns correct
        auth_api.get_current_user.side_effect = [wrong_user, correct_user]

        # Simulate saved cookies exist
        self.mock_persistence.load_shared = AsyncMock(return_value={
            'authCookie': 'old_cookie',
            'twoFactorAuthCookie': 'old_2fa',
        })

        # Need a fresh instance so api_client starts as None
        api = VRChatAPI(self.config, self.mock_persistence)
        api.otp_callback = AsyncMock()

        result = await api.initialize()

        self.assertTrue(result.success)
        self.assertEqual(result.username, 'user')
        # Cookies should have been invalidated (saved as empty dict)
        self.mock_persistence.save_shared.assert_any_call('vrchat_session', {})

    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
    async def test_initialize_cookie_username_match(self, MockAuthApi):
        """When cached cookie belongs to the configured user, use it directly"""
        auth_api = MockAuthApi.return_value

        correct_user = MagicMock(id='user_id', username='user', display_name='User')
        auth_api.get_current_user.return_value = correct_user

        self.mock_persistence.load_shared = AsyncMock(return_value={
            'authCookie': 'valid_cookie',
        })

        api = VRChatAPI(self.config, self.mock_persistence)
        result = await api.initialize()

        self.assertTrue(result.success)
        self.assertEqual(result.username, 'user')
        self.assertEqual(result.method, 'cookie')

    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
    async def test_check_auth_status_username_mismatch(self, MockAuthApi):
        """Heartbeat detects wrong user and triggers re-auth with credentials"""
        auth_api = MockAuthApi.return_value

        wrong_user = MagicMock(id='wrong_id', username='wrong_user', display_name='Wrong')
        correct_user = MagicMock(id='correct_id', username='user', display_name='User')

        # First call (heartbeat) returns wrong user, second call (credential re-auth) returns correct
        auth_api.get_current_user.side_effect = [wrong_user, correct_user]

        result = await self.api.check_auth_status()

        self.assertTrue(result.success)
        self.assertTrue(result.reauthenticated)
        # Cookies should have been invalidated
        self.mock_persistence.save_shared.assert_any_call('vrchat_session', {})

    @patch('kokuchi.services.vrchat_api.AuthenticationApi')
    async def test_check_auth_status_username_match(self, MockAuthApi):
        """Heartbeat with correct user returns success with username"""
        auth_api = MockAuthApi.return_value

        correct_user = MagicMock(id='user_id', username='user', display_name='User')
        auth_api.get_current_user.return_value = correct_user

        result = await self.api.check_auth_status()

        self.assertTrue(result.success)
        self.assertFalse(result.reauthenticated)
        self.assertEqual(result.username, 'user')

if __name__ == '__main__':
    unittest.main()
