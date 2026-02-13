"""
Cart tracking and management functionality
"""
import json
import os
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastmcp import Context
from pydantic import Field
from .shared import get_authenticated_client, get_preferred_location_id
from ..analytics.safety import (
    get_all_safe_product_ids,
    get_all_blocked_product_ids,
    get_disabled_ingredients,
    is_filtering_enabled,
)
from ..analytics.ingredients import check_product_safety
from ..analytics.deals import record_price_observation, calculate_cart_savings


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

    # Record price observation if we have pricing data
    if product_details:
        try:
            pricing = product_details.get("pricing", {})
            location_id = get_preferred_location_id()
            if pricing and location_id:
                record_price_observation(
                    product_id=product_id,
                    regular_price=pricing.get("regular_price"),
                    sale_price=pricing.get("sale_price") or pricing.get("price"),
                    location_id=location_id,
                    source="cart_add"
                )
        except Exception:
            pass  # Don't fail cart operations if price recording fails

    # Auto-add to pantry for inventory tracking
    try:
        from ..analytics.pantry import add_to_pantry
        add_to_pantry(product_id=product_id)
    except Exception:
        pass  # Don't fail cart operations if pantry add fails


def _get_session_id(ctx: Context) -> str:
    """
    Extract session ID from MCP context.

    Falls back to 'default' if no context available (testing, etc.)
    """
    if ctx and hasattr(ctx, 'session_id'):
        return str(ctx.session_id)
    # Fallback for testing or when context unavailable
    return 'default'


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
    async def add_to_cart(
        items: str | List[Dict[str, Any]] = Field(
            description=(
                "Product ID (string) for single item, or list of item dicts for batch. "
                "Each dict: {product_id, quantity?, modality?, description?}"
            )
        ),
        quantity: int = Field(
            default=1,
            ge=1,
            le=99,
            description="Quantity (only used when items is a single product ID string)"
        ),
        modality: str = Field(
            default="PICKUP",
            description="PICKUP or DELIVERY (only used when items is a single product ID string)"
        ),
        preview_only: bool = Field(
            default=False,
            description="If True, returns preview without adding to cart (batch mode)"
        ),
        confirm_unsafe: bool = Field(
            default=False,
            description="Set to True to override safety warnings and add flagged products"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add items to the user's Kroger cart. Supports single or batch operations.

        ⚠️ PREREQUISITE: You MUST call get_pantry_attention() at least once per session
        before using this tool. This ensures you review what items need attention
        (expiring, low inventory, overdue) before adding new items to your cart.

        If you haven't called get_pantry_attention() yet this session, this operation
        will be blocked with an error. Simply call get_pantry_attention() first, then
        you can freely add items to cart for the rest of the session.

        SINGLE MODE (items is a string):
            add_to_cart(items="0001111041700", quantity=2, modality="PICKUP")

        BATCH MODE (items is a list):
            add_to_cart(items=[
                {"product_id": "0001111041700", "quantity": 2},
                {"product_id": "0001111089476", "quantity": 1, "modality": "DELIVERY"}
            ])

        AUTOMATIC PANTRY TRACKING:
        When items are added to cart, they are automatically added to pantry
        inventory tracking (if not already tracked). This enables:
        - Automatic consumption rate learning based on purchase intervals
        - Low inventory alerts when items run low
        - Smart reorder suggestions based on actual usage patterns

        The system tracks depletion rates by analyzing your purchase frequency.
        View pantry status with get_pantry() or get_shopping_context().

        CONFIRMATION WORKFLOW (recommended for batch):
        Step 1: Call with preview_only=True
            - Returns what WOULD be added with pantry context
            - DOES NOT add anything to cart

        Step 2: Call with preview_only=False after user approval
            - Actually adds items to cart

        SAFETY CHECKS:
        - Products are checked for bad ingredients (nitrites, HFCS, etc.)
        - Safe-listed products bypass all checks
        - Blocked products require double confirmation
        - If flagged, returns warning with requires_confirmation: true
        - Set confirm_unsafe=True to add flagged products anyway

        Args:
            items: Product ID string OR list of item dicts
            quantity: Quantity for single mode (default: 1)
            modality: Fulfillment method for single mode - PICKUP or DELIVERY
            preview_only: If True, returns preview without modifying cart
            confirm_unsafe: Set to True to override safety warnings

        Returns:
            Dictionary confirming item(s) added or preview
        """
        from ..session_state import get_session_manager

        # Get session ID
        session_id = _get_session_id(ctx)

        # HARD REQUIREMENT CHECK
        session_manager = get_session_manager()
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
                    "required_before": ["add_to_cart", "add items to cart"]
                }
            }

        try:
            # Normalize input to list of item dicts
            if isinstance(items, str):
                # Single mode: items is a product_id string
                is_batch = False
                formatted_items = [{
                    "product_id": items,
                    "quantity": quantity,
                    "modality": modality,
                    "description": None
                }]
            else:
                # Batch mode: items is a list of dicts
                is_batch = True
                if len(items) > 50:
                    return {
                        "success": False,
                        "error": "Maximum 50 items per batch request"
                    }
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
                        "items_to_add": len(
                            [i for i in preview_items if i["recommendation"] == "ADD"]
                        ),
                        "items_to_skip": len(skip_suggestions)
                    },
                    "skip_suggestions": skip_suggestions,
                    "next_step": "Review and call again with preview_only=False to add"
                }

            # Safety check - check products for bad ingredients
            filtering_enabled = is_filtering_enabled()
            safety_warnings = []
            blocked_items = []

            if filtering_enabled and not confirm_unsafe:
                # Pre-load safety data for efficient lookups
                safe_ids = get_all_safe_product_ids()
                blocked_ids_set = get_all_blocked_product_ids()
                disabled_ingredients = get_disabled_ingredients()

                for item in formatted_items:
                    product_id = item["product_id"]
                    description = item.get("description") or ""

                    # Safe-listed products bypass all checks
                    if product_id in safe_ids:
                        continue

                    # Check blocked list
                    if product_id in blocked_ids_set:
                        blocked_items.append({
                            "product_id": product_id,
                            "description": description,
                            "reason": "Product is on your blocked list"
                        })
                        continue

                    # Check for bad ingredients (only if description available)
                    if description:
                        safety_result = check_product_safety(
                            description=description,
                            disabled_ingredients=disabled_ingredients,
                        )

                        if safety_result.has_concerns:
                            flagged = []
                            for match in safety_result.matches:
                                flagged.append({
                                    "ingredient": match.ingredient_name,
                                    "severity": match.severity.value,
                                    "reason": match.reason,
                                    "matched_text": match.matched_text
                                })

                            safety_warnings.append({
                                "product_id": product_id,
                                "description": description,
                                "severity": safety_result.highest_severity.value,
                                "flagged_ingredients": flagged
                            })

                # If we have safety concerns and user hasn't confirmed
                if blocked_items or safety_warnings:
                    all_concerns = blocked_items + safety_warnings
                    return {
                        "success": False,
                        "requires_confirmation": True,
                        "message": (
                            "Some products have safety concerns. "
                            "Set confirm_unsafe=True to add anyway."
                        ),
                        "blocked_items": blocked_items,
                        "safety_warnings": safety_warnings,
                        "total_flagged": len(all_concerns),
                        "items_requested": len(formatted_items),
                        "next_step": (
                            "Review the flagged ingredients and either: "
                            "(1) call again with confirm_unsafe=True to add anyway, "
                            "(2) remove flagged items from your request, or "
                            "(3) use approve_product() to safe-list products you trust"
                        )
                    }

            # Actual add mode
            if ctx:
                await ctx.info(f"Adding {len(formatted_items)} item(s) to cart")

            client = get_authenticated_client()

            # Format items for the Kroger API
            cart_items = []
            for item in formatted_items:
                cart_items.append({
                    "upc": item["product_id"],
                    "quantity": item["quantity"],
                    "modality": item["modality"]
                })

            if ctx:
                await ctx.info(f"Calling Kroger API to add {len(cart_items)} item(s)")

            # Add to actual Kroger cart
            client.cart.add_to_cart(cart_items)

            if ctx:
                await ctx.info("Successfully added item(s) to Kroger cart")

            # Add to local cart tracking
            for item in formatted_items:
                _add_item_to_local_cart(
                    item["product_id"],
                    item["quantity"],
                    item["modality"]
                )

            if ctx:
                await ctx.info("Item(s) added to local cart tracking")

            # Return format differs for single vs batch
            if is_batch:
                return {
                    "success": True,
                    "message": f"Successfully added {len(formatted_items)} items to cart",
                    "items_added": len(formatted_items),
                    "items": formatted_items,
                    "timestamp": datetime.now().isoformat(),
                    "reminder": "Review your cart in the Kroger app before checkout"
                }
            else:
                # Single item - return flat response for backwards compatibility
                item = formatted_items[0]
                return {
                    "success": True,
                    "message": f"Successfully added {item['quantity']}x {item['product_id']} to cart",
                    "product_id": item["product_id"],
                    "quantity": item["quantity"],
                    "modality": item["modality"],
                    "timestamp": datetime.now().isoformat()
                }

        except Exception as e:
            if ctx:
                await ctx.error(f"Failed to add item(s) to cart: {str(e)}")

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
                    "error": "Invalid request. Please check the product ID(s) and try again.",
                    "details": error_message
                }
            else:
                return {
                    "success": False,
                    "error": f"Failed to add item(s) to cart: {error_message}",
                    "items_attempted": len(formatted_items) if 'formatted_items' in locals() else 1
                }

    @mcp.tool()
    async def view_current_cart(ctx: Context = None) -> Dict[str, Any]:
        """
        View the current cart contents tracked locally.

        Note: This tool can only see items that were added via this MCP server.
        The Kroger API does not provide permission to query the actual user cart contents.

        Returns:
            Dictionary containing current cart items, summary, and savings info
        """
        try:
            cart_data = _load_cart_data()
            current_cart = cart_data.get("current_cart", [])

            # Calculate summary
            total_quantity = sum(item.get("quantity", 0) for item in current_cart)
            pickup_items = [item for item in current_cart if item.get("modality") == "PICKUP"]
            delivery_items = [item for item in current_cart if item.get("modality") == "DELIVERY"]

            # Calculate savings
            savings_summary = None
            try:
                savings_summary = calculate_cart_savings(current_cart)
            except Exception:
                pass  # Don't fail if savings calculation fails

            result = {
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

            if savings_summary:
                result["savings_summary"] = savings_summary

            return result
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

        AUTOMATIC PANTRY RESTOCKING:
        When an order is marked as placed, all items that are tracked in the
        pantry system are automatically restocked to 100% level. This:
        - Resets inventory levels for newly purchased items
        - Starts a new depletion cycle for consumption tracking
        - Updates predicted reorder dates based on actual purchase timing
        - Improves future predictions by learning from actual intervals

        Only items already in pantry tracking are restocked. New items are
        added when first added to cart.

        Args:
            order_notes: Optional notes about the order

        Returns:
            Dictionary confirming the order was recorded and pantry restocking status
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
