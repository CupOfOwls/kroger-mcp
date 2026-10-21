import json
import time

import pytest
from fastmcp import Client

from kroger_api.token_storage import save_token
from kroger_mcp.server import create_server
from kroger_mcp.tools import auth, shared

BASE = "https://api.kroger.com"
TOKEN_URL = f"{BASE}/v1/connect/oauth2/token"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch, requests_mock):
    """Keep every test away from real tokens, state files, settings, and network

    requests_mock is active for every test, so an unmocked request fails
    instead of reaching the Kroger API.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("KROGER_TOKEN_DIR", str(data_dir))
    monkeypatch.setenv("KROGER_CLIENT_ID", "id")
    monkeypatch.setenv("KROGER_CLIENT_SECRET", "secret")
    monkeypatch.delenv("KROGER_REDIRECT_URI", raising=False)
    monkeypatch.delenv("KROGER_USER_ZIP_CODE", raising=False)
    # State files found in the working directory are migrated, so use an empty one
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(shared, "_authenticated_client", None)
    monkeypatch.setattr(shared, "_client_credentials_client", None)
    monkeypatch.setattr(auth, "_pkce_params", None)
    monkeypatch.setattr(auth, "_auth_state", None)
    return data_dir


@pytest.fixture
async def mcp():
    async with Client(create_server()) as client:
        yield client


@pytest.fixture
def app_token(requests_mock):
    """The token endpoint issues client-credentials tokens"""
    return requests_mock.post(TOKEN_URL, json={"access_token": "app", "expires_in": 1800, "token_type": "bearer"})


def save_user_token(**overrides):
    token_info = {
        "access_token": "user",
        "refresh_token": "refresh",
        "expires_in": 1800,
        "expires_at": time.time() + 1800,
        "token_type": "bearer",
        **overrides,
    }
    save_token(token_info, shared.USER_TOKEN_FILE)
    return token_info


def kroger_error(code, reason):
    return {"errors": {"timestamp": 1792605133590, "code": code, "reason": reason}}


async def call_error(client, tool, arguments=None):
    """Call a tool that must fail, and return its structured error and text"""
    result = await client.call_tool(tool, arguments or {}, raise_on_error=False)
    assert result.is_error, f"{tool} did not fail: {result.content}"
    error = result.structured_content["error"]
    assert error["tool"] == tool
    json.dumps(error)  # every detail must be JSON-safe
    text = result.content[0].text
    assert error["message"] in text
    if error.get("next_step"):
        assert f"Next step: {error['next_step']}" in text
    return error, text


async def call_ok(client, tool, arguments=None):
    """Call a tool that must succeed, and return its structured result"""
    result = await client.call_tool(tool, arguments or {}, raise_on_error=False)
    assert not result.is_error, f"{tool} failed: {result.content[0].text}"
    return result.structured_content
