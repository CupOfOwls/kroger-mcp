"""
Tool errors for the Kroger MCP server

A tool that fails returns an MCP tool result with isError set, so the calling
model can read what went wrong and correct its next call. The result carries
the error twice:

- as text: the error message and the next step to take, for clients that show
  the model only text content
- as structured content: {"error": {"type", "message", ..., "next_step"}},
  with every detail kroger-api has (HTTP status, Kroger's error code and
  message, request, correlation id, response body)

Tools raise exceptions and do not build error results themselves:

- kroger-api raises KrogerAPIError subclasses for bad parameters and API errors
- tools raise KrogerToolError for problems the MCP server finds itself, such
  as a missing preferred location or an expired sign-in
- FastMCP raises ValidationError when the arguments do not match the tool's
  parameter types and constraints

The translate_errors decorator turns KrogerAPIError into KrogerToolError, and
ToolErrorMiddleware turns all three into the error result.
"""

import functools
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

import mcp.types
from fastmcp.exceptions import ToolError, ValidationError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools import ToolResult
from pydantic import ValidationError as PydanticValidationError

from kroger_api.errors import (
    TOKEN_ENDPOINT,
    APIConnectionError,
    APIStatusError,
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    InternalServerError,
    InvalidParameterError,
    InvalidResponseError,
    KrogerAPIError,
    NotAuthenticatedError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
)

ISSUES_URL = "https://github.com/CupOfOwls/kroger-mcp/issues"

SIGN_IN_STEP = (
    "Sign the user in: call start_authentication, have the user open the URL and approve access, "
    "then call complete_authentication with the URL the browser was redirected to."
)

RESTART_STEP = "then restart the MCP server. Retrying the tool will not help until then."

# The cart add is the only request this server sends that changes data, so it
# is the only one whose outcome can be unknown (error.outcome_unknown).
UNKNOWN_CART_OUTCOME_STEP = (
    "Do not call the tool again yet: Kroger may have added the items anyway. Ask the user to check "
    "their cart in the Kroger app or website, then add only the items that are missing. The local "
    "cart tracking was not updated."
)

# Longest input value repeated back in an invalid-arguments error
_MAX_INPUT_CHARS = 200


class KrogerToolError(ToolError):
    """A tool failed for a reason the calling model should see

    Attributes:
        error_type: Short, stable, machine-readable category, for example
            "authentication_required" or, for API errors, the kroger-api
            error type such as "not_found"
        message: What went wrong
        next_step: What the caller can do about it, if anything
        details: Additional JSON-safe data, such as the HTTP status of an API error
    """

    def __init__(self, error_type: str, message: str, *, next_step: Optional[str] = None,
                 details: Optional[Dict[str, Any]] = None):
        # These are expected failures, so they are logged without a traceback
        super().__init__(message, log_level=logging.WARNING)
        self.error_type = error_type
        self.message = message
        self.next_step = next_step
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.error_type, "message": self.message, **self.details, "next_step": self.next_step}

    @classmethod
    def from_api_error(cls, error: KrogerAPIError) -> "KrogerToolError":
        """Wrap a kroger-api exception, keeping all of its details"""
        details = error.to_dict()
        error_type = details.pop("type")
        message = details.pop("message")
        return cls(error_type, message, next_step=next_step_for(error), details=details)


def translate_errors(fn: Callable) -> Callable:
    """Decorate a tool so that kroger-api exceptions become KrogerToolError

    Without it the middleware still returns the same error result, but
    FastMCP first logs each kroger-api exception as an unexpected failure,
    with a full traceback. The wrapper is sync for a sync tool, so FastMCP
    still runs the tool in a worker thread.
    """

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except KrogerAPIError as e:
                raise KrogerToolError.from_api_error(e) from e

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except KrogerAPIError as e:
            raise KrogerToolError.from_api_error(e) from e

    return wrapper


def next_step_for(error: KrogerAPIError) -> Optional[str]:
    """What the calling model can do about a kroger-api error, naming this server's tools"""
    if error.outcome_unknown:
        return UNKNOWN_CART_OUTCOME_STEP
    if isinstance(error, InvalidParameterError):
        return f"Correct {error.param} and call the tool again."
    if isinstance(error, ConfigurationError):
        return f"Set the missing value in the env block of this MCP server's configuration, {RESTART_STEP}"
    if isinstance(error, NotAuthenticatedError):
        return SIGN_IN_STEP
    if isinstance(error, APIConnectionError):
        # Also covers APITimeoutError
        return "Retry once. If it fails again, the Kroger API or this machine's network connection is down."
    if isinstance(error, InvalidResponseError):
        return f"Retry once. If it happens again, report it at {ISSUES_URL} with the correlation id."
    if isinstance(error, APIStatusError):
        return _next_step_for_status(error)
    return None


def _next_step_for_status(error: APIStatusError) -> Optional[str]:
    path = urlsplit(error.url).path
    reason = (error.kroger_message or "").lower()

    if path == TOKEN_ENDPOINT:
        if isinstance(error, AuthenticationError):
            return f"Correct KROGER_CLIENT_ID and KROGER_CLIENT_SECRET in this MCP server's configuration, {RESTART_STEP}"
        if error.kroger_code == "invalid_scope":
            return (
                "Enable the Products, Locations, and Cart APIs for this app in the Kroger Developer Portal, "
                "then sign in again."
            )
        if "refresh_token" in reason:
            return "The saved sign-in can no longer be renewed. " + SIGN_IN_STEP
        if "code" in reason:
            return (
                "Call start_authentication again and use the new URL. Each authorization code works once "
                "and expires after a few minutes."
            )
        return None

    user_endpoint = path.startswith(("/v1/cart", "/v1/identity"))
    if isinstance(error, BadRequestError):
        return "Correct the parameter that the Kroger message names and call the tool again."
    if isinstance(error, AuthenticationError):
        if user_endpoint:
            return SIGN_IN_STEP
        return (
            "Retry once. If it fails again, check KROGER_CLIENT_ID and KROGER_CLIENT_SECRET in this "
            "MCP server's configuration."
        )
    if isinstance(error, PermissionDeniedError):
        if path.startswith("/v1/identity"):
            return (
                "The profile needs a sign-in that grants the profile.compact scope. Sign-ins made before "
                "kroger-mcp 0.4.0 did not request it: call start_authentication and have the user sign in "
                "again. If the error remains, check that the Identity API is enabled for this app in the "
                "Kroger Developer Portal. The cart tools do not need the profile."
            )
        if user_endpoint:
            return SIGN_IN_STEP
        return "Check that the Products and Locations APIs are enabled for this app in the Kroger Developer Portal."
    if isinstance(error, NotFoundError):
        if path.startswith("/v1/locations"):
            return "Find a valid location_id with search_locations."
        if path.startswith("/v1/products"):
            return "Find the product with search_products and use its product_id or upc."
        if path.startswith("/v1/chains"):
            return "Get the valid chain names with list_chains."
        if path.startswith("/v1/departments"):
            return "Get the valid department IDs with list_departments."
        return None
    if isinstance(error, RateLimitError):
        return (
            "Do not retry now. Kroger's rate limits are daily, so tell the user the limit is used up "
            "and try again later."
        )
    if isinstance(error, InternalServerError):
        return "Retry once. If it fails again, the Kroger API is having problems; try again later."
    return None


def _param_name(loc: tuple) -> str:
    """('items', 0, 'quantity') -> 'items[0].quantity'"""
    name = ""
    for part in loc:
        if isinstance(part, int):
            name += f"[{part}]"
        else:
            name += f".{part}" if name else str(part)
    return name or "(arguments)"


def _short_input(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    text = value if isinstance(value, str) else repr(value)
    return text if len(text) <= _MAX_INPUT_CHARS else text[:_MAX_INPUT_CHARS] + "..."


def _invalid_arguments(tool: str, error: PydanticValidationError) -> Dict[str, Any]:
    problems: List[Dict[str, Any]] = []
    lines = [f"Invalid arguments for {tool}:"]
    for item in error.errors(include_url=False):
        param = _param_name(item.get("loc", ()))
        problem = {"param": param, "problem": item.get("msg"), "error_code": item.get("type")}
        line = f"  - {param}: {item.get('msg')}"
        # For a missing argument, pydantic's input is the whole argument dict
        if not str(item.get("type")).startswith("missing"):
            problem["input"] = _short_input(item.get("input"))
            line += f" (got {problem['input']!r})"
        problems.append(problem)
        lines.append(line)
    lines.append("The tool did not run, so no request was sent.")
    return {
        "type": "invalid_arguments",
        "message": "\n".join(lines),
        "errors": problems,
        "next_step": "Correct the arguments listed and call the tool again. The tool's input schema lists the valid values.",
    }


def describe_error(tool: str, error: Exception) -> Optional[Dict[str, Any]]:
    """The structured error for an exception raised by a tool call, or None to let it propagate"""
    if isinstance(error, KrogerToolError):
        return error.to_dict()
    if isinstance(error, ValidationError) and isinstance(error.__cause__, PydanticValidationError):
        return _invalid_arguments(tool, error.__cause__)
    if isinstance(error, ToolError):
        cause = error.__cause__
        # A tool without @translate_errors: FastMCP wrapped the exception in a plain ToolError
        if isinstance(cause, KrogerAPIError):
            return KrogerToolError.from_api_error(cause).to_dict()
        if cause is not None:
            return {
                "type": "internal_error",
                "message": str(error),
                "exception_type": type(cause).__name__,
                "next_step": f"This is probably a bug in kroger-mcp. Report it at {ISSUES_URL} with this message.",
            }
        return {"type": "tool_error", "message": str(error), "next_step": None}
    return None


def error_result(tool: str, error: Dict[str, Any]) -> ToolResult:
    text = error["message"]
    if error.get("next_step"):
        text += f"\nNext step: {error['next_step']}"
    return ToolResult(
        content=[mcp.types.TextContent(type="text", text=text)],
        structured_content={"error": {**error, "tool": tool}},
        is_error=True,
    )


class ToolErrorMiddleware(Middleware):
    """Return tool failures as isError results with structured details

    FastMCP would otherwise return only the exception text, prefixed with
    "Error calling tool", and drop the details of kroger-api errors.
    """

    async def on_call_tool(self, context: MiddlewareContext[mcp.types.CallToolRequestParams], call_next):
        try:
            return await call_next(context)
        except Exception as e:
            error = describe_error(context.message.name, e)
            if error is None:
                raise
            return error_result(context.message.name, error)
