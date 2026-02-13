"""
Shopping list management tools.

Provides intermediate storage between recipes and cart:
- Add recipes to shopping list (auto-scaled to household servings)
- Consolidate quantities from multiple recipes
- Review before adding to cart
- Session requirement: Must call get_pantry_attention() first
"""

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import Field


# Shopping list storage file
SHOPPING_LIST_FILE = "kroger_shopping_list.json"


def _load_shopping_list() -> Dict[str, Any]:
    """Load shopping list from JSON file."""
    try:
        if os.path.exists(SHOPPING_LIST_FILE):
            with open(SHOPPING_LIST_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"items": [], "last_updated": None}


def _save_shopping_list(data: Dict[str, Any]) -> None:
    """Save shopping list to JSON file."""
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(SHOPPING_LIST_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save shopping list: {e}")


def _generate_list_item_id() -> str:
    """Generate unique ID for shopping list item."""
    return f"list_item_{str(uuid.uuid4())[:8]}"


def _consolidate_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Consolidate shopping list items by product_id.

    Items with the same product_id have their quantities summed
    and sources combined.
    """
    consolidated = {}

    for item in items:
        product_id = item.get("product_id")
        if not product_id:
            # Items without product_id stay separate
            item_id = item.get("id", _generate_list_item_id())
            consolidated[item_id] = item
            continue

        if product_id in consolidated:
            # Consolidate quantities
            existing = consolidated[product_id]
            existing["quantity"] = existing.get("quantity", 0) + item.get("quantity", 0)

            # Merge sources
            existing_sources = existing.get("sources", [])
            new_sources = item.get("sources", [])
            existing["sources"] = existing_sources + new_sources

            # Update timestamp
            existing["last_updated"] = datetime.now().isoformat()
        else:
            # First occurrence of this product
            consolidated[product_id] = item.copy()

    return list(consolidated.values())


def _get_session_id(ctx: Context) -> str:
    """
    Extract session ID from MCP context.

    Falls back to 'default' if no context available (testing, etc.)
    """
    if ctx and hasattr(ctx, 'session_id'):
        return str(ctx.session_id)
    return 'default'


def _check_attention_requirement(ctx: Context) -> Optional[Dict[str, Any]]:
    """
    Check if get_pantry_attention was called this session.

    Returns error dict if not called, None if requirement met.
    """
    from ..session_state import get_session_manager

    session_id = _get_session_id(ctx)
    session_manager = get_session_manager()

    if not session_manager.was_tool_called(session_id, "get_pantry_attention"):
        return {
            "success": False,
            "error": "Session requirement not met",
            "error_code": "ATTENTION_REQUIRED",
            "message": (
                "You must call get_pantry_attention() before adding to shopping list. "
                "This ensures you review expiring items, low inventory, and what you "
                "already have before building your shopping list."
            ),
            "required_action": "Call get_pantry_attention() first"
        }

    return None  # Requirement met


def _ingredient_matches(ingredient_name: str, skip_items: List[str]) -> bool:
    """Check if ingredient matches any skip item (case-insensitive, partial)."""
    if not skip_items:
        return False
    ingredient_lower = ingredient_name.lower()
    for skip in skip_items:
        skip_lower = skip.lower()
        if skip_lower in ingredient_lower or ingredient_lower in skip_lower:
            return True
    return False


def register_tools(mcp):
    """Register shopping list tools with the FastMCP server."""

    @mcp.tool()
    async def add_recipe_to_shopping_list(
        recipe_id: str = Field(description="Recipe ID to add"),
        servings: Optional[int] = Field(
            default=None,
            ge=1,
            le=20,
            description="Override servings (None = use household default)"
        ),
        skip_items: List[str] = Field(
            default=[],
            description="Ingredient names to skip (items you already have)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add recipe ingredients to shopping list (auto-scaled to household default).

        ⚠️ PREREQUISITE: You MUST call get_pantry_attention() at least once per session
        before using this tool. This ensures you review what items need attention
        before building your shopping list.

        Args:
            recipe_id: Recipe to add
            servings: Override household default (None = use default)
            skip_items: Ingredient names to skip

        Returns:
            Items added to shopping list with auto-scaling info
        """
        # Check session requirement
        requirement_error = _check_attention_requirement(ctx)
        if requirement_error:
            return requirement_error

        try:
            from .recipe_tools import _find_recipe
            from .shared import get_default_servings

            # Find recipe
            recipe = _find_recipe(recipe_id)
            if not recipe:
                return {
                    "success": False,
                    "error": f"Recipe '{recipe_id}' not found"
                }

            # Determine servings to use
            household_default = get_default_servings()
            if servings is None:
                servings = household_default
                using_default = True
            else:
                using_default = False

            recipe_base_servings = recipe.get("servings", 4)
            scale_factor = servings / recipe_base_servings

            # Get pantry context
            pantry_context = {}
            try:
                from ..analytics.pantry import get_pantry_status
                pantry_items = get_pantry_status(apply_depletion=True)
                for item in pantry_items:
                    pantry_context[item['product_id']] = {
                        "level_percent": item.get("level_percent", 0),
                        "status": item.get("status")
                    }
            except Exception:
                pass

            # Load current shopping list
            data = _load_shopping_list()
            items_added = 0
            items_skipped = 0
            skip_reasons = {"pantry_threshold": [], "user_specified": []}

            # Process ingredients
            for ing in recipe.get("ingredients", []):
                name = ing.get("name", "Unknown")
                quantity = ing.get("quantity", 1)
                unit = ing.get("unit", "")
                product_id = ing.get("product_id")

                # Calculate scaled quantity
                scaled_quantity = round(quantity * scale_factor, 2) if quantity else 1

                # Check if should skip
                user_skip = _ingredient_matches(name, skip_items)
                if user_skip:
                    items_skipped += 1
                    skip_reasons["user_specified"].append(name)
                    continue

                # Check pantry
                pantry = pantry_context.get(product_id, {}) if product_id else {}
                pantry_level = pantry.get("level_percent")
                if pantry_level is not None and pantry_level >= 30:
                    items_skipped += 1
                    skip_reasons["pantry_threshold"].append(f"{name} (pantry at {pantry_level}%)")
                    continue

                # Add to shopping list
                list_item = {
                    "id": _generate_list_item_id(),
                    "product_id": product_id,
                    "ingredient_name": name,
                    "quantity": scaled_quantity,
                    "unit": unit,
                    "sources": [
                        {
                            "recipe_id": recipe_id,
                            "recipe_name": recipe.get("name"),
                            "servings_used": servings,
                            "original_quantity": quantity,
                            "scaled_quantity": scaled_quantity
                        }
                    ],
                    "added_at": datetime.now().isoformat(),
                    "notes": None
                }

                data["items"].append(list_item)
                items_added += 1

            # Consolidate items
            data["items"] = _consolidate_items(data["items"])
            _save_shopping_list(data)

            if ctx:
                await ctx.info(f"Added {items_added} ingredients from '{recipe.get('name')}' to shopping list")

            return {
                "success": True,
                "recipe_id": recipe_id,
                "recipe_name": recipe.get("name"),
                "recipe_base_servings": recipe_base_servings,
                "servings_used": servings,
                "household_default": household_default,
                "using_household_default": using_default,
                "scale_factor": scale_factor,
                "items_added": items_added,
                "items_skipped": items_skipped,
                "skip_reasons": skip_reasons,
                "shopping_list_total_items": len(data["items"]),
                "message": f"Added {items_added} ingredients from '{recipe.get('name')}' (scaled to {servings} servings)"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add recipe to shopping list: {str(e)}"
            }

    @mcp.tool()
    async def get_shopping_list(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        View current shopping list with consolidated quantities.

        Returns:
            Shopping list items with quantities and source information
        """
        try:
            from .shared import get_default_servings

            data = _load_shopping_list()
            items = data.get("items", [])

            # Extract recipes included
            recipes_map = {}
            for item in items:
                for source in item.get("sources", []):
                    recipe_id = source.get("recipe_id")
                    if recipe_id and recipe_id not in recipes_map:
                        recipes_map[recipe_id] = {
                            "recipe_id": recipe_id,
                            "recipe_name": source.get("recipe_name"),
                            "servings": source.get("servings_used")
                        }

            recipes_included = list(recipes_map.values())
            total_servings = sum(r["servings"] for r in recipes_included)

            return {
                "success": True,
                "items": items,
                "total_items": len(items),
                "recipes_included": recipes_included,
                "servings_summary": {
                    "household_default": get_default_servings(),
                    "total_servings_planned": total_servings,
                    "total_meals": len(recipes_included)
                }
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get shopping list: {str(e)}"
            }

    @mcp.tool()
    async def remove_from_shopping_list(
        item_id: Optional[str] = Field(
            default=None,
            description="Item ID to remove (single mode)"
        ),
        item_ids: Optional[List[str]] = Field(
            default=None,
            description="List of item IDs to remove (batch mode)"
        ),
        clear_all: bool = Field(
            default=False,
            description="Clear entire shopping list"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Remove items from shopping list.

        SINGLE MODE: remove_from_shopping_list(item_id="list_item_abc")
        BATCH MODE: remove_from_shopping_list(item_ids=["list_item_abc", "list_item_def"])
        CLEAR ALL: remove_from_shopping_list(clear_all=True)
        """
        try:
            data = _load_shopping_list()

            if clear_all:
                item_count = len(data["items"])
                data["items"] = []
                _save_shopping_list(data)
                return {
                    "success": True,
                    "message": f"Cleared {item_count} items from shopping list",
                    "items_removed": item_count
                }

            if item_id:
                ids_to_remove = [item_id]
            elif item_ids:
                ids_to_remove = item_ids
            else:
                return {
                    "success": False,
                    "error": "Provide item_id, item_ids, or set clear_all=True"
                }

            original_count = len(data["items"])
            data["items"] = [
                item for item in data["items"]
                if item.get("id") not in ids_to_remove
            ]
            removed_count = original_count - len(data["items"])

            _save_shopping_list(data)

            return {
                "success": True,
                "items_removed": removed_count,
                "remaining_items": len(data["items"]),
                "message": f"Removed {removed_count} item(s) from shopping list"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to remove from shopping list: {str(e)}"
            }

    @mcp.tool()
    async def update_shopping_list_item(
        item_id: str = Field(description="Item ID to update"),
        quantity: Optional[int] = Field(
            default=None,
            ge=1,
            description="New quantity"
        ),
        notes: Optional[str] = Field(
            default=None,
            description="Notes for this item"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Update quantity or notes for a shopping list item.
        """
        try:
            data = _load_shopping_list()
            found = False

            for item in data["items"]:
                if item.get("id") == item_id:
                    found = True
                    if quantity is not None:
                        item["quantity"] = quantity
                    if notes is not None:
                        item["notes"] = notes
                    item["last_updated"] = datetime.now().isoformat()
                    break

            if not found:
                return {
                    "success": False,
                    "error": f"Item '{item_id}' not found in shopping list"
                }

            _save_shopping_list(data)

            return {
                "success": True,
                "message": f"Updated item '{item_id}'",
                "item_id": item_id
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to update shopping list item: {str(e)}"
            }

    @mcp.tool()
    async def add_shopping_list_to_cart(
        modality: str = Field(
            default="PICKUP",
            description="Fulfillment method: PICKUP or DELIVERY"
        ),
        confirm: bool = Field(
            default=False,
            description="Set to True to actually add items (after preview)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Transfer shopping list items to Kroger cart.

        ⚠️ PREREQUISITE: You MUST call get_pantry_attention() at least once per session
        before using this tool.

        WORKFLOW (2-step):
        Step 1: Call with confirm=False (preview)
            - Shows what will be added to cart
            - Cross-references with pantry
            - DOES NOT modify cart or shopping list

        Step 2: Call with confirm=True after user approval
            - Adds items to Kroger cart
            - Clears shopping list
            - Returns summary

        Args:
            modality: PICKUP or DELIVERY
            confirm: False=preview, True=execute

        Returns:
            Preview or execution summary
        """
        # Check session requirement
        requirement_error = _check_attention_requirement(ctx)
        if requirement_error:
            return requirement_error

        try:
            from .shared import get_authenticated_client
            from .cart_tools import _add_item_to_local_cart

            data = _load_shopping_list()
            items = data.get("items", [])

            if not items:
                return {
                    "success": True,
                    "message": "Shopping list is empty - nothing to add",
                    "items_added": 0
                }

            # Get pantry context for re-check
            pantry_context = {}
            try:
                from ..analytics.pantry import get_pantry_status
                pantry_items = get_pantry_status(apply_depletion=True)
                for item in pantry_items:
                    pantry_context[item['product_id']] = {
                        "level_percent": item.get("level_percent", 0)
                    }
            except Exception:
                pass

            # Build preview
            items_to_add = []
            items_to_skip = []

            for item in items:
                product_id = item.get("product_id")
                if not product_id:
                    items_to_skip.append({
                        "ingredient_name": item.get("ingredient_name"),
                        "reason": "No product_id (search for product first)"
                    })
                    continue

                # Check pantry again
                pantry = pantry_context.get(product_id, {})
                pantry_level = pantry.get("level_percent")

                if pantry_level is not None and pantry_level >= 30:
                    items_to_skip.append({
                        "product_id": product_id,
                        "ingredient_name": item.get("ingredient_name"),
                        "reason": f"Pantry at {pantry_level}%",
                        "action": "SKIP"
                    })
                else:
                    from_recipes = [s.get("recipe_name") for s in item.get("sources", [])]
                    items_to_add.append({
                        "product_id": product_id,
                        "ingredient_name": item.get("ingredient_name"),
                        "quantity": int(item.get("quantity", 1)),
                        "from_recipes": from_recipes,
                        "action": "ADD",
                        "reason": "Not in pantry" if pantry_level is None else f"Pantry low: {pantry_level}%"
                    })

            # Preview mode
            if not confirm:
                return {
                    "success": True,
                    "confirmation_required": True,
                    "preview": {
                        "items_to_add": len(items_to_add),
                        "items_to_skip": len(items_to_skip),
                        "modality": modality,
                        "items": items_to_add + items_to_skip
                    },
                    "next_step": "Review the items above. Call this tool again with confirm=True to add to cart."
                }

            # Confirm mode - actually add to cart
            if not items_to_add:
                return {
                    "success": True,
                    "message": "No items to add - all are well-stocked or missing product_ids",
                    "items_added_to_cart": 0,
                    "items_skipped": len(items_to_skip)
                }

            if ctx:
                await ctx.info(f"Adding {len(items_to_add)} items from shopping list to cart...")

            try:
                client = get_authenticated_client()

                # Format for Kroger API
                api_items = [
                    {
                        "upc": item["product_id"],
                        "quantity": item["quantity"],
                        "modality": modality
                    }
                    for item in items_to_add
                ]

                client.cart.add_to_cart(api_items)

                # Track in local cart
                for item in items_to_add:
                    _add_item_to_local_cart(
                        item["product_id"],
                        item["quantity"],
                        modality
                    )

                # Clear shopping list
                data["items"] = []
                _save_shopping_list(data)

                return {
                    "success": True,
                    "items_added_to_cart": len(items_to_add),
                    "items_skipped": len(items_to_skip),
                    "shopping_list_cleared": True,
                    "modality": modality,
                    "message": f"Added {len(items_to_add)} items to cart. Shopping list has been cleared.",
                    "reminder": "Review your cart in the Kroger app before checkout."
                }

            except Exception as cart_error:
                error_msg = str(cart_error)
                if "401" in error_msg or "Unauthorized" in error_msg:
                    return {
                        "success": False,
                        "error": "Authentication failed. Run force_reauthenticate.",
                        "details": error_msg
                    }
                return {
                    "success": False,
                    "error": f"Failed to add to cart: {error_msg}",
                    "items_attempted": len(items_to_add)
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to process shopping list: {str(e)}"
            }
