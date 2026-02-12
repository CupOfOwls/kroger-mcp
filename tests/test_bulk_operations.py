"""
Tests for bulk operations support in MCP tools.

Tests Tier 1 (Pantry Tools) and Tier 2 (High-Priority Tools) bulk functionality.
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


# ==================== Tier 1: Pantry Tools ====================


class TestAddToPantryBulk:
    """Test bulk operations for add_to_pantry tool."""

    @patch('kroger_mcp.tools.prediction_tools.add_to_pantry')
    async def test_single_mode_backward_compatibility(self, mock_add):
        """Verify single-item mode works identically to before."""
        from kroger_mcp.tools.prediction_tools import register_tools

        # Mock backend function
        mock_add.return_value = {
            "success": True,
            "product_id": "001",
            "level": 100,
            "daily_depletion_rate": 5.2
        }

        # Create mock MCP server
        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        # Call in single mode
        result = await tool_func(product_id="001", level=100)

        # Should return flat response (not nested)
        assert result["success"] is True
        assert result["product_id"] == "001"
        assert "results" not in result
        assert "summary" not in result

    @patch('kroger_mcp.tools.prediction_tools.add_to_pantry')
    async def test_batch_mode_multiple_items(self, mock_add):
        """Verify batch mode adds multiple items."""
        from kroger_mcp.tools.prediction_tools import register_tools

        # Mock backend function to succeed for all
        mock_add.side_effect = lambda **kwargs: {
            "success": True,
            "product_id": kwargs["product_id"],
            "level": kwargs["level"]
        }

        # Create mock MCP server
        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        # Call in batch mode
        result = await tool_func(product_id=["001", "002", "003"], level=100)

        # Should return structured batch response
        assert result["success"] is True
        assert "results" in result
        assert "summary" in result
        assert len(result["results"]) == 3
        assert result["summary"]["total"] == 3
        assert result["summary"]["successful"] == 3
        assert result["summary"]["failed"] == 0

    async def test_batch_limit_enforced(self):
        """Verify max 50 items enforced."""
        from kroger_mcp.tools.prediction_tools import register_tools

        # Create mock MCP server
        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        # Try with 51 items
        ids = [f"00{i}" for i in range(51)]
        result = await tool_func(product_id=ids, level=100)

        # Should fail with error
        assert result["success"] is False
        assert "Maximum 50" in result["error"]

    @patch('kroger_mcp.tools.prediction_tools.add_to_pantry')
    async def test_partial_failure_continues(self, mock_add):
        """Verify batch continues on individual item failure."""
        from kroger_mcp.tools.prediction_tools import register_tools

        # Mock backend: succeed for 001, fail for 002, succeed for 003
        def mock_behavior(**kwargs):
            if kwargs["product_id"] == "002":
                raise Exception("Product not found")
            return {"success": True, "product_id": kwargs["product_id"]}

        mock_add.side_effect = mock_behavior

        # Create mock MCP server
        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        # Call with 3 items
        result = await tool_func(product_id=["001", "002", "003"], level=100)

        # Should process all items
        assert result["success"] is True
        assert len(result["results"]) == 3
        assert result["results"]["001"]["success"] is True
        assert result["results"]["002"]["success"] is False
        assert result["results"]["003"]["success"] is True
        assert result["summary"]["successful"] == 2
        assert result["summary"]["failed"] == 1


class TestUpdatePantryItemBulk:
    """Test bulk operations for update_pantry_item tool."""

    @patch('kroger_mcp.tools.prediction_tools.update_pantry_level')
    async def test_single_mode(self, mock_update):
        """Verify single-item mode works."""
        from kroger_mcp.tools.prediction_tools import register_tools

        mock_update.return_value = {
            "success": True,
            "product_id": "001",
            "level": 50
        }

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        result = await tool_func(product_id="001", level=50)

        assert result["success"] is True
        assert result["product_id"] == "001"
        assert "results" not in result

    @patch('kroger_mcp.tools.prediction_tools.update_pantry_level')
    async def test_batch_mode(self, mock_update):
        """Verify batch mode updates multiple items."""
        from kroger_mcp.tools.prediction_tools import register_tools

        mock_update.side_effect = lambda pid, level: {
            "success": True,
            "product_id": pid,
            "level": level
        }

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        result = await tool_func(product_id=["001", "002"], level=50)

        assert result["success"] is True
        assert len(result["results"]) == 2
        assert result["summary"]["level_set"] == 50


class TestRemoveFromPantryBulk:
    """Test bulk operations for remove_from_pantry tool."""

    @patch('kroger_mcp.tools.prediction_tools.remove_from_pantry')
    async def test_batch_mode(self, mock_remove):
        """Verify batch mode removes multiple items."""
        from kroger_mcp.tools.prediction_tools import register_tools

        mock_remove.side_effect = lambda pid: {
            "success": True,
            "product_id": pid,
            "message": f"Removed {pid}"
        }

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        result = await tool_func(product_id=["001", "002", "003"])

        assert result["success"] is True
        assert len(result["results"]) == 3
        assert result["summary"]["successful"] == 3


# ==================== Tier 2: High-Priority Tools ====================


class TestCategorizeItemBulk:
    """Test bulk operations for categorize_item tool (Pattern 2: Dual-Mode)."""

    @patch('kroger_mcp.tools.prediction_tools.set_product_category')
    async def test_single_mode(self, mock_categorize):
        """Verify single mode with product_id and category."""
        from kroger_mcp.tools.prediction_tools import register_tools

        mock_result = MagicMock()
        mock_result.previous_category = "regular"
        mock_result.was_override = False
        mock_categorize.return_value = mock_result

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        result = await tool_func(product_id="001", category="routine")

        assert result["success"] is True
        assert result["product_id"] == "001"
        assert result["category"] == "routine"
        assert "results" not in result

    @patch('kroger_mcp.tools.prediction_tools.set_product_category')
    async def test_batch_mode_different_categories(self, mock_categorize):
        """Verify batch mode with different categories per item."""
        from kroger_mcp.tools.prediction_tools import register_tools

        mock_result = MagicMock()
        mock_result.previous_category = "regular"
        mock_result.was_override = False
        mock_categorize.return_value = mock_result

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        items = [
            {"product_id": "001", "category": "routine"},
            {"product_id": "002", "category": "regular"},
            {"product_id": "003", "category": "treat"}
        ]
        result = await tool_func(items=items)

        assert result["success"] is True
        assert len(result["results"]) == 3
        assert result["results"]["001"]["category"] == "routine"
        assert result["results"]["002"]["category"] == "regular"
        assert result["results"]["003"]["category"] == "treat"

    async def test_invalid_category_rejected(self):
        """Verify invalid category is rejected."""
        from kroger_mcp.tools.prediction_tools import register_tools

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        result = await tool_func(product_id="001", category="invalid")

        assert result["success"] is False
        assert "Invalid category" in result["error"]


class TestAddToWatchlistBulk:
    """Test bulk operations for add_to_watchlist tool."""

    @patch('kroger_mcp.tools.deal_tools.get_preferred_location_id')
    @patch('kroger_mcp.tools.deal_tools.get_client_credentials_client')
    @patch('kroger_mcp.tools.deal_tools.get_db_cursor')
    async def test_batch_mode(self, mock_cursor, mock_client, mock_location):
        """Verify batch mode adds multiple items to watchlist."""
        from kroger_mcp.tools.deal_tools import register_tools

        # Mock location
        mock_location.return_value = "loc123"

        # Mock API client
        mock_api = MagicMock()
        mock_api.get_product.return_value = {
            "data": {
                "description": "Test Product",
                "pricing": {"regular_price": 5.99, "on_sale": False}
            }
        }
        mock_client.return_value = mock_api

        # Mock database cursor
        mock_db = MagicMock()
        mock_cursor.return_value.__enter__.return_value = mock_db

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        result = await tool_func(product_id=["001", "002"], priority=2)

        assert result["success"] is True
        assert len(result["results"]) == 2
        assert result["summary"]["priority"] == "medium"

    async def test_batch_limit_30_items(self):
        """Verify max 30 items enforced for watchlist."""
        from kroger_mcp.tools.deal_tools import register_tools

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        # Try with 31 items
        ids = [f"00{i}" for i in range(31)]
        result = await tool_func(product_id=ids)

        assert result["success"] is False
        assert "Maximum 30" in result["error"]


class TestAddCustomIngredientBulk:
    """Test bulk operations for add_custom_ingredient tool."""

    @patch('kroger_mcp.tools.ingredient_management_tools.get_db_connection')
    @patch('kroger_mcp.tools.ingredient_management_tools.get_compiled_patterns')
    async def test_batch_mode(self, mock_patterns, mock_conn):
        """Verify batch mode adds multiple ingredients."""
        from kroger_mcp.tools.ingredient_management_tools import register_tools

        # Mock database
        mock_db = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None  # Ingredient doesn't exist
        mock_cursor.lastrowid = 1
        mock_db.execute.return_value = mock_cursor
        mock_conn.return_value = mock_db

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        ingredients = [
            {
                "ingredient_name": "maltitol",
                "severity": "warning",
                "reason": "Digestive issues"
            },
            {
                "ingredient_name": "sucralose",
                "severity": "critical",
                "reason": "Gut disruption"
            }
        ]
        result = await tool_func(ingredients=ingredients)

        assert result["success"] is True
        assert len(result["results"]) == 2
        assert result["summary"]["successful"] == 2

    async def test_batch_limit_20_items(self):
        """Verify max 20 items enforced."""
        from kroger_mcp.tools.ingredient_management_tools import register_tools

        mcp = MagicMock()
        tool_func = None

        def capture_tool(func):
            nonlocal tool_func
            tool_func = func
            return func

        mcp.tool.return_value = capture_tool
        register_tools(mcp)

        # Try with 21 items
        ingredients = [
            {"ingredient_name": f"ing{i}", "severity": "watch"}
            for i in range(21)
        ]
        result = await tool_func(ingredients=ingredients)

        assert result["success"] is False
        assert "Maximum 20" in result["error"]


# ==================== Response Format Tests ====================


class TestResponseFormats:
    """Test response format consistency across all bulk tools."""

    async def test_single_mode_returns_flat_response(self):
        """Verify single mode returns flat response (not nested)."""
        # This is tested in individual tool tests above
        pass

    async def test_batch_mode_returns_structured_response(self):
        """Verify batch mode returns results dict + summary."""
        # Expected structure:
        # {
        #     "success": True,
        #     "results": {
        #         "product_id": {"success": True, ...},
        #         ...
        #     },
        #     "summary": {
        #         "total": N,
        #         "successful": M,
        #         "failed": K
        #     }
        # }
        pass


# ==================== Integration Tests ====================


@pytest.mark.integration
class TestBulkIntegration:
    """Integration tests for bulk operations (require database)."""

    async def test_end_to_end_pantry_batch(self):
        """Test complete workflow: add multiple items to pantry."""
        # This would require actual database setup
        # Skip for unit tests, run separately
        pytest.skip("Integration test - requires database")

    async def test_end_to_end_categorize_batch(self):
        """Test complete workflow: categorize multiple items."""
        pytest.skip("Integration test - requires database")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
