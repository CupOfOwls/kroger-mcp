"""
Cart tracking and management functionality
"""
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from ..errors import KrogerToolError, translate_errors
from .params import Modality, ProductId, Quantity
from .shared import get_authenticated_client, load_state_file, save_state_file


# Cart storage file (resolved to the shared per-user data directory)
CART_FILE = "kroger_cart.json"
ORDER_HISTORY_FILE = "kroger_order_history.json"


class CartItem(BaseModel):
    """One item of a bulk_add_to_cart call"""

    model_config = ConfigDict(extra="forbid")

    product_id: ProductId
    quantity: Quantity = 1
    modality: Modality = "PICKUP"


def _load_cart_data() -> Dict[str, Any]:
    """Load cart data from file"""
    cart_data = load_state_file(CART_FILE, {})
    cart_data.setdefault("current_cart", [])
    cart_data.setdefault("last_updated", None)
    return cart_data


def _save_cart_data(cart_data: Dict[str, Any]) -> None:
    """Save cart data to file"""
    save_state_file(CART_FILE, cart_data)


def _load_order_history() -> List[Dict[str, Any]]:
    """Load order history from file"""
    return load_state_file(ORDER_HISTORY_FILE, [])


def _save_order_history(history: List[Dict[str, Any]]) -> None:
    """Save order history to file"""
    save_state_file(ORDER_HISTORY_FILE, history)


def _add_items_to_local_cart(items: List[Dict[str, Any]]) -> Optional[str]:
    """Add items to the local cart tracking

    The items are already in the Kroger cart when this runs, so a failure
    here must not fail the tool call: a caller that retries would add the
    items to the Kroger cart twice.

    Args:
        items: Cart items as sent to the API, with upc, quantity, and modality

    Returns:
        A warning for the tool result if the local tracking was not updated, else None
    """
    try:
        cart_data = _load_cart_data()
        current_cart = cart_data["current_cart"]
        now = datetime.now().isoformat()
        
        for item in items:
            product_id, quantity, modality = item["upc"], item["quantity"], item["modality"]
            # Check if item already exists in cart
            existing_item = next(
                (i for i in current_cart if i.get("product_id") == product_id and i.get("modality") == modality),
                None
            )
            if existing_item:
                # Update existing item quantity
                existing_item["quantity"] = existing_item.get("quantity", 0) + quantity
                existing_item["last_updated"] = now
            else:
                current_cart.append({
                    "product_id": product_id,
                    "quantity": quantity,
                    "modality": modality,
                    "added_at": now,
                    "last_updated": now
                })
        
        cart_data["last_updated"] = now
        _save_cart_data(cart_data)
    except KrogerToolError as e:
        return (
            f"The Kroger cart was updated, but the local cart tracking was not: {e.message} "
            f"Do not add the items again."
        )
    return None


def register_tools(mcp):
    """Register cart-related tools with the FastMCP server"""
    
    @mcp.tool()
    @translate_errors
    async def add_items_to_cart(
        product_id: ProductId,
        quantity: Quantity = 1,
        modality: Modality = "PICKUP",
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add a single item to the user's Kroger cart and track it locally.
        
        If the user doesn't specifically indicate a preference for pickup or delivery,
        you should ask them which modality they prefer before calling this tool.
        
        Args:
            product_id: The product ID or UPC to add to cart
            quantity: Quantity to add (default: 1)
            modality: Fulfillment method - PICKUP or DELIVERY
        
        Returns:
            Dictionary confirming the item was added to cart
        """
        if ctx:
            await ctx.info(f"Adding {quantity}x {product_id} to cart with {modality} modality")
        
        # Raises authentication_required if the user is not signed in
        client = get_authenticated_client()
        
        # Format the item for the API
        cart_item = {
            "upc": product_id,
            "quantity": quantity,
            "modality": modality
        }
        
        if ctx:
            await ctx.info(f"Calling Kroger API to add item: {cart_item}")
        
        # add_to_cart returns None on success and raises a kroger-api error on failure
        client.cart.add_to_cart([cart_item])
        
        if ctx:
            await ctx.info("Successfully added item to Kroger cart")
        
        result = {
            "success": True,
            "message": f"Successfully added {quantity}x {product_id} to cart",
            "product_id": product_id,
            "quantity": quantity,
            "modality": modality,
            "timestamp": datetime.now().isoformat()
        }
        warning = _add_items_to_local_cart([cart_item])
        if warning:
            result["warning"] = warning
        return result

    @mcp.tool()
    @translate_errors
    async def bulk_add_to_cart(
        items: Annotated[List[CartItem], Field(min_length=1)],
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add multiple items to the user's Kroger cart in a single operation.
        
        If the user doesn't specifically indicate a preference for pickup or delivery,
        you should ask them which modality they prefer before calling this tool.
        
        Args:
            items: List of items to add. Each item should have:
                   - product_id: The product ID or UPC
                   - quantity: Quantity to add (default: 1)
                   - modality: PICKUP or DELIVERY (default: PICKUP)
        
        Returns:
            Dictionary with results for each item
        """
        if ctx:
            await ctx.info(f"Adding {len(items)} items to cart in bulk")
        
        client = get_authenticated_client()
        
        # Format items for the API
        cart_items = [
            {"upc": item.product_id, "quantity": item.quantity, "modality": item.modality}
            for item in items
        ]
        
        if ctx:
            await ctx.info(f"Calling Kroger API to add {len(cart_items)} items")
        
        # All items go in one request, so they are added together or not at all
        client.cart.add_to_cart(cart_items)
        
        if ctx:
            await ctx.info("Successfully added all items to Kroger cart")
        
        result = {
            "success": True,
            "message": f"Successfully added {len(items)} items to cart",
            "items_added": len(items),
            "timestamp": datetime.now().isoformat()
        }
        warning = _add_items_to_local_cart(cart_items)
        if warning:
            result["warning"] = warning
        return result

    @mcp.tool()
    @translate_errors
    async def view_current_cart(ctx: Context = None) -> Dict[str, Any]:
        """
        View the current cart contents tracked locally.
        
        Note: This tool can only see items that were added via this MCP server.
        The Kroger API does not provide permission to query the actual user cart contents.
        
        Returns:
            Dictionary containing current cart items and summary
        """
        cart_data = _load_cart_data()
        current_cart = cart_data["current_cart"]
        
        # Calculate summary
        total_quantity = sum(item.get("quantity", 0) for item in current_cart)
        pickup_items = [item for item in current_cart if item.get("modality") == "PICKUP"]
        delivery_items = [item for item in current_cart if item.get("modality") == "DELIVERY"]
        
        return {
            "success": True,
            "current_cart": current_cart,
            "summary": {
                "total_items": len(current_cart),
                "total_quantity": total_quantity,
                "pickup_items": len(pickup_items),
                "delivery_items": len(delivery_items),
                "last_updated": cart_data.get("last_updated")
            }
        }

    @mcp.tool()
    @translate_errors
    async def remove_from_cart(
        product_id: Annotated[str, Field(min_length=1, description="The product ID to remove from the local tracking")],
        modality: Optional[Modality] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Remove an item from the local cart tracking only.
        
        IMPORTANT: This tool CANNOT remove items from the actual Kroger cart in the app/website.
        It only updates our local tracking to stay in sync. The user must remove the item from
        their actual cart through the Kroger app or website themselves.
        
        Use this tool only when:
        1. The user has already removed an item from their Kroger cart through the app/website
        2. You need to update the local tracking to reflect that change
        
        Args:
            product_id: The product ID to remove
            modality: Specific modality to remove (if None, removes all instances)
        
        Returns:
            Dictionary confirming the removal from local tracking
        """
        cart_data = _load_cart_data()
        current_cart = cart_data["current_cart"]
        original_count = len(current_cart)
        
        if modality:
            # Remove specific modality
            cart_data["current_cart"] = [
                item for item in current_cart 
                if not (item.get("product_id") == product_id and item.get("modality") == modality)
            ]
        else:
            # Remove all instances
            cart_data["current_cart"] = [
                item for item in current_cart 
                if item.get("product_id") != product_id
            ]
        
        items_removed = original_count - len(cart_data["current_cart"])
        
        if items_removed > 0:
            cart_data["last_updated"] = datetime.now().isoformat()
            _save_cart_data(cart_data)
            message = f"Removed {items_removed} items from local cart tracking"
        else:
            message = (
                f"No item with product_id {product_id}"
                + (f" and modality {modality}" if modality else "")
                + " is in the local cart tracking, so nothing was removed. See view_current_cart."
            )
        
        return {
            "success": True,
            "message": message,
            "items_removed": items_removed,
            "product_id": product_id,
            "modality": modality
        }

    @mcp.tool()
    @translate_errors
    async def clear_current_cart(ctx: Context = None) -> Dict[str, Any]:
        """
        Clear all items from the local cart tracking only.
        
        IMPORTANT: This tool CANNOT remove items from the actual Kroger cart in the app/website.
        It only clears our local tracking. The user must remove items from their actual cart
        through the Kroger app or website themselves.
        
        Use this tool only when:
        1. The user has already cleared their Kroger cart through the app/website
        2. You need to update the local tracking to reflect that change
        3. Or when the local tracking is out of sync with the actual cart
        
        Returns:
            Dictionary confirming the local cart tracking was cleared
        """
        cart_data = _load_cart_data()
        items_count = len(cart_data["current_cart"])
        
        cart_data["current_cart"] = []
        cart_data["last_updated"] = datetime.now().isoformat()
        _save_cart_data(cart_data)
        
        return {
            "success": True,
            "message": f"Cleared {items_count} items from local cart tracking",
            "items_cleared": items_count
        }

    @mcp.tool()
    @translate_errors
    async def mark_order_placed(
        order_notes: Optional[str] = None,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Mark the current cart as an order that has been placed and move it to order history.
        Use this after you've completed checkout on the Kroger website/app.
        
        Args:
            order_notes: Optional notes about the order
        
        Returns:
            Dictionary confirming the order was recorded
        """
        cart_data = _load_cart_data()
        current_cart = cart_data["current_cart"]
        
        if not current_cart:
            raise KrogerToolError(
                "empty_cart",
                "The local cart tracking is empty, so there is no order to record.",
                next_step=(
                    "Only items added with add_items_to_cart or bulk_add_to_cart are tracked. Items added "
                    "in the Kroger app or website are not."
                ),
            )
        
        # Create order record
        order_record = {
            "items": current_cart.copy(),
            "placed_at": datetime.now().isoformat(),
            "item_count": len(current_cart),
            "total_quantity": sum(item.get("quantity", 0) for item in current_cart),
            "notes": order_notes
        }
        
        # Load and update order history
        order_history = _load_order_history()
        order_history.append(order_record)
        _save_order_history(order_history)
        
        # Clear current cart
        cart_data["current_cart"] = []
        cart_data["last_updated"] = datetime.now().isoformat()
        try:
            _save_cart_data(cart_data)
        except KrogerToolError as e:
            raise KrogerToolError(
                "local_state_error",
                f"The order was added to the order history, but the local cart could not be cleared: {e.message}",
                next_step="Do not call mark_order_placed again. Fix the problem, then call clear_current_cart.",
                details=e.details,
            ) from e
        
        return {
            "success": True,
            "message": f"Marked order with {order_record['item_count']} items as placed",
            "order_id": len(order_history),  # Simple order ID based on history length
            "items_placed": order_record["item_count"],
            "total_quantity": order_record["total_quantity"],
            "placed_at": order_record["placed_at"]
        }

    @mcp.tool()
    @translate_errors
    async def view_order_history(
        limit: Annotated[int, Field(ge=1, le=50, description="Number of recent orders to show (1-50)")] = 10,
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        View the history of placed orders.
        
        Note: This tool can only see orders that were explicitly marked as placed via this MCP server.
        The Kroger API does not provide permission to query the actual order history from Kroger's systems.
        
        Args:
            limit: Number of recent orders to show (1-50)
        
        Returns:
            Dictionary containing order history
        """
        order_history = _load_order_history()
        
        # Sort by placed_at date (most recent first) and limit
        sorted_orders = sorted(order_history, key=lambda x: x.get("placed_at", ""), reverse=True)
        limited_orders = sorted_orders[:limit]
        
        # Calculate summary stats
        total_orders = len(order_history)
        total_items_all_time = sum(order.get("item_count", 0) for order in order_history)
        total_quantity_all_time = sum(order.get("total_quantity", 0) for order in order_history)
        
        return {
            "success": True,
            "orders": limited_orders,
            "showing": len(limited_orders),
            "summary": {
                "total_orders": total_orders,
                "total_items_all_time": total_items_all_time,
                "total_quantity_all_time": total_quantity_all_time
            }
        }
