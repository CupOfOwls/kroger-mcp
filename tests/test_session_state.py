"""
Unit tests for session state tracking.
"""

import pytest
from datetime import datetime, timedelta
from src.kroger_mcp.session_state import SessionStateManager


def test_initial_state():
    """Test initial session state is empty."""
    manager = SessionStateManager()
    assert not manager.was_tool_called("session1", "get_pantry_attention")


def test_mark_tool_called():
    """Test marking a tool as called."""
    manager = SessionStateManager()

    # Mark tool as called
    manager.mark_tool_called("session1", "get_pantry_attention")

    # Should be marked as called
    assert manager.was_tool_called("session1", "get_pantry_attention")


def test_session_isolation():
    """Test that sessions are isolated from each other."""
    manager = SessionStateManager()

    # Mark tool for session1
    manager.mark_tool_called("session1", "get_pantry_attention")

    # session1 should have it
    assert manager.was_tool_called("session1", "get_pantry_attention")

    # session2 should NOT have it
    assert not manager.was_tool_called("session2", "get_pantry_attention")


def test_multiple_tools_per_session():
    """Test tracking multiple tools in a session."""
    manager = SessionStateManager()

    # Mark multiple tools
    manager.mark_tool_called("session1", "get_pantry_attention")
    manager.mark_tool_called("session1", "add_to_cart")
    manager.mark_tool_called("session1", "search_products")

    # All should be tracked
    assert manager.was_tool_called("session1", "get_pantry_attention")
    assert manager.was_tool_called("session1", "add_to_cart")
    assert manager.was_tool_called("session1", "search_products")


def test_reset_session():
    """Test resetting a session clears its state."""
    manager = SessionStateManager()

    # Mark tools
    manager.mark_tool_called("session1", "get_pantry_attention")
    manager.mark_tool_called("session1", "add_to_cart")

    # Verify they're tracked
    assert manager.was_tool_called("session1", "get_pantry_attention")

    # Reset session
    manager.reset_session("session1")

    # Should be cleared
    assert not manager.was_tool_called("session1", "get_pantry_attention")
    assert not manager.was_tool_called("session1", "add_to_cart")


def test_cleanup_stale_sessions():
    """Test cleanup of stale sessions."""
    manager = SessionStateManager()

    # Mark tool and manually set old timestamp
    manager.mark_tool_called("old_session", "get_pantry_attention")
    manager._last_activity["old_session"] = datetime.now() - timedelta(hours=25)

    # Mark tool for fresh session
    manager.mark_tool_called("new_session", "get_pantry_attention")

    # Run cleanup (24 hour threshold)
    manager.cleanup_stale_sessions(max_age_hours=24)

    # Old session should be cleaned up
    assert not manager.was_tool_called("old_session", "get_pantry_attention")

    # New session should still exist
    assert manager.was_tool_called("new_session", "get_pantry_attention")


def test_activity_updates_on_mark():
    """Test that marking a tool updates last activity."""
    import time
    manager = SessionStateManager()

    # Mark tool
    manager.mark_tool_called("session1", "tool1")
    time1 = manager._last_activity.get("session1")

    # Wait a tiny bit to ensure different timestamp
    time.sleep(0.001)

    # Mark another tool (should update activity)
    manager.mark_tool_called("session1", "tool2")
    time2 = manager._last_activity.get("session1")

    # Activity time should be updated (or at least not less)
    assert time2 >= time1
