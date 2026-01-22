"""
User profile and authentication tools for Kroger MCP server
"""

from typing import Dict, Any
from fastmcp import Context

from .shared import get_authenticated_client, invalidate_authenticated_client


def register_tools(mcp):
    """Register profile-related tools with the FastMCP server"""
    
    @mcp.tool()
    async def get_user_profile(ctx: Context = None) -> Dict[str, Any]:
        """
        Get the authenticated user's Kroger profile information.
        
        Returns:
            Dictionary containing user profile data
        """
        if ctx:
            await ctx.info("Getting user profile information")
        
        try:
            client = get_authenticated_client()
            profile = client.identity.get_profile()
            
            if profile and "data" in profile:
                profile_id = profile["data"].get("id", "N/A")
                
                if ctx:
                    await ctx.info(f"Retrieved profile for user ID: {profile_id}")
                
                return {
                    "success": True,
                    "profile_id": profile_id,
                    "message": "User profile retrieved successfully",
                    "note": "The Kroger Identity API only provides the profile ID for privacy reasons."
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to retrieve user profile"
                }
                
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting user profile: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    @mcp.tool()
    async def test_authentication(ctx: Context = None) -> Dict[str, Any]:
        """
        Test if the current authentication token is valid.
        
        Returns:
            Dictionary indicating authentication status
        """
        if ctx:
            await ctx.info("Testing authentication token validity")
        
        try:
            client = get_authenticated_client()
            is_valid = client.test_current_token()
            
            if ctx:
                await ctx.info(f"Authentication test result: {'valid' if is_valid else 'invalid'}")
            
            result = {
                "success": True,
                "token_valid": is_valid,
                "message": f"Authentication token is {'valid' if is_valid else 'invalid'}"
            }
            
            # Check for refresh token availability
            if hasattr(client.client, 'token_info') and client.client.token_info:
                has_refresh_token = "refresh_token" in client.client.token_info
                result["has_refresh_token"] = has_refresh_token
                result["can_auto_refresh"] = has_refresh_token
                
                if has_refresh_token:
                    result["message"] += ". Token can be automatically refreshed when it expires."
                else:
                    result["message"] += ". No refresh token available - will need to re-authenticate when token expires."
            
            return result
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error testing authentication: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "token_valid": False
            }

    @mcp.tool()
    async def get_authentication_info(ctx: Context = None) -> Dict[str, Any]:
        """
        Get information about the current authentication state and token.
        
        Returns:
            Dictionary containing authentication information
        """
        if ctx:
            await ctx.info("Getting authentication information")
        
        try:
            client = get_authenticated_client()
            
            result = {
                "success": True,
                "authenticated": True,
                "message": "User is authenticated"
            }
            
            # Get token information if available
            if hasattr(client.client, 'token_info') and client.client.token_info:
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
            if hasattr(client.client, 'token_file') and client.client.token_file:
                result["token_file"] = client.client.token_file
            
            return result
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error getting authentication info: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "authenticated": False
            }

    @mcp.tool()
    async def force_reauthenticate(ctx: Context = None) -> Dict[str, Any]:
        """
        Force re-authentication by clearing the current authentication token.
        Use this if you're having authentication issues or need to log in as a different user.
        
        Returns:
            Dictionary indicating the re-authentication was initiated
        """
        if ctx:
            await ctx.info("Forcing re-authentication by clearing current token")
        
        try:
            # Clear the current authenticated client
            invalidate_authenticated_client()
            
            if ctx:
                await ctx.info("Authentication token cleared. Next cart operation will trigger re-authentication.")
            
            return {
                "success": True,
                "message": "Authentication token cleared. The next cart operation will open your browser for re-authentication.",
                "note": "You will need to log in again when you next use cart-related tools."
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Error clearing authentication: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }
