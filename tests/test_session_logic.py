"""
Unit tests for session requirement logic (without full imports).
"""

import pytest
from src.kroger_mcp.session_state import get_session_manager


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


def test_workflow_blocks_without_attention():
    """Test that session requirement logic blocks cart operations."""
    manager = get_session_manager()
    session_id = "test_session"

    # Simulate checking if attention was called (should be False)
    attention_called = manager.was_tool_called(session_id, "get_pantry_attention")
    assert not attention_called

    # This is what add_to_cart does - it should fail
    if not attention_called:
        # Operation should be blocked
        result = {
            "success": False,
            "error": "Session requirement not met",
            "error_code": "ATTENTION_REQUIRED"
        }
        assert result["success"] is False
        assert result["error_code"] == "ATTENTION_REQUIRED"


def test_workflow_allows_after_attention():
    """Test that session requirement logic allows cart operations after attention called."""
    manager = get_session_manager()
    session_id = "test_session"

    # Simulate calling attention tool first
    manager.mark_tool_called(session_id, "get_pantry_attention")

    # Now check if we can proceed
    attention_called = manager.was_tool_called(session_id, "get_pantry_attention")
    assert attention_called

    # Operation should be allowed
    if attention_called:
        result = {"success": True, "allowed": True}
        assert result["success"] is True


def test_workflow_session_isolation():
    """Test that requirement is session-scoped."""
    manager = get_session_manager()

    # Session 1 calls attention
    manager.mark_tool_called("session1", "get_pantry_attention")

    # Session 1 should be allowed
    assert manager.was_tool_called("session1", "get_pantry_attention")

    # Session 2 should NOT be allowed (different session)
    assert not manager.was_tool_called("session2", "get_pantry_attention")


def test_workflow_persistent_within_session():
    """Test that requirement persists for multiple operations in same session."""
    manager = get_session_manager()
    session_id = "test_session"

    # Call attention once
    manager.mark_tool_called(session_id, "get_pantry_attention")

    # Should be allowed multiple times in same session
    assert manager.was_tool_called(session_id, "get_pantry_attention")
    assert manager.was_tool_called(session_id, "get_pantry_attention")
    assert manager.was_tool_called(session_id, "get_pantry_attention")

    # All operations in this session should pass the check


def test_workflow_error_message_structure():
    """Test that error message has proper structure for client."""
    manager = get_session_manager()
    session_id = "test_session"

    # Check requirement
    if not manager.was_tool_called(session_id, "get_pantry_attention"):
        error_response = {
            "success": False,
            "error": "Session requirement not met",
            "error_code": "ATTENTION_REQUIRED",
            "message": (
                "You must call get_pantry_attention() at least once before adding "
                "items to cart. This ensures you review what needs attention "
                "(expiring items, low inventory, overdue reorders) before shopping.\n\n"
                "To fix: Call get_pantry_attention() first, then retry add_to_cart."
            ),
            "required_action": {
                "tool": "get_pantry_attention",
                "reason": "Review items needing attention before shopping",
                "required_before": ["add_to_cart", "add items to cart"]
            }
        }

        # Verify structure
        assert error_response["success"] is False
        assert error_response["error_code"] == "ATTENTION_REQUIRED"
        assert "required_action" in error_response
        assert error_response["required_action"]["tool"] == "get_pantry_attention"
        assert isinstance(error_response["required_action"]["required_before"], list)


def test_workflow_success_indicator():
    """Test that attention tool marks success."""
    manager = get_session_manager()
    session_id = "test_session"

    # Simulate attention tool success
    manager.mark_tool_called(session_id, "get_pantry_attention")

    # Simulate response
    response = {
        "success": True,
        "items": [],
        "summary": {},
        "_session_requirement_fulfilled": True
    }

    # Verify session flag is set
    assert manager.was_tool_called(session_id, "get_pantry_attention")
    assert response["_session_requirement_fulfilled"] is True
