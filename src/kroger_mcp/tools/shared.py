"""
Shared utilities and client management for Kroger MCP server
"""

import json
import logging
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from typing import Any, Generator, Optional

import anyio.from_thread
from fastmcp import Context

from kroger_api import KrogerClient
from kroger_api.errors import BadRequestError, NotAuthenticatedError
from kroger_api.kroger_api import KrogerAPI
from kroger_api.token_storage import USER_TOKEN_FILE, clear_token, load_token, get_token_file_path
from kroger_api.utils.locking import file_lock

from ..errors import KrogerToolError, SIGN_IN_STEP

logger = logging.getLogger(__name__)

# The cached clients. FastMCP runs the tools in worker threads, so each cache
# has a lock: one thread at a time checks it and, if needed, replaces it.
_authenticated_client: Optional[KrogerAPI] = None
_client_credentials_client: Optional[KrogerAPI] = None
_authenticated_client_lock = threading.Lock()
_client_credentials_client_lock = threading.Lock()

# JSON files for configuration storage
PREFERENCES_FILE = "kroger_preferences.json"

# Scope of the token used for public data (products and locations)
CLIENT_CREDENTIALS_SCOPE = "product.compact"

DEFAULT_ZIP_CODE = "10001"


def log_to_client(ctx: Optional[Context], message: str, level: str = "info") -> None:
    """Send a log message to the MCP client from a tool

    The tools run in worker threads, and the Context methods are async, so
    the message is sent on the event loop. Sending is best effort: a message
    that cannot be sent never fails the tool.

    Args:
        ctx: The tool's Context, or None
        message: The message
        level: The Context method to send it with: "info" or "warning"
    """
    if ctx is None:
        return
    try:
        anyio.from_thread.run(getattr(ctx, level), message)
    except Exception as e:
        logger.debug("Could not send a log message to the client: %s", e)


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

    with _client_credentials_client_lock:
        if _client_credentials_client is None:
            _client_credentials_client = KrogerAPI()

        client = _client_credentials_client
        token_info = client.client.token_info
        if not token_info or KrogerClient.is_token_expired(token_info):
            client.authorization.get_token_with_client_credentials(CLIENT_CREDENTIALS_SCOPE)
        return client


def get_authenticated_client() -> KrogerAPI:
    """Get the client for the user's cart and profile

    The client holds the user token saved by complete_authentication, renewed
    first if it has expired. kroger-api renews it with the token file locked
    (AuthorizationAPI.load_saved_token): another server process that shares
    the file (Claude Desktop and Claude Code, for example) may have renewed
    the token already, and its token is then used instead of sending a
    refresh token that was already used.

    Raises:
        KrogerToolError: authentication_required, if there is no saved sign-in
            or it has expired and cannot be renewed
        ConfigurationError: If KROGER_CLIENT_ID or KROGER_CLIENT_SECRET is missing
        KrogerAPIError: If renewing the sign-in fails for another reason, such
            as a network error
    """
    global _authenticated_client

    with _authenticated_client_lock:
        client = _authenticated_client
        if client is not None and not KrogerClient.is_token_expired(client.client.token_info):
            return client
        _authenticated_client = None

        saved = load_token(USER_TOKEN_FILE)
        if not isinstance(saved, dict) or not saved.get("access_token"):
            raise _authentication_required("The user is not signed in to Kroger, and this tool needs their permission.")
        client = KrogerAPI()
        try:
            client.authorization.load_saved_token(USER_TOKEN_FILE)
        except NotAuthenticatedError as e:
            raise _authentication_required(
                f"The user's Kroger sign-in has expired and cannot be renewed: {e.message}"
            ) from e
        except BadRequestError as e:
            raise _authentication_required(
                f"The user's Kroger sign-in has expired and could not be renewed: "
                f"{e.kroger_message or e.message.splitlines()[0]}",
                details={"kroger_code": e.kroger_code, "correlation_id": e.correlation_id},
            ) from e

        _authenticated_client = client
        return client


def _authentication_required(message: str, details: Optional[dict] = None) -> KrogerToolError:
    return KrogerToolError("authentication_required", message, next_step=SIGN_IN_STEP, details=details)


def invalidate_authenticated_client():
    """Forget the cached user client, so the next cart call reloads the saved token"""
    global _authenticated_client
    with _authenticated_client_lock:
        _authenticated_client = None


def sign_out() -> None:
    """Delete the saved user token and forget the cached user client

    The cache lock is held for both steps. Otherwise a concurrent tool call
    could load the token file between them, cache the old sign-in, and keep
    using it until it expires.

    Raises:
        OSError: If the token file cannot be deleted
    """
    global _authenticated_client
    with _authenticated_client_lock:
        _authenticated_client = None
        clear_token(USER_TOKEN_FILE)


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


@contextmanager
def state_file_lock(filename: str) -> Generator[None, None, None]:
    """Hold the lock of a state file while the block reads, changes, and saves it

    Tools run in worker threads, and several server processes can share the
    state files, so a change made without the lock could be lost to a
    concurrent one. See kroger_api.utils.locking.file_lock.
    """
    with file_lock(resolve_data_file(filename)):
        yield


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


def invalid_state_file(filename: str, problem: str) -> KrogerToolError:
    """The local_state_error for a state file whose content has the wrong shape"""
    path = resolve_data_file(filename)
    return _state_error(f"The local state file {path} is not valid: {problem}.", path)


def save_state_file(filename: str, data: Any) -> None:
    """Write a JSON state file

    The data goes to a temporary file that then replaces the old one, so a
    failed write never leaves a half-written file behind. The temporary file
    has a unique name, so two server processes never write to the same one.

    Raises:
        KrogerToolError: local_state_error, if the file cannot be written
    """
    path = resolve_data_file(filename)
    temp_path = None
    try:
        fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(path), prefix=".tmp-", suffix=".json")
        with os.fdopen(fd, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(temp_path, path)
    except OSError as e:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
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
    with state_file_lock(PREFERENCES_FILE):
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


def response_data(response: Optional[dict], expected: type, api: str, description: str) -> Any:
    """The data member of a Kroger API response

    Args:
        response: The parsed response body
        expected: The type the data must have, dict or list
        api: The API's name for the error message, for example "Locations"
        description: What the data is, for example "data for location 01400513"

    Raises:
        KrogerToolError: unexpected_response, if the data is missing or has the wrong type
    """
    data = (response or {}).get("data")
    if not isinstance(data, expected):
        raise KrogerToolError(
            "unexpected_response",
            f"The Kroger {api} API answered without the {description} it documents.",
            details={"response_body": response},
        )
    return data


def format_currency(value: Optional[float]) -> str:
    """Format a value as currency"""
    if value is None:
        return "N/A"
    return f"${value:.2f}"


def get_configured_zip_code() -> Optional[str]:
    """The KROGER_USER_ZIP_CODE setting, or None if it is not set"""
    return os.getenv("KROGER_USER_ZIP_CODE") or None
