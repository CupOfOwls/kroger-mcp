"""
Cart tracking and management functionality
"""
import json
import os
from datetime import datetime
from typing import Dict, Any, List

from fastmcp import Context
from .shared import get_authenticated_client


# Cart storage file
CART_FILE = "kroger_cart.json"
ORDER_HISTORY_FILE = "kroger_order_history.json"


def _load_cart_data() -> Dict[str, Any]:
    """Load cart data from file"""
    try:
        if os.path.exists(CART_FILE):
            with open(CART_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"current_cart": [], "last_updated": None, "preferred_location_id": None}


def _save_cart_data(cart_data: Dict[str, Any]) -> None:
    """Save cart data to file"""
    try:
        with open(CART_FILE, 'w') as f:
            json.dump(cart_data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save cart data: {e}")


def _load_order_history() -> List[Dict[str, Any]]:
    """Load order history from file"""
    try:
        if os.path.exists(ORDER_HISTORY_FILE):
            with open(ORDER_HISTORY_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _save_order_history(history: List[Dict[str, Any]]) -> None:
    """Save order history to file"""
    try:
        with open(ORDER_HISTORY_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save order history: {e}")


def _add_item_to_local_cart(product_id: str, quantity: int, modality: str, product_details: Dict[str, Any] = None) -> None:
    """Add an item to the local cart tracking and analytics database"""
    cart_data = _load_cart_data()
    current_cart = cart_data.get("current_cart", [])

    # Check if item already exists in cart
    existing_item = None
    for item in current_cart:
        if item.get("product_id") == product_id and item.get("modality") == modality:
            existing_item = item
            break

    if existing_item:
        # Update existing item quantity
        existing_item["quantity"] = existing_item.get("quantity", 0) + quantity
        existing_item["last_updated"] = datetime.now().isoformat()
    else:
        # Add new item
        new_item = {
            "product_id": product_id,
            "quantity": quantity,
            "modality": modality,
            "added_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat()
        }

        # Add product details if provided
        if product_details:
            new_item.update(product_details)

        current_cart.append(new_item)

    cart_data["current_cart"] = current_cart
    cart_data["last_updated"] = datetime.now().isoformat()
    _save_cart_data(cart_data)

    # Record in analytics database
    try:
        from ..analytics.purchase_tracker import record_cart_add
        record_cart_add(product_id, quantity, modality, product_details)
    except Exception as e:
        # Don't fail cart operations if analytics fails
        print(f"Warning: Could not record analytics: {e}")


def register_tools(mcp):
    """Register cart-related tools with the FastMCP server"""
    
    @mcp.tool()
    async def add_items_to_cart(
        product_id: str,
        quantity: int = 1,
        modality: str = "PICKUP",
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
        try:
            if ctx:
                await ctx.info(f"Adding {quantity}x {product_id} to cart with {modality} modality")
            
            # Get authenticated client
            client = get_authenticated_client()
            
            # Format the item for the API
            cart_item = {
                "upc": product_id,
                "quantity": quantity,
                "modality": modality
            }
            
            if ctx:
                await ctx.info(f"Calling Kroger API to add item: {cart_item}")
            
            # Add the item to the actual Kroger cart
            # Note: add_to_cart returns None on success, raises exception on failure
            client.cart.add_to_cart([cart_item])
            
            if ctx:
                await ctx.info("Successfully added item to Kroger cart")
            
            # Add to local cart tracking
            _add_item_to_local_cart(product_id, quantity, modality)
            
            if ctx:
                await ctx.info("Item added to local cart tracking")
            
            return {
                "success": True,
                "message": f"Successfully added {quantity}x {product_id} to cart",
                "product_id": product_id,
                "quantity": quantity,
                "modality": modality,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Failed to add item to cart: {str(e)}")
            
            # Provide helpful error message for authentication issues
            error_message = str(e)
            if "401" in error_message or "Unauthorized" in error_message:
                return {
                    "success": False,
                    "error": "Authentication failed. Please run force_reauthenticate and try again.",
                    "details": error_message
                }
            elif "400" in error_message or "Bad Request" in error_message:
                return {
                    "success": False,
                    "error": "Invalid request. Please check the product ID and try again.",
                    "details": error_message
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to add item to cart: {error_message}",
                    "product_id": product_id,
                    "quantity": quantity,
                    "modality": modality
                }

    @mcp.tool()
    async def bulk_add_to_cart(
        items: List[Dict[str, Any]],
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
        try:
            if ctx:
                await ctx.info(f"Adding {len(items)} items to cart in bulk")
            
            client = get_authenticated_client()
            
            # Format items for the API
            cart_items = []
            for item in items:
                cart_item = {
                    "upc": item["product_id"],
                    "quantity": item.get("quantity", 1),
                    "modality": item.get("modality", "PICKUP")
                }
                cart_items.append(cart_item)
            
            if ctx:
                await ctx.info(f"Calling Kroger API to add {len(cart_items)} items")
            
            # Add all items to the actual Kroger cart
            client.cart.add_to_cart(cart_items)
            
            if ctx:
                await ctx.info("Successfully added all items to Kroger cart")
            
            # Add all items to local cart tracking
            for item in items:
                _add_item_to_local_cart(
                    item["product_id"],
                    item.get("quantity", 1),
                    item.get("modality", "PICKUP")
                )
            
            if ctx:
                await ctx.info("All items added to local cart tracking")
            
            return {
                "success": True,
                "message": f"Successfully added {len(items)} items to cart",
                "items_added": len(items),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            if ctx:
                await ctx.error(f"Failed to bulk add items to cart: {str(e)}")
            
            error_message = str(e)
            if "401" in error_message or "Unauthorized" in error_message:
                return {
                    "success": False,
                    "error": "Authentication failed. Please run force_reauthenticate and try again.",
                    "details": error_message
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to add items to cart: {error_message}",
                    "items_attempted": len(items)
                }

    @mcp.tool()
    async def view_current_cart(ctx: Context = None) -> Dict[str, Any]:
        """
        View the current cart contents tracked locally.
        
        Note: This tool can only see items that were added via this MCP server.
        The Kroger API does not provide permission to query the actual user cart contents.
        
        Returns:
            Dictionary containing current cart items and summary
        """
        try:
            cart_data = _load_cart_data()
            current_cart = cart_data.get("current_cart", [])
            
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
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to view cart: {str(e)}"
            }

    @mcp.tool()
    async def remove_from_cart(
        product_id: str,
        modality: str = None,
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
        try:
            cart_data = _load_cart_data()
            current_cart = cart_data.get("current_cart", [])
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
            
            return {
                "success": True,
                "message": f"Removed {items_removed} items from local cart tracking",
                "items_removed": items_removed,
                "product_id": product_id,
                "modality": modality
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to remove from cart: {str(e)}"
            }

    @mcp.tool()
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
        try:
            cart_data = _load_cart_data()
            items_count = len(cart_data.get("current_cart", []))
            
            cart_data["current_cart"] = []
            cart_data["last_updated"] = datetime.now().isoformat()
            _save_cart_data(cart_data)
            
            return {
                "success": True,
                "message": f"Cleared {items_count} items from local cart tracking",
                "items_cleared": items_count
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to clear cart: {str(e)}"
            }

    @mcp.tool()
    async def mark_order_placed(
        order_notes: str = None,
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
        try:
            cart_data = _load_cart_data()
            current_cart = cart_data.get("current_cart", [])
            
            if not current_cart:
                return {
                    "success": False,
                    "error": "No items in current cart to mark as placed"
                }
            
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

            # Record in analytics database and update statistics
            analytics_order_id = None
            try:
                from ..analytics.purchase_tracker import record_order
                from ..analytics.statistics import update_all_product_stats

                analytics_order_id = record_order(current_cart, order_notes)

                # Update statistics for all products in the order
                product_ids = [item.get("product_id") for item in current_cart]
                update_all_product_stats(product_ids)
            except Exception as e:
                # Don't fail order operations if analytics fails
                print(f"Warning: Could not record analytics: {e}")

            # Clear current cart
            cart_data["current_cart"] = []
            cart_data["last_updated"] = datetime.now().isoformat()
            _save_cart_data(cart_data)

            return {
                "success": True,
                "message": f"Marked order with {order_record['item_count']} items as placed",
                "order_id": len(order_history),  # Simple order ID based on history length
                "analytics_order_id": analytics_order_id,
                "items_placed": order_record["item_count"],
                "total_quantity": order_record["total_quantity"],
                "placed_at": order_record["placed_at"]
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to mark order as placed: {str(e)}"
            }

    @mcp.tool()
    async def view_order_history(
        limit: int = 10,
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
        try:
            # Ensure limit is within bounds
            limit = max(1, min(50, limit))
            
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
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to view order history: {str(e)}"
            }
