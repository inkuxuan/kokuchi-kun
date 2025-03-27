import os
import pytest
import logging
from dotenv import load_dotenv
from utils.vrchat_api import VRChatAPI

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

@pytest.fixture
def vrchat_config():
    """Load VRChat configuration from environment variables"""
    load_dotenv(".test.env")
    
    config = {
        'username': os.getenv('VRCHAT_TEST_USERNAME'),
        'password': os.getenv('VRCHAT_TEST_PASSWORD'),
        'group_id': os.getenv('VRCHAT_TEST_GROUP_ID'),
        # 'cookie_file': 'test_vrchat_session.json'  # Use a separate file for testing
    }
    
    # Check if all required credentials are available
    for key, value in config.items():
        if not value:
            pytest.skip(f"Missing required VRChat configuration: {key}")
    
    return config

def test_vrchat_post_announcement(vrchat_config):
    """Test posting an announcement to a VRChat group"""
    # Create API instance
    api = VRChatAPI(vrchat_config)
    
    try:
        # Initialize API (will use cookies if available, otherwise credentials)
        init_result = api.initialize()
        assert init_result["success"], f"Failed to initialize VRChat API: {init_result.get('error', 'Unknown error')}"
        
        # Log authentication method used
        auth_method = init_result.get("method", "unknown")
        logging.info(f"Authenticated using {auth_method} method")
        
        # Post a test announcement
        test_title = "Automated Test Announcement"
        test_content = "This is an automated test announcement. Please ignore."
        
        post_result = api.post_announcement(test_title, test_content)
        assert post_result["success"], f"Failed to post announcement: {post_result.get('error', 'Unknown error')}"
        
        logging.info(f"Successfully posted test announcement with ID: {post_result['group_post'].id}")
        
        # Delete the test post to clean up
        delete_result = api.delete_post(post_result['group_post'].id)
        assert delete_result["success"], f"Failed to delete test post: {delete_result.get('error', 'Unknown error')}"
        
        logging.info("Successfully deleted test announcement")
        
    finally:
        # Always close the API connection
        api.close()

if __name__ == "__main__":
    # Allow running directly as a script for easier debugging
    pytest.main(["-xvs", __file__])