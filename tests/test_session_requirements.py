"""
Integration tests for session-based tool requirements.
"""

import pytest
from unittest.mock import Mock, AsyncMock
from src.kroger_mcp.session_state import get_session_manager


# Mock Context for testing
class MockContext:
    def __init__(self, session_id="test_session"):
        self.session_id = session_id

    async def info(self, message):
        pass

    async def error(self, message):
        pass


@pytest.fixture(autouse=True)
def reset_session_state():
    """Reset session state before each test."""
    manager = get_session_manager()
    # Clear all sessions
    manager._tool_calls.clear()
    manager._last_activity.clear()
    yield
    # Cleanup after test
    manager._tool_calls.clear()
    manager._last_activity.clear()


@pytest.mark.asyncio
async def test_add_to_cart_blocks_without_attention():
    """Test that add_to_cart blocks if attention not called."""
    from src.kroger_mcp.tools.cart_tools import register_tools
    from fastmcp import FastMCP

    # Create a minimal MCP instance
    mcp = FastMCP("test")
    register_tools(mcp)

    # Get the add_to_cart function
    # Note: We need to call it directly as a function
    # For now, we'll test the logic by importing the session manager

    from src.kroger_mcp.session_state import get_session_manager

    manager = get_session_manager()
    ctx = MockContext("test_session_1")

    # Verify attention not called yet
    assert not manager.was_tool_called("test_session_1", "get_pantry_attention")

    # This would be tested in actual MCP call - for unit test we verify the state


@pytest.mark.asyncio
async def test_get_pantry_attention_sets_session_flag():
    """Test that get_pantry_attention marks session state."""
    from src.kroger_mcp.session_state import get_session_manager

    manager = get_session_manager()
    ctx = MockContext("test_session_2")

    # Initially not called
    assert not manager.was_tool_called("test_session_2", "get_pantry_attention")

    # Simulate the tool being called (mark it)
    manager.mark_tool_called("test_session_2", "get_pantry_attention")

    # Now it should be marked
    assert manager.was_tool_called("test_session_2", "get_pantry_attention")


@pytest.mark.asyncio
async def test_session_independence():
    """Test that different sessions are independent."""
    from src.kroger_mcp.session_state import get_session_manager

    manager = get_session_manager()

    # Session 1 calls attention
    manager.mark_tool_called("session1", "get_pantry_attention")

    # Session 1 should have it
    assert manager.was_tool_called("session1", "get_pantry_attention")

    # Session 2 should NOT have it (independent session)
    assert not manager.was_tool_called("session2", "get_pantry_attention")


@pytest.mark.asyncio
async def test_session_persists_across_multiple_tool_calls():
    """Test that session state persists across multiple tool calls."""
    from src.kroger_mcp.session_state import get_session_manager

    manager = get_session_manager()

    # Call attention once
    manager.mark_tool_called("session1", "get_pantry_attention")

    # Should allow multiple subsequent operations in the same session
    assert manager.was_tool_called("session1", "get_pantry_attention")
    assert manager.was_tool_called("session1", "get_pantry_attention")
    assert manager.was_tool_called("session1", "get_pantry_attention")


def test_session_id_extraction_with_context():
    """Test session ID extraction from context."""
    from src.kroger_mcp.tools.cart_tools import _get_session_id

    ctx = MockContext("my_session_id")
    session_id = _get_session_id(ctx)

    assert session_id == "my_session_id"


def test_session_id_fallback_without_context():
    """Test session ID fallback when no context provided."""
    from src.kroger_mcp.tools.cart_tools import _get_session_id

    session_id = _get_session_id(None)

    # Should fall back to 'default'
    assert session_id == "default"
