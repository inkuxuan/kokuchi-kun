import logging
import os
import json
import vrchatapi
import sys
from datetime import datetime
import pytz
from vrchatapi.api.authentication_api import AuthenticationApi
from vrchatapi.api.groups_api import GroupsApi
from vrchatapi.exceptions import UnauthorizedException, ApiException
from vrchatapi.models.create_calendar_event_request import CreateCalendarEventRequest
from vrchatapi.models.two_factor_auth_code import TwoFactorAuthCode
from vrchatapi.models.two_factor_email_code import TwoFactorEmailCode
from utils.messages import Messages

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Add a console handler to ensure logs are output immediately
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

class VRChatAPI:
    def __init__(self, config):
        """Initialize with configuration but don't connect yet"""
        self.username = config['username']
        self.password = config['password']
        self.group_id = config['group_id']
        self.authenticated = False
        self.api_client = None
        self.current_user = None
        self.cookie_file = config.get('cookie_file', 'vrchat_session.json')
        self.failed_posts = []  # Store failed posts for retry
        self.otp_callback = None  # Callback function to request OTP
    
    def set_otp_callback(self, callback):
        """Set the callback function to request OTP"""
        self.otp_callback = callback
    
    async def initialize(self):
        """Initialize and authenticate with VRChat"""
        # Try to authenticate with saved cookies first
        if await self._try_cookie_auth():
            return {
                "success": True,
                "user_id": self.current_user.id,
                "display_name": self.current_user.display_name,
                "method": "cookie"
            }
        
        # Fall back to username/password auth with OTP
        return await self._authenticate_with_credentials()
    
    async def _try_cookie_auth(self):
        """Try to authenticate using saved cookies"""
        logger.info(Messages.Log.COOKIE_AUTH_ATTEMPT)
        
        try:
            if not os.path.exists(self.cookie_file):
                logger.warning(Messages.Log.NO_SESSION_FILE)
                return False
                
            with open(self.cookie_file, 'r') as f:
                cookie_data = json.load(f)
                
            auth_cookie = cookie_data.get('authCookie')
            two_factor_cookie = cookie_data.get('twoFactorAuthCookie')
            
            if not auth_cookie:
                logger.warning(Messages.Log.NO_AUTH_COOKIE)
                return False
                
            # Create a basic configuration
            configuration = vrchatapi.Configuration()
            
            # Create a new API client
            self.api_client = vrchatapi.ApiClient(configuration)
            self.api_client.user_agent = Messages.Const.VRC_USER_AGENT
            
            # Create and set cookies directly in the cookie jar
            from http.cookiejar import Cookie
            
            def make_cookie(name, value):
                return Cookie(
                    0,                  # version
                    name,               # name
                    value,              # value
                    None,               # port
                    False,              # port_specified
                    "api.vrchat.cloud", # domain (important!)
                    True,               # domain_specified
                    False,              # domain_initial_dot
                    "/",                # path (important!)
                    False,              # path_specified
                    False,              # secure
                    173106866300,       # expires (doesn't matter much)
                    False,              # discard
                    None,               # comment
                    None,               # comment_url
                    {}                  # rest
                )
            
            # Set the auth cookie
            self.api_client.rest_client.cookie_jar.set_cookie(
                make_cookie("auth", auth_cookie)
            )
            
            # Set the 2FA cookie if available
            if two_factor_cookie:
                self.api_client.rest_client.cookie_jar.set_cookie(
                    make_cookie("twoFactorAuth", two_factor_cookie)
                )
            
            # Try to get current user to validate cookie
            auth_api = AuthenticationApi(self.api_client)
            
            try:
                self.current_user = auth_api.get_current_user()
                self.authenticated = True
                
                logger.info(Messages.Log.COOKIE_AUTH_SUCCESS.format(self.current_user.display_name))
                return True
            except UnauthorizedException as e:
                logger.warning(Messages.Log.COOKIE_AUTH_FAIL_UNAUTH.format(e.reason))
                return False
            except ApiException as e:
                logger.warning(Messages.Log.COOKIE_AUTH_FAIL_API.format(str(e)))
                return False
            
        except Exception as e:
            logger.warning(Messages.Log.COOKIE_AUTH_FAIL.format(str(e)))
            # Clean up if cookie auth failed
            if self.api_client:
                self.api_client.close()
                self.api_client = None
            self.authenticated = False
            self.current_user = None
            return False
    
    def _save_cookies(self):
        """Save authentication cookies to file"""
        if not self.api_client or not self.authenticated:
            return False
            
        try:
            cookies = {}
            
            # Extract cookies properly from the cookie jar
            # This matches how the official example accesses cookies
            if hasattr(self.api_client.rest_client, 'cookie_jar') and hasattr(self.api_client.rest_client.cookie_jar, '_cookies'):
                cookie_jar = self.api_client.rest_client.cookie_jar._cookies
                
                # Check if the VRChat domain exists
                if "api.vrchat.cloud" in cookie_jar and "/" in cookie_jar["api.vrchat.cloud"]:
                    domain_cookies = cookie_jar["api.vrchat.cloud"]["/"]
                    
                    if "auth" in domain_cookies:
                        cookies['authCookie'] = domain_cookies["auth"].value
                        
                    if "twoFactorAuth" in domain_cookies:
                        cookies['twoFactorAuthCookie'] = domain_cookies["twoFactorAuth"].value
            
            # Verify we have the auth cookie before saving
            if 'authCookie' not in cookies:
                logger.warning(Messages.Log.NO_AUTH_COOKIE_SAVE)
                return False
                
            # Save to file
            with open(self.cookie_file, 'w') as f:
                json.dump(cookies, f)
                
            logger.info(Messages.Log.COOKIES_SAVED.format(self.cookie_file))
            return True
            
        except Exception as e:
            logger.error(Messages.Log.COOKIE_SAVE_FAIL.format(str(e)))
            return False
    
    async def _authenticate_with_credentials(self):
        """Authenticate with username and password"""
        # Create configuration with credentials
        configuration = vrchatapi.Configuration(
            username=self.username,
            password=self.password,
        )
        
        # Create a new API client
        self.api_client = vrchatapi.ApiClient(configuration)
        
        # Set User-Agent as required by VRChat
        self.api_client.user_agent = Messages.Const.VRC_USER_AGENT
        
        # Try to authenticate
        result = await self._authenticate()
        
        # Save cookies if authentication was successful
        if result.get('success') and self.authenticated:
            self._save_cookies()
            
        return result
    
    async def _authenticate(self):
        """Internal method to authenticate with VRChat - interactive for 2FA"""
        if not self.api_client:
            return {"success": False, "error": Messages.Error.API_CLIENT_NOT_INIT}
        
        try:
            # Create auth API instance
            auth_api = AuthenticationApi(self.api_client)
            
            try:
                # Attempt to get current user (this triggers authentication)
                self.current_user = auth_api.get_current_user()
                self.authenticated = True
                
                logger.info(Messages.Log.AUTH_SUCCESS.format(self.current_user.display_name))
                
                # Save cookies after successful authentication
                self._save_cookies()
                
                return {
                    "success": True,
                    "user_id": self.current_user.id,
                    "display_name": self.current_user.display_name,
                    "method": "password"
                }
                
            except UnauthorizedException as e:
                # Handle 2FA if needed
                if e.status == 200:
                    if "Email 2 Factor Authentication" in e.reason:
                        # Request OTP through callback
                        if not self.otp_callback:
                            return {"success": False, "error": Messages.Error.OTP_CALLBACK_NOT_SET}
                            
                        otp = await self.otp_callback("Email 2FA")
                        if not otp:
                            return {"success": False, "error": Messages.Error.NO_OTP_PROVIDED}
                            
                        try:
                            auth_api.verify2_fa_email_code(
                                two_factor_email_code=TwoFactorEmailCode(code=otp)
                            )
                            logger.info(Messages.Log.EMAIL_2FA_SUCCESS)
                        except Exception as e2:
                            logger.error(Messages.Log.EMAIL_2FA_FAIL.format(str(e2)))
                            return {"success": False, "error": Messages.Error.EMAIL_2FA_FAIL.format(str(e2))}
                            
                    elif "2 Factor Authentication" in e.reason:
                        # Request OTP through callback
                        if not self.otp_callback:
                            return {"success": False, "error": Messages.Error.OTP_CALLBACK_NOT_SET}
                            
                        otp = await self.otp_callback("TOTP 2FA")
                        if not otp:
                            return {"success": False, "error": Messages.Error.NO_OTP_PROVIDED}
                            
                        try:
                            auth_api.verify2_fa(
                                two_factor_auth_code=TwoFactorAuthCode(code=otp)
                            )
                            logger.info(Messages.Log.TOTP_2FA_SUCCESS)
                        except Exception as e2:
                            logger.error(Messages.Log.TOTP_2FA_FAIL.format(str(e2)))
                            return {"success": False, "error": Messages.Error.TOTP_2FA_FAIL.format(str(e2))}
                    
                    # Try again after 2FA
                    try:
                        self.current_user = auth_api.get_current_user()
                        self.authenticated = True
                        
                        logger.info(Messages.Log.AUTH_2FA_SUCCESS.format(self.current_user.display_name))
                        return {
                            "success": True,
                            "user_id": self.current_user.id,
                            "display_name": self.current_user.display_name
                        }
                    except ApiException as e2:
                        logger.error(Messages.Log.ERROR_AFTER_2FA.format(str(e2)))
                        return {"success": False, "error": Messages.Error.AUTH_FAIL_AFTER_2FA.format(str(e2))}
                else:
                    logger.error(Messages.Log.AUTH_ERROR.format(e.reason))
                    return {"success": False, "error": Messages.Error.AUTH_FAIL.format(e.reason)}
                    
            except ApiException as e:
                logger.error(Messages.Log.AUTH_API_ERROR.format(str(e)))
                return {"success": False, "error": Messages.Error.API_ERROR.format(str(e))}
                
        except Exception as e:
            logger.error(Messages.Log.AUTH_UNEXPECTED_ERROR.format(str(e)))
            return {"success": False, "error": Messages.Error.UNEXPECTED_ERROR.format(str(e))}
    
    async def authenticate(self):
        """Public method to authenticate or re-authenticate"""
        return await self._authenticate()
    
    async def post_announcement(self, title, content):
        """Post in the group with notification"""
        if not self.authenticated or not self.api_client:
            return {"success": False, "error": Messages.Error.NOT_AUTHENTICATED}
        
        try:
            # Create groups API instance
            groups_api = GroupsApi(self.api_client)
            
            # Create a post with notification
            logger.info(Messages.Log.POST_GROUP.format(self.group_id))
            group_post = groups_api.add_group_post(
                group_id=self.group_id,
                create_group_post_request={
                    "title": title,
                    "text": content,
                    "sendNotification": True
                }
            )
            
            return {
                "success": True,
                "group_post": group_post
            }
        except UnauthorizedException as e:
            logger.error(Messages.Log.POST_AUTH_ERROR.format(e))
            # Add to failed posts for retry
            self.failed_posts.append({
                "title": title,
                "content": content
            })
            return {"success": False, "error": Messages.Error.AUTH_FAIL_RETRY}
        except Exception as e:
            logger.error(Messages.Log.POST_ERROR.format(e))
            return {"success": False, "error": str(e)}
    
    async def create_group_calendar_event(self, title, content, start_at, end_at):
        """Create a group calendar event"""
        if not self.authenticated or not self.api_client:
            return {"success": False, "error": Messages.Error.NOT_AUTHENTICATED}

        try:
            from vrchatapi.api.calendar_api import CalendarApi
            from vrchatapi.models.calendar_event_access import CalendarEventAccess
            from vrchatapi.models.calendar_event_category import CalendarEventCategory

            calendar_api = CalendarApi(self.api_client)

            # Ensure start_at and end_at are datetime objects
            if isinstance(start_at, (int, float)):
                start_at = datetime.fromtimestamp(start_at, tz=pytz.utc)
            if isinstance(end_at, (int, float)):
                end_at = datetime.fromtimestamp(end_at, tz=pytz.utc)
            
            start_at = start_at.strftime('%Y-%m-%dT%H:%M:%SZ')
            end_at = end_at.strftime('%Y-%m-%dT%H:%M:%SZ')

            logger.info(f"Creating calendar event: {title} ({start_at} - {end_at})")

            request = CreateCalendarEventRequest(
                access_type=CalendarEventAccess.PUBLIC,
                category=CalendarEventCategory.OTHER,
                title=title,
                description=content,
                starts_at=start_at,
                ends_at=end_at,
                featured=False,
                image_id=None,
                is_draft=False,
                send_creation_notification=False,
            )

            event = calendar_api.create_group_calendar_event(
                group_id=self.group_id,
                create_calendar_event_request=request
            )

            return {
                "success": True,
                "event": event,
                "event_id": event.id
            }

        except Exception as e:
            logger.error(f"Error creating calendar event: {e}")
            return {"success": False, "error": str(e)}

    async def delete_group_calendar_event(self, calendar_event_id):
        """Delete a group calendar event"""
        if not self.authenticated or not self.api_client:
            return {"success": False, "error": Messages.Error.NOT_AUTHENTICATED}

        try:
            from vrchatapi.api.calendar_api import CalendarApi
            calendar_api = CalendarApi(self.api_client)

            logger.info(f"Deleting calendar event: {calendar_event_id}")

            calendar_api.delete_group_calendar_event(
                group_id=self.group_id,
                calendar_id=calendar_event_id
            )

            return {"success": True}

        except Exception as e:
            logger.error(f"Error deleting calendar event: {e}")
            return {"success": False, "error": str(e)}

    async def retry_failed_posts(self):
        """Retry all failed posts"""
        if not self.failed_posts:
            return []
            
        results = []
        for post in self.failed_posts:
            result = await self.post_announcement(post["title"], post["content"])
            results.append(result)
            
        # Clear failed posts after retry
        self.failed_posts = []
        return results
    
    async def delete_post(self, notification_id):
        """Delete a post"""
        if not self.authenticated or not self.api_client:
            return {"success": False, "error": Messages.Error.NOT_AUTHENTICATED}
        
        try:
            # Create groups API instance
            groups_api = GroupsApi(self.api_client) 
            
            # Delete the post
            groups_api.delete_group_post(
                group_id=self.group_id,
                notification_id=notification_id
            )
            
            return {
                "success": True,
                "message": "Post deleted successfully"
            }
        except Exception as e:  
            logger.error(Messages.Log.DELETE_POST_ERROR.format(e))
            return {"success": False, "error": str(e)}
    
    def close(self):
        """Close the API client"""
        if self.api_client:
            self.api_client.close()
            self.api_client = None
            self.authenticated = False
            self.current_user = None
