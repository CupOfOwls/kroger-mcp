"""
Cart tracking and management functionality
"""
import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastmcp import Context
from pydantic import Field
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

    # ========== Shopping Context Tool ==========

    @mcp.tool()
    async def get_shopping_context(
        product_ids: Optional[List[str]] = Field(
            default=None,
            description="Product IDs to check. If None, returns all pantry/favorites context."
        ),
        pantry_threshold: int = Field(
            default=30,
            ge=0,
            le=100,
            description="Items above this pantry level (%) are suggested to skip"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get pantry levels, favorite status, and recommendations for products.

        IMPORTANT: Call this BEFORE adding items to cart to show user
        what they already have and may want to skip.

        This tool enables smart shopping by cross-referencing:
        - Pantry inventory levels (what you have)
        - Favorite lists (frequently purchased items)
        - Low inventory alerts (what you need)

        Args:
            product_ids: Optional list of product IDs to check
            pantry_threshold: Items above this level suggest skipping (default 30%)

        Returns:
            - pantry_items: Current levels for tracked items
            - favorite_matches: Which favorite lists contain these products
            - skip_suggestions: Items above pantry threshold (don't need to buy)
            - low_inventory_alerts: Items below 20% that should be ordered
        """
        try:
            from ..analytics.pantry import get_pantry_status
            from ..analytics.favorites import get_lists, get_list_items

            result = {
                "success": True,
                "pantry_items": [],
                "favorite_matches": [],
                "skip_suggestions": [],
                "low_inventory_alerts": [],
                "summary": {}
            }

            # Get all pantry items with current levels
            pantry_items = get_pantry_status(apply_depletion=True)

            # If specific product_ids provided, filter pantry items
            if product_ids:
                product_id_set = set(product_ids)
                filtered_pantry = [
                    item for item in pantry_items
                    if item['product_id'] in product_id_set
                ]
            else:
                filtered_pantry = pantry_items

            result["pantry_items"] = filtered_pantry

            # Categorize pantry items
            for item in filtered_pantry:
                level = item.get('level_percent', 0)
                if level >= pantry_threshold:
                    result["skip_suggestions"].append({
                        "product_id": item['product_id'],
                        "description": item.get('description'),
                        "level_percent": level,
                        "reason": f"Pantry at {level}% (above {pantry_threshold}% threshold)"
                    })
                elif level <= 20:
                    result["low_inventory_alerts"].append({
                        "product_id": item['product_id'],
                        "description": item.get('description'),
                        "level_percent": level,
                        "days_until_empty": item.get('days_until_empty'),
                        "urgency": "high" if level <= 10 else "medium"
                    })

            # Check which favorite lists contain these products
            all_lists = get_lists()
            for fav_list in all_lists:
                list_id = fav_list['id']  # get_lists returns 'id', not 'list_id'
                list_items = get_list_items(list_id, include_pantry_status=False)

                if list_items.get('success') and list_items.get('items'):
                    list_product_ids = {
                        item['product_id'] for item in list_items['items']
                    }

                    # Find matches
                    if product_ids:
                        matching_ids = list_product_ids.intersection(set(product_ids))
                    else:
                        matching_ids = list_product_ids

                    if matching_ids:
                        result["favorite_matches"].append({
                            "list_id": list_id,
                            "list_name": fav_list['name'],
                            "matching_products": list(matching_ids),
                            "match_count": len(matching_ids)
                        })

            # Build summary
            result["summary"] = {
                "pantry_items_checked": len(filtered_pantry),
                "items_to_skip": len(result["skip_suggestions"]),
                "low_inventory_count": len(result["low_inventory_alerts"]),
                "favorite_list_matches": len(result["favorite_matches"]),
                "pantry_threshold_used": pantry_threshold
            }

            # Add guidance message
            if result["skip_suggestions"]:
                result["guidance"] = (
                    f"You have {len(result['skip_suggestions'])} items that are "
                    f"well-stocked (>{pantry_threshold}%). Consider skipping these. "
                    f"Ask the user to confirm before adding to cart."
                )
            elif result["low_inventory_alerts"]:
                result["guidance"] = (
                    f"You have {len(result['low_inventory_alerts'])} items running low. "
                    "These should be prioritized for your next order."
                )
            else:
                result["guidance"] = "No pantry data available for these products."

            return result

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get shopping context: {str(e)}",
                "pantry_items": [],
                "favorite_matches": [],
                "skip_suggestions": [],
                "low_inventory_alerts": []
            }

    # ========== Cart Management Tools ==========

    @mcp.tool()
    async def add_items_to_cart(
        product_id: str,
        quantity: int = 1,
        modality: str = "PICKUP",
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add a single item to the user's Kroger cart and track it locally.

        IMPORTANT - CONFIRMATION WORKFLOW:
        Before calling this tool, the client SHOULD:
        1. Call get_shopping_context() to check pantry levels
        2. Show user if they already have this item (pantry status)
        3. Ask for confirmation: "Add [item] to cart?"
        4. Confirm modality preference (PICKUP/DELIVERY)

        After calling this tool:
        - Show what was added
        - Remind user to review cart in Kroger app before checkout

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
        preview_only: bool = Field(
            default=False,
            description="If True, returns preview without adding to cart"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add multiple items to the user's Kroger cart in a single operation.

        CONFIRMATION WORKFLOW (2-step process):
        Step 1: Call with preview_only=True
            - Returns what WOULD be added without modifying cart
            - Includes pantry context for each item
            - DOES NOT add anything to cart

        Step 2: Call with preview_only=False (default) after user approval
            - Actually adds items to cart
            - Returns confirmation summary

        The client SHOULD show the preview to user and get explicit
        confirmation before calling with preview_only=False.

        Args:
            items: List of items to add. Each item should have:
                   - product_id: The product ID or UPC
                   - quantity: Quantity to add (default: 1)
                   - modality: PICKUP or DELIVERY (default: PICKUP)
            preview_only: If True, returns preview without modifying cart

        Returns:
            Dictionary with preview (if preview_only) or confirmation
        """
        try:
            # Build item list with details
            formatted_items = []
            for item in items:
                formatted_items.append({
                    "product_id": item["product_id"],
                    "quantity": item.get("quantity", 1),
                    "modality": item.get("modality", "PICKUP"),
                    "description": item.get("description")
                })

            # Preview mode - return what would be added with pantry context
            if preview_only:
                # Get pantry context for these items
                product_ids = [item["product_id"] for item in formatted_items]

                pantry_context = {}
                try:
                    from ..analytics.pantry import get_pantry_item
                    for pid in product_ids:
                        pantry_item = get_pantry_item(pid)
                        if pantry_item:
                            pantry_context[pid] = {
                                "level_percent": pantry_item.get("level_percent", 0),
                                "status": pantry_item.get("status"),
                                "days_until_empty": pantry_item.get("days_until_empty")
                            }
                except Exception:
                    pass  # Pantry check is optional

                # Build preview with recommendations
                preview_items = []
                skip_suggestions = []
                for item in formatted_items:
                    pid = item["product_id"]
                    pantry = pantry_context.get(pid, {})
                    level = pantry.get("level_percent")

                    preview_item = {
                        **item,
                        "pantry_level": level,
                        "pantry_status": pantry.get("status")
                    }

                    if level is not None and level >= 30:
                        preview_item["recommendation"] = "SKIP"
                        preview_item["reason"] = f"Pantry at {level}%"
                        skip_suggestions.append(preview_item)
                    else:
                        preview_item["recommendation"] = "ADD"

                    preview_items.append(preview_item)

                return {
                    "success": True,
                    "preview_only": True,
                    "confirmation_required": True,
                    "items": preview_items,
                    "summary": {
                        "total_items": len(preview_items),
                        "items_to_add": len([i for i in preview_items if i["recommendation"] == "ADD"]),
                        "items_to_skip": len(skip_suggestions)
                    },
                    "skip_suggestions": skip_suggestions,
                    "next_step": "Review items and call again with preview_only=False to add to cart"
                }

            # Actual add mode
            if ctx:
                await ctx.info(f"Adding {len(items)} items to cart in bulk")

            client = get_authenticated_client()

            # Format items for the API
            cart_items = []
            for item in formatted_items:
                cart_item = {
                    "upc": item["product_id"],
                    "quantity": item["quantity"],
                    "modality": item["modality"]
                }
                cart_items.append(cart_item)

            if ctx:
                await ctx.info(f"Calling Kroger API to add {len(cart_items)} items")

            # Add all items to the actual Kroger cart
            client.cart.add_to_cart(cart_items)

            if ctx:
                await ctx.info("Successfully added all items to Kroger cart")

            # Add all items to local cart tracking
            for item in formatted_items:
                _add_item_to_local_cart(
                    item["product_id"],
                    item["quantity"],
                    item["modality"]
                )

            if ctx:
                await ctx.info("All items added to local cart tracking")

            return {
                "success": True,
                "message": f"Successfully added {len(items)} items to cart",
                "items_added": len(items),
                "items": formatted_items,
                "timestamp": datetime.now().isoformat(),
                "reminder": "Review your cart in the Kroger app before checkout"
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
