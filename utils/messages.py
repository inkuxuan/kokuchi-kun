class Messages:
    class Const:
        VRC_USER_AGENT = "VRChatAnnounceBotPython/1.0.0 mail@sayonara-natsu.com"

    class Log:
        # bot.py
        LOADING_ENV = "Loading environment from: {}"
        ENV_NOT_FOUND = "Environment file not found: {}, using default environment"
        BOT_SETUP_SUCCESS = "Bot setup completed successfully"
        BOT_SETUP_ERROR = "Error during bot setup: {}"
        BOT_READY = "Bot is ready! Logged in as {}"
        OTP_CHANNEL_NOT_FOUND = "Could not find channel for OTP request"
        DISCORD_TOKEN_NOT_FOUND = "Discord token not found in environment variables!"
        VRC_API_INIT_FAIL = "Failed to initialize VRChat API: {}"
        VRC_API_INIT_SUCCESS = "VRChat API initialized successfully"
        VRC_API_INIT_ERROR = "Error during VRChat API initialization: {}"
        CONFIG_LOAD_FAIL = "Failed to load config: {}"
        BOT_START_ERROR = "Error starting bot: {}"

        # cogs/announcement.py
        ANNOUNCEMENT_REQUEST_ERROR = "Error handling announcement request: {}"
        SCHEDULED_MSG_DELETE_ERROR = "Error deleting scheduled message: {}"
        APPROVED_ANNOUNCEMENT_ERROR = "Error processing approved announcement: {}"

        # cogs/admin.py
        VERSION_LOAD_FAIL = "Failed to load version from pyproject.toml: {}"
        ADMIN_CMD_ERROR = "Error in admin command: {}"

        # utils/ai_processor.py
        AI_PROCESSING = "Processing announcement with AI"
        AI_RAW_RESPONSE = "Raw AI response: {}"
        AI_PARSED_RESPONSE = "Parsed response: {}"
        AI_PROCESS_ERROR = "Error processing with AI: {}"

        # utils/scheduler.py
        SCHEDULING_JOB = "Scheduling announcement for {} with job ID {}"
        EXECUTING_JOB = "Executing scheduled job {}"
        JOB_AUTH_FAIL = "Failed to authenticate for job {}: {}"
        POST_SUCCESS = "Successfully posted announcement to VRChat, post ID: {}"
        POST_FAIL = "Failed to post announcement to VRChat: {}"
        JOB_EXEC_ERROR = "Error executing scheduled job {}: {}"
        JOB_CANCEL_ERROR = "Error cancelling job {}: {}"

        # utils/vrchat_api.py
        COOKIE_AUTH_ATTEMPT = "Attempting cookie authentication"
        NO_SESSION_FILE = "No saved session found"
        NO_AUTH_COOKIE = "No auth cookie found in saved session"
        COOKIE_AUTH_SUCCESS = "Successfully authenticated with saved cookie as {}"
        COOKIE_AUTH_FAIL_UNAUTH = "Cookie authentication failed - unauthorized: {}"
        COOKIE_AUTH_FAIL_API = "Cookie authentication failed - API error: {}"
        COOKIE_AUTH_FAIL = "Cookie authentication failed: {}"
        NO_AUTH_COOKIE_SAVE = "No auth cookie found to save"
        COOKIES_SAVED = "VRChat session cookies saved to {}"
        COOKIE_SAVE_FAIL = "Failed to save cookies: {}"
        AUTH_SUCCESS = "Authenticated as {}"
        EMAIL_2FA_SUCCESS = "Email 2FA verified successfully"
        EMAIL_2FA_FAIL = "Email 2FA failed: {}"
        TOTP_2FA_SUCCESS = "TOTP 2FA verified successfully"
        TOTP_2FA_FAIL = "TOTP 2FA failed: {}"
        AUTH_2FA_SUCCESS = "Authenticated with 2FA as {}"
        POST_GROUP = "Posting to group {}"
        POST_AUTH_ERROR = "Authentication error posting announcement: {}"
        POST_ERROR = "Error posting announcement: {}"
        DELETE_POST_ERROR = "Error deleting post: {}"
        AUTH_ERROR = "Authentication error: {}"
        AUTH_API_ERROR = "API error during authentication: {}"
        AUTH_UNEXPECTED_ERROR = "Unexpected error during authentication: {}"
        ERROR_AFTER_2FA = "Error after 2FA: {}"

    class Discord:
        # Shared
        OTP_REQUEST = "{role_mention} VRChatの認証に{otp_type}が必要です。認証コードを入力してください。"
        OTP_REQUEST_EDITED = "VRChatの認証に{otp_type}が必要です。認証コードを入力してください。"
        OTP_TIMEOUT = "{role_mention} OTPリクエストがタイムアウトしました。"

        # Announcement Cog
        ALREADY_BOOKED = "この告知は既に予約されています。"
        REQUEST_CONFIRMED = "告知リクエストを確認しました。管理者の承認を待っています。"
        ERROR_OCCURRED = "エラーが発生しました: {}"
        BOOKING_CANCELLED = "告知の予約がキャンセルされました。"
        PROCESSING = "処理中..."
        BOOKING_COMPLETED_TITLE = "告知が予約されました"
        FIELD_POST_TIME = "投稿日時"
        FIELD_TITLE = "タイトル"
        FIELD_CONTENT = "内容"
        FIELD_JOB_ID = "ジョブID"
        PROCESSING_ERROR = "告知の処理中にエラーが発生しました: {}"

        # Admin Cog
        NO_SCHEDULED_JOBS = "予約されている告知はありません。"
        SCHEDULED_JOBS_TITLE = "予約されている告知"
        JOB_CANCELLED = "ジョブID {} の告知をキャンセルしました。"
        JOB_NOT_FOUND = "ジョブID {} は見つかりませんでした。"
        CMD_LIST_TITLE = "コマンド一覧"
        CMD_LIST_DESC = "予約されている告知の一覧を表示"
        CMD_CANCEL_DESC = "指定されたジョブIDの告知をキャンセル"
        CMD_HELP_DESC = "このヘルプメッセージを表示"
        NO_PERMISSION = "このコマンドを実行する権限がありません。"
        CMD_EXEC_ERROR = "コマンドの実行中にエラーが発生しました。"

    class Error:
        # AI Processor
        AI_ERROR = "AI処理中にエラーが発生しました。{}"

        # VRChat API
        API_CLIENT_NOT_INIT = "API client not initialized"
        OTP_CALLBACK_NOT_SET = "OTP callback not set"
        NO_OTP_PROVIDED = "No OTP provided"
        EMAIL_2FA_FAIL = "Email 2FA failed: {}"
        TOTP_2FA_FAIL = "TOTP 2FA failed: {}"
        AUTH_FAIL_AFTER_2FA = "Authentication failed after 2FA: {}"
        AUTH_FAIL = "Authentication failed: {}"
        API_ERROR = "API error: {}"
        UNEXPECTED_ERROR = "Unexpected error: {}"
        NOT_AUTHENTICATED = "Not authenticated"
        AUTH_FAIL_RETRY = "Authentication failed, will retry after reauth"
