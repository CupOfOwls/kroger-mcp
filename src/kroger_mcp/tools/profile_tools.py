"""
User profile and authentication tools for Kroger MCP server
"""

from typing import Dict, Any
from fastmcp import Context

from kroger_api.token_storage import clear_token

from ..errors import KrogerToolError, SIGN_IN_STEP, translate_errors
from .shared import USER_TOKEN_FILE, get_authenticated_client, invalidate_authenticated_client


def register_tools(mcp):
    """Register profile-related tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def get_user_profile(ctx: Context = None) -> Dict[str, Any]:
        """
        Get the authenticated user's Kroger profile information.

        The Identity API needs a sign-in that grants the profile.compact scope.
        
        Returns:
            Dictionary containing user profile data
        """
        if ctx:
            await ctx.info("Getting user profile information")
        
        client = get_authenticated_client()
        profile = client.identity.get_profile()
        
        if not profile or not isinstance(profile.get("data"), dict):
            raise KrogerToolError(
                "unexpected_response",
                "The Kroger Identity API answered without the profile data it documents.",
                details={"response_body": profile},
            )
                
        profile_id = profile["data"].get("id", "N/A")
        
        if ctx:
            await ctx.info(f"Retrieved profile for user ID: {profile_id}")
        
        return {
            "success": True,
            "profile_id": profile_id,
            "message": "User profile retrieved successfully",
            "note": "The Kroger Identity API only provides the profile ID for privacy reasons."
        }

    @mcp.tool()
    @translate_errors
    async def test_authentication(ctx: Context = None) -> Dict[str, Any]:
        """
        Test if the current authentication token is valid.

        An expired token is refreshed if possible. A user who is not signed in
        is a normal result (token_valid false), not an error.
        
        Returns:
            Dictionary indicating authentication status
        """
        if ctx:
            await ctx.info("Testing authentication token validity")
        
        try:
            client = get_authenticated_client()
        except KrogerToolError as e:
            if e.error_type != "authentication_required":
                raise
            return {
                "success": True,
                "token_valid": False,
                "has_refresh_token": False,
                "can_auto_refresh": False,
                "message": f"{e.message} {SIGN_IN_STEP}"
            }
            
        result = {
            "success": True,
            "token_valid": True,
            "message": "Authentication token is valid"
        }
        
        # Check for refresh token availability
        has_refresh_token = "refresh_token" in client.client.token_info
        result["has_refresh_token"] = has_refresh_token
        result["can_auto_refresh"] = has_refresh_token
        
        if has_refresh_token:
            result["message"] += ". Token can be automatically refreshed when it expires."
        else:
            result["message"] += ". No refresh token available - will need to re-authenticate when token expires."
        
        return result

    @mcp.tool()
    @translate_errors
    async def get_authentication_info(ctx: Context = None) -> Dict[str, Any]:
        """
        Get information about the current authentication state and token.

        A user who is not signed in is a normal result (authenticated false),
        not an error.
        
        Returns:
            Dictionary containing authentication information
        """
        if ctx:
            await ctx.info("Getting authentication information")
        
        try:
            client = get_authenticated_client()
        except KrogerToolError as e:
            if e.error_type != "authentication_required":
                raise
            return {
                "success": True,
                "authenticated": False,
                "message": f"{e.message} {SIGN_IN_STEP}"
            }
            
        result = {
            "success": True,
            "authenticated": True,
            "message": "User is authenticated"
        }
        
        token_info = client.client.token_info
        result.update({
            "token_type": token_info.get("token_type", "Unknown"),
            "has_refresh_token": "refresh_token" in token_info,
            "expires_in": token_info.get("expires_in"),
            "scope": token_info.get("scope", "Unknown")
        })
        
        # Don't expose the actual tokens for security
        result["access_token_preview"] = f"{token_info.get('access_token', '')[:10]}..." if token_info.get('access_token') else "N/A"
        
        if "refresh_token" in token_info:
            result["refresh_token_preview"] = f"{token_info['refresh_token'][:10]}..."
        
        # Get token file information if available
        if client.client.token_file:
            result["token_file"] = client.client.token_file
        
        return result

    @mcp.tool()
    @translate_errors
    async def force_reauthenticate(ctx: Context = None) -> Dict[str, Any]:
        """
        Force re-authentication by clearing the current authentication token.
        Use this if you're having authentication issues or need to log in as a different user.

        This deletes the saved user token. The local cart tracking and order
        history are kept.
        
        Returns:
            Dictionary indicating the re-authentication was initiated
        """
        if ctx:
            await ctx.info("Forcing re-authentication by clearing current token")
        
        invalidate_authenticated_client()
        try:
            clear_token(USER_TOKEN_FILE)
        except OSError as e:
            raise KrogerToolError(
                "local_state_error",
                f"Could not delete the saved user token: {e}",
                next_step="Delete the token file by hand, or check the permissions of its directory.",
            ) from e
        
        if ctx:
            await ctx.info("Authentication token cleared")
        
        return {
            "success": True,
            "message": "The saved Kroger sign-in was deleted.",
            "next_step": SIGN_IN_STEP
        }
