"""
Favorite lists MCP tools for the Kroger MCP server.

Provides 9 tools for managing named favorite lists as a shopping list
workaround (since Kroger Public API doesn't support actual lists).
"""

from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import Field


def register_tools(mcp):
    """Register favorite list tools with the FastMCP server."""

    # ========== List Management Tools ==========

    @mcp.tool()
    async def create_favorite_list(
        name: str = Field(
            description="List name (e.g., 'Weekly Staples', 'Party Supplies')"
        ),
        description: str = Field(
            default=None,
            description="Optional description of the list"
        ),
        list_type: str = Field(
            default="custom",
            description="List type: 'custom', 'weekly', 'monthly', 'seasonal'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Create a new named favorite list.

        Use lists to organize frequently purchased items. Each list can have
        its own products and can be ordered separately.

        Examples:
        - "Weekly Staples" for items you buy every week
        - "Party Supplies" for event shopping
        - "Monthly Bulk" for less frequent purchases

        Args:
            name: Unique name for the list
            description: Optional description
            list_type: Category type for the list

        Returns:
            Created list info with list_id
        """
        from ..analytics.favorites import create_list

        result = create_list(
            name=name,
            description=description,
            list_type=list_type
        )
        return result

    @mcp.tool()
    async def get_favorite_lists(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get all favorite lists with item counts.

        Returns all lists including the default "My Favorites" list,
        with the number of items in each.

        Returns:
            List of all favorite lists with metadata
        """
        from ..analytics.favorites import get_lists

        lists = get_lists()
        return {
            "success": True,
            "lists": lists,
            "total_lists": len(lists)
        }

    @mcp.tool()
    async def rename_favorite_list(
        list_id: str = Field(
            description="ID of the list to rename"
        ),
        new_name: str = Field(
            default=None,
            description="New name for the list"
        ),
        new_description: str = Field(
            default=None,
            description="New description for the list"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Rename a favorite list or update its description.

        Note: The default list cannot be renamed.

        Args:
            list_id: The list ID to update
            new_name: New name (optional)
            new_description: New description (optional)

        Returns:
            Success status
        """
        from ..analytics.favorites import rename_list

        return rename_list(
            list_id=list_id,
            new_name=new_name,
            new_description=new_description
        )

    @mcp.tool()
    async def delete_favorite_list(
        list_id: str = Field(
            description="ID of the list to delete (cannot delete 'default')"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Delete a favorite list and all its items.

        This permanently removes the list and all products in it.
        The default "My Favorites" list cannot be deleted.

        Args:
            list_id: The list ID to delete

        Returns:
            Success status with count of items deleted
        """
        from ..analytics.favorites import delete_list

        return delete_list(list_id=list_id)

    # ========== Item Management Tools ==========

    @mcp.tool()
    async def add_to_favorite_list(
        product_id: str = Field(
            default=None,
            description="Kroger product ID to add (for single item)"
        ),
        description: str = Field(
            default=None,
            description="Product description (for single item)"
        ),
        list_id: str = Field(
            default="default",
            description="List ID to add to (defaults to 'default')"
        ),
        brand: str = Field(
            default=None,
            description="Product brand (for single item)"
        ),
        default_quantity: int = Field(
            default=1, ge=1, le=100,
            description="Default quantity when ordering (for single item)"
        ),
        preferred_modality: str = Field(
            default="PICKUP",
            description="Preferred fulfillment: 'PICKUP' or 'DELIVERY'"
        ),
        notes: str = Field(
            default=None,
            description="Optional notes about this item (for single item)"
        ),
        items: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description="""For bulk add: list of items, each with:
            - product_id (required): Kroger product ID
            - description (required): Product description
            - brand (optional): Product brand
            - default_quantity (optional): Default quantity (default 1)
            - preferred_modality (optional): PICKUP or DELIVERY
            - notes (optional): Notes about the item"""
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add one or more products to a favorite list.

        For single item: provide product_id and description.
        For bulk add: provide items list with multiple products.

        If no list_id is provided, adds to the default "My Favorites" list.
        Each product can only appear once per list.

        Examples:
        - Single: add_to_favorite_list(product_id="123", description="Milk")
        - Bulk: add_to_favorite_list(items=[
            {"product_id": "123", "description": "Milk"},
            {"product_id": "456", "description": "Bread", "default_quantity": 2}
          ])

        Args:
            product_id: Kroger product ID (for single item)
            description: Product description (for single item)
            list_id: Which list to add to
            brand: Product brand (for single item)
            default_quantity: Quantity to order by default (for single item)
            preferred_modality: PICKUP or DELIVERY
            notes: Optional notes (for single item)
            items: List of items for bulk add

        Returns:
            Success status with added/failed counts for bulk operations
        """
        from ..analytics.favorites import add_to_list, bulk_add_to_list

        # Bulk add mode
        if items is not None:
            return bulk_add_to_list(list_id=list_id, items=items)

        # Single item mode - validate required fields
        if not product_id or not description:
            return {
                "success": False,
                "error": "For single item add, both product_id and description "
                         "are required. For bulk add, provide items list."
            }

        return add_to_list(
            list_id=list_id,
            product_id=product_id,
            description=description,
            brand=brand,
            default_quantity=default_quantity,
            preferred_modality=preferred_modality,
            notes=notes
        )

    @mcp.tool()
    async def remove_from_favorite_list(
        product_id: str = Field(
            description="Kroger product ID to remove"
        ),
        list_id: str = Field(
            default="default",
            description="List ID to remove from (defaults to 'default')"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Remove a product from a favorite list.

        Args:
            product_id: Kroger product ID to remove
            list_id: Which list to remove from

        Returns:
            Success status
        """
        from ..analytics.favorites import remove_from_list

        return remove_from_list(list_id=list_id, product_id=product_id)

    @mcp.tool()
    async def get_favorite_list_items(
        list_id: str = Field(
            default="default",
            description="List ID to get items from (defaults to 'default')"
        ),
        include_pantry_status: bool = Field(
            default=True,
            description="Include current pantry levels for each item"
        ),
        sort_by: str = Field(
            default="description",
            description="Sort by: 'description', 'times_ordered', 'added_at'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get all items in a favorite list with optional pantry status.

        Shows each item's product info, default quantity, and optionally
        current pantry levels with reorder recommendations.

        Args:
            list_id: Which list to get items from
            include_pantry_status: Show pantry levels
            sort_by: How to sort results

        Returns:
            List info and items with pantry status
        """
        from ..analytics.favorites import get_list_items

        return get_list_items(
            list_id=list_id,
            include_pantry_status=include_pantry_status,
            sort_by=sort_by
        )

    # ========== Smart Ordering Tools ==========

    @mcp.tool()
    async def order_favorite_list(
        list_id: str = Field(
            default="default",
            description="List ID to order from (defaults to 'default')"
        ),
        skip_if_stocked: bool = Field(
            default=True,
            description="Skip items with pantry level above threshold"
        ),
        pantry_threshold: int = Field(
            default=30, ge=0, le=100,
            description="Skip items with pantry level above this percentage"
        ),
        modality: str = Field(
            default=None,
            description="Override all items' modality: 'PICKUP' or 'DELIVERY'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add favorite list items to cart, optionally skipping well-stocked items.

        Checks pantry levels and skips items that are still well-stocked.
        Uses each item's preferred modality unless overridden.

        Args:
            list_id: Which list to order from
            skip_if_stocked: Skip items above pantry threshold
            pantry_threshold: Pantry level above which to skip
            modality: Override fulfillment method for all items

        Returns:
            Summary of items added and skipped
        """
        from ..analytics.favorites import get_list_items, increment_times_ordered

        # Get all items with pantry status
        result = get_list_items(list_id, include_pantry_status=True)
        if not result.get("success"):
            return result

        items_to_order = []
        items_skipped = []

        for item in result["items"]:
            pantry = item.get("pantry_status", {})
            level = pantry.get("level_percent")

            # Determine if we should skip
            should_skip = False
            skip_reason = None

            if skip_if_stocked and level is not None and level >= pantry_threshold:
                should_skip = True
                skip_reason = f"Pantry at {level}% (threshold: {pantry_threshold}%)"

            if should_skip:
                items_skipped.append({
                    "product_id": item["product_id"],
                    "description": item["description"],
                    "reason": skip_reason,
                    "pantry_level": level
                })
            else:
                items_to_order.append({
                    "upc": item["product_id"],
                    "quantity": item["default_quantity"],
                    "modality": modality or item["preferred_modality"],
                    "description": item["description"]
                })

        if not items_to_order:
            return {
                "success": True,
                "message": "No items needed - all are well-stocked",
                "items_ordered": [],
                "items_skipped": items_skipped,
                "order_count": 0,
                "skip_count": len(items_skipped)
            }

        # Use the cart API directly like bulk_add_to_cart does
        try:
            from .shared import get_authenticated_client
            from .cart_tools import _add_item_to_local_cart

            client = get_authenticated_client()

            # Format items for the Kroger API (uses 'upc' not 'product_id')
            cart_items = [
                {
                    "upc": item["product_id"],
                    "quantity": item["quantity"],
                    "modality": item["modality"]
                }
                for item in items_to_order
            ]

            # Add all items to the actual Kroger cart
            client.cart.add_to_cart(cart_items)

            # Add to local cart tracking
            for item in items_to_order:
                _add_item_to_local_cart(
                    item["product_id"],
                    item["quantity"],
                    item["modality"],
                    {"description": item.get("description")}
                )

            # Update times_ordered counter
            ordered_ids = [i["product_id"] for i in items_to_order]
            increment_times_ordered(list_id, ordered_ids)

            return {
                "success": True,
                "message": f"Added {len(items_to_order)} items, skipped {len(items_skipped)}",
                "items_ordered": [
                    {"product_id": i["product_id"], "description": i["description"],
                     "quantity": i["quantity"], "modality": i["modality"]}
                    for i in items_to_order
                ],
                "items_skipped": items_skipped,
                "order_count": len(items_to_order),
                "skip_count": len(items_skipped)
            }
        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "Unauthorized" in error_msg:
                auth_err = "Authentication failed. Run force_reauthenticate."
                return {
                    "success": False,
                    "error": auth_err,
                    "details": error_msg
                }
            return {
                "success": False,
                "error": f"Failed to add items to cart: {error_msg}",
                "items_to_order": [
                    {"product_id": i["product_id"], "description": i["description"]}
                    for i in items_to_order
                ],
                "items_skipped": items_skipped
            }

    @mcp.tool()
    async def suggest_favorites(
        list_id: str = Field(
            default=None,
            description="If provided, excludes items already in this list"
        ),
        min_purchases: int = Field(
            default=3, ge=1, le=100,
            description="Minimum purchases to be suggested"
        ),
        min_frequency_score: float = Field(
            default=0.5, ge=0.0, le=1.0,
            description="Minimum frequency score (0-1)"
        ),
        limit: int = Field(
            default=10, ge=1, le=50,
            description="Maximum suggestions to return"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Suggest products to add to favorites based on purchase history.

        Analyzes your purchase patterns to find frequently bought items
        that aren't yet in your favorite lists.

        Args:
            list_id: Exclude items already in this list
            min_purchases: Minimum purchase count to qualify
            min_frequency_score: Minimum frequency score
            limit: Max suggestions

        Returns:
            List of suggested products with purchase stats
        """
        from ..analytics.favorites import suggest_for_list

        return suggest_for_list(
            list_id=list_id,
            min_purchases=min_purchases,
            min_frequency_score=min_frequency_score,
            limit=limit
        )
