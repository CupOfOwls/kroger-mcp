#!/usr/bin/env python3
"""
Shared utilities and configuration for Kroger MCP tools
"""

import os
import json
from typing import Optional, Dict, Any
from kroger_api import KrogerAPI
from kroger_api.auth import load_token

# Global variables for client instances
_client_credentials_client = None
_authenticated_client = None

# File paths
PREFERENCES_FILE = os.path.expanduser("~/.kroger_mcp_preferences.json")
TOKEN_FILE = ".kroger_token_user.json"

def load_and_validate_env(required_vars: list) -> None:
    """Load and validate required environment variables"""
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

def get_zip_code(default: str = "10001") -> str:
    """Get zip code from environment or use default"""
    return os.getenv("KROGER_USER_ZIP_CODE", default)

def get_client_credentials_client():
    """Get a client credentials authenticated client (for public data)"""
    global _client_credentials_client
    
    if _client_credentials_client is not None:
        return _client_credentials_client
    
    try:
        load_and_validate_env(["KROGER_CLIENT_ID", "KROGER_CLIENT_SECRET"])
        _client_credentials_client = KrogerAPI()
        _client_credentials_client.authorization.client_credentials()
        return _client_credentials_client
    except Exception as e:
        raise Exception(f"Failed to initialize client credentials client: {str(e)}")

def get_authenticated_client():
    """
    Get an authenticated client for user-specific operations.
    Raises an exception if authentication is required.
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
    """Load preferences from file with better error handling and file creation"""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)
        
        if os.path.exists(PREFERENCES_FILE):
            with open(PREFERENCES_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content:
                    return json.loads(content)
                else:
                    # File exists but is empty
                    return {"preferred_location_id": None}
        else:
            # File doesn't exist, create it with default preferences
            default_prefs = {"preferred_location_id": None}
            _save_preferences(default_prefs)
            return default_prefs
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load preferences from {PREFERENCES_FILE}: {e}")
        # Return default preferences and try to recreate the file
        default_prefs = {"preferred_location_id": None}
        try:
            _save_preferences(default_prefs)
        except Exception as save_error:
            print(f"Warning: Could not create default preferences file: {save_error}")
        return default_prefs
    except Exception as e:
        print(f"Warning: Unexpected error loading preferences: {e}")
        return {"preferred_location_id": None}

def _save_preferences(preferences: dict) -> None:
    """Save preferences to file with better error handling"""
    try:
        # Ensure the directory exists
        os.makedirs(os.path.dirname(PREFERENCES_FILE), exist_ok=True)
        
        # Write to a temporary file first, then rename for atomic operation
        temp_file = PREFERENCES_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(preferences, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk
        
        # Atomic rename
        if os.name == 'nt':  # Windows
            if os.path.exists(PREFERENCES_FILE):
                os.remove(PREFERENCES_FILE)
        os.rename(temp_file, PREFERENCES_FILE)
        
        print(f"Preferences saved successfully to {PREFERENCES_FILE}")
    except Exception as e:
        print(f"Error: Could not save preferences to {PREFERENCES_FILE}: {e}")
        # Clean up temp file if it exists
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
        raise

def get_preferred_location_id() -> Optional[str]:
    """Get the current preferred location ID from preferences file"""
    preferences = _load_preferences()
    location_id = preferences.get("preferred_location_id")
    print(f"Retrieved preferred location ID: {location_id}")
    return location_id

def set_preferred_location_id(location_id: str) -> None:
    """Set the preferred location ID in preferences file"""
    print(f"Setting preferred location ID to: {location_id}")
    preferences = _load_preferences()
    preferences["preferred_location_id"] = location_id
    _save_preferences(preferences)
    
    # Verify the save was successful
    saved_preferences = _load_preferences()
    saved_location_id = saved_preferences.get("preferred_location_id")
    if saved_location_id != location_id:
        raise Exception(f"Failed to save preferred location. Expected: {location_id}, Got: {saved_location_id}")
    print(f"Successfully saved preferred location ID: {location_id}")

def format_currency(value: Optional[float]) -> str:
    """Format a value as currency"""
    if value is None:
        return "N/A"
    return f"${value:.2f}"

def get_default_zip_code() -> str:
    """Get the default zip code from environment or fallback"""
    return get_zip_code(default="10001")
