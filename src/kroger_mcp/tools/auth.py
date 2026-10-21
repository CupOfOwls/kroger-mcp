"""
Authentication tools module for Kroger MCP server

This module provides OAuth authentication tools designed specifically for MCP context,
where the browser-based authentication flow needs to be handled through user interaction
rather than automated browser opening.
"""
import os
import secrets
from typing import Dict, Any
from fastmcp import Context
from dotenv import load_dotenv
from urllib.parse import urlparse, parse_qs

# Import the PKCE utilities from kroger-api
from kroger_api.utils import generate_pkce_parameters
from kroger_api import KrogerAPI

from ..errors import KrogerToolError, translate_errors
from .shared import invalidate_authenticated_client

# Load environment variables
load_dotenv()

DEFAULT_REDIRECT_URI = "http://localhost:8000/callback"

# Scopes needed for Kroger API (cart.basic:write is needed for cart operations)
USER_SCOPES = "product.compact cart.basic:write"

RESTART_SIGN_IN_STEP = "Call start_authentication again and have the user approve access with the new URL."

# Store PKCE parameters between steps
_pkce_params = None
_auth_state = None


def _new_client() -> KrogerAPI:
    return KrogerAPI(redirect_uri=os.environ.get("KROGER_REDIRECT_URI") or DEFAULT_REDIRECT_URI)


def register_auth_tools(mcp):
    """Register authentication-specific tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def start_authentication(ctx: Context = None) -> Dict[str, Any]:
        """
        Start the OAuth authentication flow with Kroger.
        
        This tool returns a URL that the user needs to open in their browser
        to authenticate with Kroger. After authorization, the user will be
        redirected to a callback URL that they need to copy and paste back.
        
        Returns:
            Dictionary with authorization URL and instructions
        """
        global _pkce_params, _auth_state
        
        # Raises ConfigurationError if the client ID or secret is missing
        kroger = _new_client()
        
        # Generate PKCE parameters
        _pkce_params = generate_pkce_parameters()
        
        # Random state for CSRF protection. It must not be derived from the
        # code verifier, which has to stay secret.
        _auth_state = secrets.token_urlsafe(16)
        
        # Get the authorization URL with PKCE
        auth_url = kroger.authorization.get_authorization_url(
            scope=USER_SCOPES,
            state=_auth_state,
            code_challenge=_pkce_params["code_challenge"],
            code_challenge_method=_pkce_params["code_challenge_method"]
        )
        
        if ctx:
            await ctx.info(f"Generated auth URL with PKCE: {auth_url}")
        
        return {
            "auth_url": auth_url,
            "instructions": (
                "1. Click this link to authorize: [🔗 Authorize Kroger Access]({auth_url})\n"
                "   - Please present the authorization URL as a clickable markdown link\n"
                "2. Log in to your Kroger account and authorize the application\n"
                "3. After authorization, you'll be redirected to a callback URL\n"
                "4. Copy the FULL redirect URL from your browser's address bar\n"
                "5. Use the complete_authentication tool with that URL to complete the process"
            ).format(auth_url=auth_url)
        }
    
    @mcp.tool()
    @translate_errors
    async def complete_authentication(redirect_url: str, ctx: Context = None) -> Dict[str, Any]:
        """
        Complete the OAuth flow using the redirect URL from Kroger.
        
        After opening the auth URL in your browser and authorizing the app,
        you'll be redirected to a callback URL. Copy that entire URL and
        pass it to this tool to complete the authentication process.
        
        Args:
            redirect_url: The full URL from your browser after authorization
            
        Returns:
            Dictionary indicating authentication status
        """
        global _pkce_params, _auth_state
        
        if not _pkce_params or not _auth_state:
            raise KrogerToolError(
                "authentication_not_started",
                "There is no sign-in in progress. The server may have restarted since start_authentication was called.",
                next_step=RESTART_SIGN_IN_STEP,
            )
            
        query_params = parse_qs(urlparse(redirect_url).query)

        # Kroger reports a refused or failed authorization in the redirect
        # (RFC 6749 section 4.1.2.1), for example error=access_denied
        if "error" in query_params:
            error = query_params["error"][0]
            description = query_params.get("error_description", [None])[0]
            raise KrogerToolError(
                "authorization_failed",
                f"Kroger did not authorize the app: {error}" + (f" ({description})" if description else ""),
                next_step=RESTART_SIGN_IN_STEP,
                details={"oauth_error": error, "oauth_error_description": description},
            )
            
        if "code" not in query_params:
            raise KrogerToolError(
                "invalid_redirect_url",
                "The redirect URL has no code parameter. Pass the full URL from the browser's address bar "
                "after the user approves access, including everything after the '?'.",
                next_step="Ask the user for the complete redirect URL and call complete_authentication again.",
                details={"query_parameters": sorted(query_params)},
            )
                
        auth_code = query_params['code'][0]
        received_state = query_params.get('state', [None])[0]
        
        # Verify state parameter to prevent CSRF attacks
        if received_state != _auth_state:
            raise KrogerToolError(
                "state_mismatch",
                "The redirect URL's state parameter does not match the sign-in in progress. The URL may "
                "come from an earlier start_authentication call, or from a request this server did not make.",
                next_step="Use the redirect URL from the latest start_authentication link, or call start_authentication again.",
            )
            
        kroger = _new_client()
        
        # Exchange the authorization code for tokens with the code verifier.
        # A rejected code raises BadRequestError, with the reason from Kroger.
        if ctx:
            await ctx.info("Exchanging authorization code for tokens with code_verifier")
        token_info = kroger.authorization.get_token_with_authorization_code(
            auth_code,
            code_verifier=_pkce_params["code_verifier"]
        )
        
        # Clear PKCE parameters and state after successful exchange
        _pkce_params = None
        _auth_state = None
        # The cart tools must use the new token, not a cached client
        invalidate_authenticated_client()
        
        if ctx:
            await ctx.info("Authentication successful!")
        
        return {
            "success": True,
            "message": "Authentication successful! You can now use Kroger API tools that require authentication.",
            "token_info": {
                "expires_in": token_info.get("expires_in"),
                "token_type": token_info.get("token_type"),
                "scope": token_info.get("scope"),
                "has_refresh_token": "refresh_token" in token_info
            }
        }
