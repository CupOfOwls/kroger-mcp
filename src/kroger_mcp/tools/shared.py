"""
Shared utilities and client management for Kroger MCP server
"""

import json
import os
import sys
from typing import Any, Optional

from dotenv import load_dotenv

from kroger_api import KrogerClient
from kroger_api.errors import BadRequestError
from kroger_api.kroger_api import KrogerAPI
from kroger_api.token_storage import load_token, get_token_file_path

from ..errors import KrogerToolError, SIGN_IN_STEP

# Load environment variables
load_dotenv()

# Global state for clients and preferred location
_authenticated_client: Optional[KrogerAPI] = None
_client_credentials_client: Optional[KrogerAPI] = None

# JSON files for configuration storage
PREFERENCES_FILE = "kroger_preferences.json"

# Token file that kroger-api saves user (authorization-code) tokens to
USER_TOKEN_FILE = ".kroger_token_user.json"

# Scope of the token used for public data (products and locations)
CLIENT_CREDENTIALS_SCOPE = "product.compact"

DEFAULT_ZIP_CODE = "10001"


def get_client_credentials_client() -> KrogerAPI:
    """Get the client for public data (products, locations, chains, departments)

    The client holds an unexpired client-credentials token. kroger-api reuses
    the saved token file while it is unexpired, and replaces a token the API
    rejects.

    Raises:
        ConfigurationError: If KROGER_CLIENT_ID or KROGER_CLIENT_SECRET is missing
        AuthenticationError: If Kroger rejects the client ID and secret
    """
    global _client_credentials_client

    if _client_credentials_client is None:
        _client_credentials_client = KrogerAPI()

    client = _client_credentials_client
    token_info = client.client.token_info
    if not token_info or KrogerClient.is_token_expired(token_info):
        client.authorization.get_token_with_client_credentials(CLIENT_CREDENTIALS_SCOPE)
    return client


def get_authenticated_client() -> KrogerAPI:
    """Get the client for the user's cart and profile

    The client holds the user token saved by complete_authentication, refreshed
    first if it has expired.

    Raises:
        KrogerToolError: authentication_required, if there is no saved sign-in
            or it has expired and cannot be renewed
        ConfigurationError: If KROGER_CLIENT_ID or KROGER_CLIENT_SECRET is missing
        KrogerAPIError: If renewing the sign-in fails for another reason, such
            as a network error
    """
    global _authenticated_client

    client = _authenticated_client
    if client is None:
        token_info = load_token(USER_TOKEN_FILE)
        if not token_info or not token_info.get("access_token"):
            raise KrogerToolError(
                "authentication_required",
                "The user is not signed in to Kroger, and this tool needs their permission.",
                next_step=SIGN_IN_STEP,
            )
        client = KrogerAPI()
        client.client.token_info = token_info
        client.client.token_file = USER_TOKEN_FILE

    token_info = client.client.token_info
    if KrogerClient.is_token_expired(token_info):
        _authenticated_client = None
        refresh_token = token_info.get("refresh_token")
        if not refresh_token:
            raise KrogerToolError(
                "authentication_required",
                "The user's Kroger sign-in has expired and has no refresh token to renew it with.",
                next_step=SIGN_IN_STEP,
            )
        try:
            client.authorization.refresh_token(refresh_token)
        except BadRequestError as e:
            raise KrogerToolError(
                "authentication_required",
                f"The user's Kroger sign-in has expired and could not be renewed: "
                f"{e.kroger_message or e.message.splitlines()[0]}",
                next_step=SIGN_IN_STEP,
                details={"kroger_code": e.kroger_code, "correlation_id": e.correlation_id},
            ) from e

    _authenticated_client = client
    return client


def invalidate_authenticated_client():
    """Forget the cached user client, so the next cart call reloads the saved token"""
    global _authenticated_client
    _authenticated_client = None


def invalidate_client_credentials_client():
    """Invalidate the client credentials client to force re-authentication"""
    global _client_credentials_client
    _client_credentials_client = None


def resolve_data_file(filename: str) -> str:
    """Resolve a state file to the shared per-user data directory.

    State files live alongside the OAuth tokens (see
    kroger_api.token_storage.get_token_file_path), NOT the current working
    directory: MCP hosts like Claude Desktop launch the server with a CWD
    that may be read-only and that varies between sessions, which made
    state silently fail to persist (issue #15). Any legacy copy found in
    the CWD is migrated once.
    """
    path = get_token_file_path(filename)
    if not os.path.exists(path) and os.path.exists(filename):
        try:
            with open(filename, 'r') as src, open(path, 'w') as dst:
                dst.write(src.read())
        except Exception as e:
            print(f"Warning: Could not migrate {filename} from CWD: {e}", file=sys.stderr)
    return path


def load_state_file(filename: str, default: Any) -> Any:
    """Read a JSON state file, or return default if the file does not exist

    Raises:
        KrogerToolError: local_state_error, if the file cannot be read, is not
            valid JSON, or holds a different JSON type than default
    """
    path = resolve_data_file(filename)
    if not os.path.exists(path):
        return default
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise _state_error(f"Could not read the local state file {path}: {e}", path) from e
    if not isinstance(data, type(default)):
        raise _state_error(
            f"The local state file {path} holds a JSON {type(data).__name__}, not a JSON {type(default).__name__}.",
            path,
        )
    return data


def save_state_file(filename: str, data: Any) -> None:
    """Write a JSON state file

    The data goes to a temporary file that then replaces the old one, so a
    failed write never leaves a half-written file behind.

    Raises:
        KrogerToolError: local_state_error, if the file cannot be written
    """
    path = resolve_data_file(filename)
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    except OSError as e:
        raise KrogerToolError(
            "local_state_error",
            f"Could not write the local state file {path}: {e}",
            next_step=(
                "Make the directory writable, or set KROGER_TOKEN_DIR to a writable directory in this "
                "MCP server's configuration and restart the server."
            ),
            details={"path": path},
        ) from e


def _state_error(message: str, path: str) -> KrogerToolError:
    return KrogerToolError(
        "local_state_error",
        message,
        next_step="Correct the file's JSON, or move the file aside to start again with empty state.",
        details={"path": path},
    )


def get_preferred_location_id() -> Optional[str]:
    """Get the current preferred location ID from preferences file"""
    return load_state_file(PREFERENCES_FILE, {}).get("preferred_location_id")


def set_preferred_location_id(location_id: str) -> None:
    """Set the preferred location ID in preferences file"""
    preferences = load_state_file(PREFERENCES_FILE, {})
    preferences["preferred_location_id"] = location_id
    save_state_file(PREFERENCES_FILE, preferences)


def resolve_location_id(location_id: Optional[str]) -> str:
    """The given location ID, else the preferred location

    Raises:
        KrogerToolError: location_required, if neither is set
    """
    if location_id:
        return location_id
    preferred = get_preferred_location_id()
    if preferred:
        return preferred
    raise KrogerToolError(
        "location_required",
        "No location_id was given and no preferred location is set.",
        next_step="Pass location_id, or find a store with search_locations and save it with set_preferred_location.",
    )


def format_currency(value: Optional[float]) -> str:
    """Format a value as currency"""
    if value is None:
        return "N/A"
    return f"${value:.2f}"


def get_configured_zip_code() -> Optional[str]:
    """The KROGER_USER_ZIP_CODE setting, or None if it is not set"""
    return os.getenv("KROGER_USER_ZIP_CODE") or None
