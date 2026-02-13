#!/usr/bin/env python3
"""
Manual test script for session-based attention tool requirement.

This script demonstrates the session requirement enforcement:
1. Try to add to cart without calling attention → BLOCKED
2. Call get_pantry_attention → SUCCESS
3. Try to add to cart after calling attention → ALLOWED
"""

import asyncio
from src.kroger_mcp.session_state import get_session_manager


class MockContext:
    """Mock context for testing."""
    def __init__(self, session_id="test_session"):
        self.session_id = session_id

    async def info(self, message):
        print(f"[INFO] {message}")

    async def error(self, message):
        print(f"[ERROR] {message}")


def _get_session_id(ctx):
    """Extract session ID from context."""
    if ctx and hasattr(ctx, 'session_id'):
        return str(ctx.session_id)
    return 'default'


async def simulate_add_to_cart(ctx):
    """Simulate the add_to_cart tool logic."""
    from src.kroger_mcp.session_state import get_session_manager

    session_id = _get_session_id(ctx)
    session_manager = get_session_manager()

    # HARD REQUIREMENT CHECK
    if not session_manager.was_tool_called(session_id, "get_pantry_attention"):
        return {
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
                "required_before": ["add_to_cart"]
            }
        }

    # If we get here, the requirement was met
    return {
        "success": True,
        "message": "Item added to cart successfully",
        "product_id": "test_product",
        "quantity": 1
    }


async def simulate_get_pantry_attention(ctx):
    """Simulate the get_pantry_attention tool logic."""
    from src.kroger_mcp.session_state import get_session_manager

    session_id = _get_session_id(ctx)
    session_manager = get_session_manager()

    # Simulate successful call
    session_manager.mark_tool_called(session_id, "get_pantry_attention")

    return {
        "success": True,
        "items": [],
        "summary": {
            "total_items": 0,
            "expired": 0,
            "low_inventory": 0
        },
        "_session_requirement_fulfilled": True
    }


async def main():
    """Run the manual test."""
    print("=" * 70)
    print("SESSION-BASED ATTENTION REQUIREMENT TEST")
    print("=" * 70)
    print()

    ctx = MockContext("manual_test_session")

    # Reset session state for clean test
    manager = get_session_manager()
    manager.reset_session("manual_test_session")

    # TEST 1: Try to add to cart WITHOUT calling attention first
    print("TEST 1: Add to cart WITHOUT calling get_pantry_attention first")
    print("-" * 70)
    result1 = await simulate_add_to_cart(ctx)
    print(f"Result: {result1['success']}")
    if not result1['success']:
        print(f"Error Code: {result1.get('error_code')}")
        print(f"Message: {result1.get('message')}")
        print(f"Required Action: {result1.get('required_action')}")
    print()

    # TEST 2: Call get_pantry_attention
    print("TEST 2: Call get_pantry_attention()")
    print("-" * 70)
    result2 = await simulate_get_pantry_attention(ctx)
    print(f"Result: {result2['success']}")
    print(f"Session Requirement Fulfilled: {result2.get('_session_requirement_fulfilled')}")
    print(f"Summary: {result2.get('summary')}")
    print()

    # TEST 3: Try to add to cart AFTER calling attention
    print("TEST 3: Add to cart AFTER calling get_pantry_attention")
    print("-" * 70)
    result3 = await simulate_add_to_cart(ctx)
    print(f"Result: {result3['success']}")
    if result3['success']:
        print(f"Message: {result3.get('message')}")
        print(f"Product ID: {result3.get('product_id')}")
    print()

    # TEST 4: Add to cart again (should still work in same session)
    print("TEST 4: Add to cart AGAIN (same session)")
    print("-" * 70)
    result4 = await simulate_add_to_cart(ctx)
    print(f"Result: {result4['success']}")
    if result4['success']:
        print(f"Message: {result4.get('message')}")
    print()

    # TEST 5: New session should require calling attention again
    print("TEST 5: New session (different session ID)")
    print("-" * 70)
    new_ctx = MockContext("new_session")
    result5 = await simulate_add_to_cart(new_ctx)
    print(f"Result: {result5['success']}")
    if not result5['success']:
        print(f"Error Code: {result5.get('error_code')}")
        print("✓ Correctly blocked - new session requires calling attention again")
    print()

    # SUMMARY
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    print(f"Test 1 (blocked without attention): {'✓ PASS' if not result1['success'] else '✗ FAIL'}")
    print(f"Test 2 (attention call success): {'✓ PASS' if result2['success'] else '✗ FAIL'}")
    print(f"Test 3 (allowed after attention): {'✓ PASS' if result3['success'] else '✗ FAIL'}")
    print(f"Test 4 (still allowed in session): {'✓ PASS' if result4['success'] else '✗ FAIL'}")
    print(f"Test 5 (new session blocked): {'✓ PASS' if not result5['success'] else '✗ FAIL'}")
    print()

    # Verify all tests passed
    all_passed = (
        not result1['success'] and  # Should be blocked
        result2['success'] and      # Should succeed
        result3['success'] and      # Should be allowed
        result4['success'] and      # Should still be allowed
        not result5['success']      # New session should be blocked
    )

    if all_passed:
        print("✓✓✓ ALL TESTS PASSED ✓✓✓")
    else:
        print("✗✗✗ SOME TESTS FAILED ✗✗✗")

    print()


if __name__ == "__main__":
    asyncio.run(main())
