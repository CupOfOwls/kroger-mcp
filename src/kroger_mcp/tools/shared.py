"""
Shared utilities and client management for Kroger MCP server
"""

import os
import json
from typing import Optional
from dotenv import load_dotenv

from kroger_api.kroger_api import KrogerAPI
from kroger_api.utils.env import load_and_validate_env, get_zip_code
from kroger_api.token_storage import load_token

# Load environment variables
load_dotenv()

# Global state for clients and preferred location
_authenticated_client: Optional[KrogerAPI] = None
_client_credentials_client: Optional[KrogerAPI] = None

# JSON files for configuration storage
PREFERENCES_FILE = "kroger_preferences.json"


def get_client_credentials_client() -> KrogerAPI:
    """Get or create a client credentials authenticated client for public data"""
    global _client_credentials_client
    
    if _client_credentials_client is not None and _client_credentials_client.test_current_token():
        return _client_credentials_client
    
    _client_credentials_client = None
    
    try:
        load_and_validate_env(["KROGER_CLIENT_ID", "KROGER_CLIENT_SECRET"])
        _client_credentials_client = KrogerAPI()
        
        # Try to load existing token first
        token_file = ".kroger_token_client_product.compact.json"
        token_info = load_token(token_file)
        
        if token_info:
            # Test if the token is still valid
            _client_credentials_client.client.token_info = token_info
            if _client_credentials_client.test_current_token():
                # Token is valid, use it
                return _client_credentials_client
        
        # Token is invalid or not found, get a new one
        token_info = _client_credentials_client.authorization.get_token_with_client_credentials("product.compact")
        return _client_credentials_client
    except Exception as e:
        raise Exception(f"Failed to get client credentials: {str(e)}")


def get_authenticated_client() -> KrogerAPI:
    """Get or create a user-authenticated client for cart operations
    
    This function attempts to load an existing token or prompts for authentication.
    In an MCP context, the user needs to explicitly call start_authentication and
    complete_authentication tools to authenticate.
    
    Returns:
        KrogerAPI: Authenticated client
        
    Raises:
        Exception: If no valid token is available and authentication is required
    """
    global _authenticated_client
    
    if _authenticated_client is not None and _authenticated_client.test_current_token():
        # Client exists and token is still valid
        return _authenticated_client
    
    # Clear the reference if token is invalid
    _authenticated_client = None
    
    try:
        load_and_validate_env(["KROGER_CLIENT_ID", "KROGER_CLIENT_SECRET", "KROGER_REDIRECT_URI"])
        
        # Try to load existing user token first
        token_file = ".kroger_token_user.json"
        token_info = load_token(token_file)
        
        if token_info:
            # Create a new client with the loaded token
            _authenticated_client = KrogerAPI()
            _authenticated_client.client.token_info = token_info
            _authenticated_client.client.token_file = token_file
            
            if _authenticated_client.test_current_token():
                # Token is valid, use it
                return _authenticated_client
            
            # Token is invalid, try to refresh it
            if "refresh_token" in token_info:
                try:
                    _authenticated_client.authorization.refresh_token(token_info["refresh_token"])
                    # If refresh was successful, return the client
                    if _authenticated_client.test_current_token():
                        return _authenticated_client
                except Exception:
                    # Refresh failed, need to re-authenticate
                    _authenticated_client = None
        
        # No valid token available, need user-initiated authentication
        raise Exception(
            "Authentication required. Please use the start_authentication tool to begin the OAuth flow, "
            "then complete it with the complete_authentication tool."
        )
    except Exception as e:
        if "Authentication required" in str(e):
            # This is an expected error when authentication is needed
            raise
        else:
            # Other unexpected errors
            raise Exception(f"Authentication failed: {str(e)}")


def invalidate_authenticated_client():
    """Invalidate the authenticated client to force re-authentication"""
    global _authenticated_client
    _authenticated_client = None


def invalidate_client_credentials_client():
    """Invalidate the client credentials client to force re-authentication"""
    global _client_credentials_client
    _client_credentials_client = None


def _load_preferences() -> dict:
    """Load preferences from file"""
    try:
        if os.path.exists(PREFERENCES_FILE):
            with open(PREFERENCES_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Warning: Could not load preferences: {e}")
    return {"preferred_location_id": None}


def _save_preferences(preferences: dict) -> None:
    """Save preferences to file"""
    try:
        with open(PREFERENCES_FILE, 'w') as f:
            json.dump(preferences, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save preferences: {e}")


def get_preferred_location_id() -> Optional[str]:
    """Get the current preferred location ID from preferences file"""
    preferences = _load_preferences()
    return preferences.get("preferred_location_id")


def set_preferred_location_id(location_id: str) -> None:
    """Set the preferred location ID in preferences file"""
    preferences = _load_preferences()
    preferences["preferred_location_id"] = location_id
    _save_preferences(preferences)


def format_currency(value: Optional[float]) -> str:
    """Format a value as currency"""
    if value is None:
        return "N/A"
    return f"${value:.2f}"


def get_default_zip_code() -> str:
    """Get the default zip code from environment or fallback"""
    return get_zip_code(default="10001")
