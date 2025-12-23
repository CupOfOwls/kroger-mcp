"""
Recipe management and selective ordering tools.

Provides tools for:
- Saving and managing recipes with ingredient lists
- Ordering recipe ingredients with selective opt-out
- Preview orders before adding to cart
"""

import json
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastmcp import Context
from pydantic import Field

from .shared import get_authenticated_client, get_preferred_location_id


# Recipe storage file
RECIPES_FILE = "kroger_recipes.json"


def _load_recipes() -> Dict[str, Any]:
    """Load recipes from JSON file."""
    try:
        if os.path.exists(RECIPES_FILE):
            with open(RECIPES_FILE, 'r') as f:
                return json.load(f)
    except Exception:
        pass
    return {"recipes": [], "last_updated": None}


def _save_recipes(data: Dict[str, Any]) -> None:
    """Save recipes to JSON file."""
    try:
        data["last_updated"] = datetime.now().isoformat()
        with open(RECIPES_FILE, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save recipes: {e}")


def _find_recipe(recipe_id: str) -> Optional[Dict[str, Any]]:
    """Find a recipe by ID."""
    data = _load_recipes()
    for recipe in data.get("recipes", []):
        if recipe.get("id") == recipe_id:
            return recipe
    return None


def _ingredient_matches(ingredient_name: str, skip_items: List[str]) -> bool:
    """Check if ingredient matches any skip item (case-insensitive, partial)."""
    if not skip_items:
        return False
    ingredient_lower = ingredient_name.lower()
    for skip in skip_items:
        skip_lower = skip.lower()
        # Match if skip term is contained in ingredient name or vice versa
        if skip_lower in ingredient_lower or ingredient_lower in skip_lower:
            return True
    return False


def register_tools(mcp):
    """Register recipe-related tools with the FastMCP server."""

    # ========== Recipe Management Tools ==========

    @mcp.tool()
    async def save_recipe(
        name: str = Field(description="Recipe name"),
        ingredients: List[Dict[str, Any]] = Field(
            description="List of ingredients. Each should have: name (required), "
            "quantity, unit, product_id (optional), category (optional)"
        ),
        instructions: str = Field(
            default=None, description="Cooking instructions"
        ),
        servings: int = Field(default=4, ge=1, description="Number of servings"),
        description: str = Field(
            default=None, description="Brief recipe description"
        ),
        source: str = Field(
            default="user provided",
            description="Recipe source (e.g., 'web search', 'family recipe')"
        ),
        tags: List[str] = Field(
            default=None,
            description="Tags for categorization (e.g., ['italian', 'quick'])"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Save a recipe for future ordering.

        Each ingredient should have at minimum a 'name' field. Optional fields:
        - quantity: Amount needed (number)
        - unit: Measurement unit (oz, cups, lbs, etc.)
        - product_id: Kroger product ID for direct ordering
        - category: Food category (meat, dairy, produce, etc.)

        Example ingredient:
        {"name": "Eggs", "quantity": 4, "unit": "large", "category": "dairy"}
        """
        try:
            # Validate ingredients
            if not ingredients:
                return {
                    "success": False,
                    "error": "At least one ingredient is required"
                }

            for i, ing in enumerate(ingredients):
                if not ing.get("name"):
                    return {
                        "success": False,
                        "error": f"Ingredient {i + 1} is missing 'name' field"
                    }

            # Generate recipe ID
            recipe_id = str(uuid.uuid4())[:8]

            # Create recipe object
            recipe = {
                "id": recipe_id,
                "name": name,
                "description": description,
                "servings": servings,
                "ingredients": ingredients,
                "instructions": instructions,
                "source": source,
                "tags": tags or [],
                "created_at": datetime.now().isoformat(),
                "last_ordered_at": None,
                "times_ordered": 0
            }

            # Save to file
            data = _load_recipes()
            data["recipes"].append(recipe)
            _save_recipes(data)

            if ctx:
                await ctx.info(f"Saved recipe '{name}' with {len(ingredients)} ingredients")

            return {
                "success": True,
                "recipe_id": recipe_id,
                "message": f"Recipe '{name}' saved successfully",
                "ingredient_count": len(ingredients),
                "servings": servings
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to save recipe: {str(e)}"}

    @mcp.tool()
    async def get_recipes(
        limit: int = Field(default=20, ge=1, le=100, description="Max recipes"),
        tag_filter: str = Field(
            default=None, description="Filter by tag (e.g., 'italian')"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get list of saved recipes.

        Returns recipe summaries (not full ingredients) for browsing.
        Use get_recipe with a specific ID for full details.
        """
        try:
            data = _load_recipes()
            recipes = data.get("recipes", [])

            # Apply tag filter
            if tag_filter:
                tag_lower = tag_filter.lower()
                recipes = [
                    r for r in recipes
                    if any(tag_lower in t.lower() for t in r.get("tags", []))
                ]

            # Sort by most recently created
            recipes = sorted(
                recipes,
                key=lambda r: r.get("created_at", ""),
                reverse=True
            )[:limit]

            # Return summaries
            summaries = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r.get("description"),
                    "servings": r.get("servings"),
                    "ingredient_count": len(r.get("ingredients", [])),
                    "tags": r.get("tags", []),
                    "times_ordered": r.get("times_ordered", 0),
                    "created_at": r.get("created_at")
                }
                for r in recipes
            ]

            return {
                "success": True,
                "recipes": summaries,
                "count": len(summaries),
                "total_saved": len(data.get("recipes", []))
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to get recipes: {str(e)}"}

    @mcp.tool()
    async def get_recipe(
        recipe_id: str = Field(description="Recipe ID to retrieve"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get full details of a specific recipe including all ingredients.
        """
        try:
            recipe = _find_recipe(recipe_id)
            if not recipe:
                return {
                    "success": False,
                    "error": f"Recipe '{recipe_id}' not found"
                }

            return {
                "success": True,
                "recipe": recipe
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to get recipe: {str(e)}"}

    @mcp.tool()
    async def delete_recipe(
        recipe_id: str = Field(description="Recipe ID to delete"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Delete a saved recipe.
        """
        try:
            data = _load_recipes()
            original_count = len(data.get("recipes", []))

            data["recipes"] = [
                r for r in data.get("recipes", [])
                if r.get("id") != recipe_id
            ]

            if len(data["recipes"]) == original_count:
                return {
                    "success": False,
                    "error": f"Recipe '{recipe_id}' not found"
                }

            _save_recipes(data)

            return {
                "success": True,
                "message": f"Recipe '{recipe_id}' deleted",
                "remaining_recipes": len(data["recipes"])
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to delete recipe: {str(e)}"}

    @mcp.tool()
    async def update_recipe(
        recipe_id: str = Field(description="Recipe ID to update"),
        name: str = Field(default=None, description="New recipe name"),
        ingredients: List[Dict[str, Any]] = Field(
            default=None, description="New ingredients list"
        ),
        instructions: str = Field(default=None, description="New instructions"),
        servings: int = Field(default=None, description="New serving count"),
        description: str = Field(default=None, description="New description"),
        tags: List[str] = Field(default=None, description="New tags"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Update an existing recipe. Only provided fields will be changed.
        """
        try:
            data = _load_recipes()

            # Find and update recipe
            found = False
            for recipe in data.get("recipes", []):
                if recipe.get("id") == recipe_id:
                    found = True
                    if name is not None:
                        recipe["name"] = name
                    if ingredients is not None:
                        recipe["ingredients"] = ingredients
                    if instructions is not None:
                        recipe["instructions"] = instructions
                    if servings is not None:
                        recipe["servings"] = servings
                    if description is not None:
                        recipe["description"] = description
                    if tags is not None:
                        recipe["tags"] = tags
                    recipe["updated_at"] = datetime.now().isoformat()
                    break

            if not found:
                return {
                    "success": False,
                    "error": f"Recipe '{recipe_id}' not found"
                }

            _save_recipes(data)

            return {
                "success": True,
                "message": f"Recipe '{recipe_id}' updated",
                "recipe_id": recipe_id
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to update recipe: {str(e)}"}

    @mcp.tool()
    async def search_recipes(
        query: str = Field(description="Search term for recipe name or tags"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Search recipes by name or tags.
        """
        try:
            data = _load_recipes()
            query_lower = query.lower()

            matches = []
            for recipe in data.get("recipes", []):
                # Check name
                if query_lower in recipe.get("name", "").lower():
                    matches.append(recipe)
                    continue
                # Check tags
                if any(query_lower in tag.lower()
                       for tag in recipe.get("tags", [])):
                    matches.append(recipe)
                    continue
                # Check description
                if query_lower in (recipe.get("description") or "").lower():
                    matches.append(recipe)

            summaries = [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "description": r.get("description"),
                    "tags": r.get("tags", []),
                    "ingredient_count": len(r.get("ingredients", []))
                }
                for r in matches
            ]

            return {
                "success": True,
                "query": query,
                "matches": summaries,
                "count": len(summaries)
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to search: {str(e)}"}

    # ========== Selective Ordering Tools ==========

    @mcp.tool()
    async def preview_recipe_order(
        recipe_id: str = Field(description="Recipe ID to preview"),
        skip_items: List[str] = Field(
            default=None,
            description="Ingredient names to skip (items you already have)"
        ),
        scale: float = Field(
            default=1.0, ge=0.25, le=10.0,
            description="Scale factor for quantities (2.0 = double recipe)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Preview what would be ordered without adding to cart.

        Use this to show the user the ingredient list and let them
        choose which items to skip before ordering.

        The skip_items parameter accepts ingredient names and uses
        fuzzy matching (case-insensitive, partial match).

        Example: skip_items=["eggs", "pasta"] will skip "Large Eggs"
        and "Spaghetti Pasta".
        """
        try:
            recipe = _find_recipe(recipe_id)
            if not recipe:
                return {
                    "success": False,
                    "error": f"Recipe '{recipe_id}' not found"
                }

            skip_items = skip_items or []
            ingredients_preview = []
            items_to_order = 0
            items_to_skip = 0

            for i, ing in enumerate(recipe.get("ingredients", [])):
                name = ing.get("name", "Unknown")
                quantity = ing.get("quantity", 1)
                unit = ing.get("unit", "")
                product_id = ing.get("product_id")

                # Check if should skip
                will_skip = _ingredient_matches(name, skip_items)

                if will_skip:
                    items_to_skip += 1
                else:
                    items_to_order += 1

                ingredients_preview.append({
                    "index": i,
                    "name": name,
                    "quantity": quantity,
                    "unit": unit,
                    "scaled_quantity": round(quantity * scale, 2) if quantity else None,
                    "product_id": product_id,
                    "has_product_id": product_id is not None,
                    "will_order": not will_skip,
                    "skip_reason": "user has item" if will_skip else None
                })

            return {
                "success": True,
                "recipe_id": recipe_id,
                "recipe_name": recipe.get("name"),
                "base_servings": recipe.get("servings", 4),
                "scaled_servings": int(recipe.get("servings", 4) * scale),
                "scale": scale,
                "ingredients": ingredients_preview,
                "items_to_order": items_to_order,
                "items_to_skip": items_to_skip,
                "total_ingredients": len(ingredients_preview)
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to preview: {str(e)}"}

    @mcp.tool()
    async def order_recipe_ingredients(
        recipe_id: str = Field(description="Recipe ID to order from"),
        skip_items: List[str] = Field(
            default=None,
            description="Ingredient names to skip (items you already have)"
        ),
        modality: str = Field(
            default="PICKUP",
            description="Fulfillment method: PICKUP or DELIVERY"
        ),
        scale: float = Field(
            default=1.0, ge=0.25, le=10.0,
            description="Scale factor for quantities"
        ),
        auto_search: bool = Field(
            default=True,
            description="Search for products if ingredient has no product_id"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Order ingredients from a saved recipe, skipping items user already has.

        Workflow:
        1. Load recipe and filter out skipped items
        2. For items with product_id: add directly to cart
        3. For items without product_id (if auto_search=True): search and add
        4. Return summary of what was added/skipped/not found

        Use preview_recipe_order first to show user what will be ordered.
        """
        try:
            recipe = _find_recipe(recipe_id)
            if not recipe:
                return {
                    "success": False,
                    "error": f"Recipe '{recipe_id}' not found"
                }

            if ctx:
                await ctx.info(f"Ordering ingredients for '{recipe.get('name')}'")

            skip_items = skip_items or []
            added_items = []
            skipped_items = []
            not_found = []
            cart_items = []

            # Get location for product search
            location_id = get_preferred_location_id()

            for ing in recipe.get("ingredients", []):
                name = ing.get("name", "Unknown")
                quantity = ing.get("quantity", 1)
                product_id = ing.get("product_id")

                # Check if should skip
                if _ingredient_matches(name, skip_items):
                    skipped_items.append({
                        "name": name,
                        "reason": "user already has item"
                    })
                    continue

                # Scale quantity
                scaled_qty = max(1, int(round(quantity * scale))) if quantity else 1

                # If we have a product_id, use it directly
                if product_id:
                    cart_items.append({
                        "product_id": product_id,
                        "quantity": scaled_qty,
                        "modality": modality,
                        "name": name
                    })
                    added_items.append({
                        "name": name,
                        "product_id": product_id,
                        "quantity": scaled_qty,
                        "source": "saved_product_id"
                    })
                elif auto_search and location_id:
                    # Try to search for the product
                    if ctx:
                        await ctx.info(f"Searching for '{name}'...")

                    try:
                        client = get_authenticated_client()
                        results = client.products.search(
                            search_term=name,
                            location_id=location_id,
                            limit=1
                        )

                        if results and len(results) > 0:
                            found_product = results[0]
                            found_id = found_product.get("productId")
                            if found_id:
                                cart_items.append({
                                    "product_id": found_id,
                                    "quantity": scaled_qty,
                                    "modality": modality,
                                    "name": name
                                })
                                added_items.append({
                                    "name": name,
                                    "product_id": found_id,
                                    "quantity": scaled_qty,
                                    "found_product": found_product.get(
                                        "description", name
                                    ),
                                    "source": "auto_search"
                                })
                            else:
                                not_found.append({
                                    "name": name,
                                    "reason": "no product ID in search result"
                                })
                        else:
                            not_found.append({
                                "name": name,
                                "reason": "no products found"
                            })
                    except Exception as search_error:
                        not_found.append({
                            "name": name,
                            "reason": f"search failed: {str(search_error)}"
                        })
                else:
                    not_found.append({
                        "name": name,
                        "reason": "no product_id and auto_search disabled"
                    })

            # Add items to cart
            if cart_items:
                if ctx:
                    await ctx.info(f"Adding {len(cart_items)} items to cart...")

                try:
                    client = get_authenticated_client()

                    # Format for Kroger API
                    api_items = [
                        {
                            "upc": item["product_id"],
                            "quantity": item["quantity"],
                            "modality": item["modality"]
                        }
                        for item in cart_items
                    ]

                    client.cart.add_to_cart(api_items)

                    # Track in local cart (import here to avoid circular)
                    from .cart_tools import _add_item_to_local_cart
                    for item in cart_items:
                        _add_item_to_local_cart(
                            item["product_id"],
                            item["quantity"],
                            item["modality"]
                        )

                except Exception as cart_error:
                    return {
                        "success": False,
                        "error": f"Failed to add to cart: {str(cart_error)}",
                        "items_attempted": len(cart_items)
                    }

            # Update recipe stats
            data = _load_recipes()
            for r in data.get("recipes", []):
                if r.get("id") == recipe_id:
                    r["times_ordered"] = r.get("times_ordered", 0) + 1
                    r["last_ordered_at"] = datetime.now().isoformat()
                    break
            _save_recipes(data)

            return {
                "success": True,
                "recipe_name": recipe.get("name"),
                "added_items": added_items,
                "skipped_items": skipped_items,
                "not_found": not_found,
                "summary": {
                    "total_added": len(added_items),
                    "total_skipped": len(skipped_items),
                    "total_not_found": len(not_found)
                },
                "modality": modality,
                "scale": scale,
                "message": (
                    f"Added {len(added_items)} items to cart. "
                    f"Skipped {len(skipped_items)} items. "
                    f"{len(not_found)} items not found."
                )
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to order ingredients: {str(e)}"
            }

    @mcp.tool()
    async def link_ingredient_to_product(
        recipe_id: str = Field(description="Recipe ID"),
        ingredient_index: int = Field(
            description="Index of ingredient in recipe (0-based)"
        ),
        product_id: str = Field(description="Kroger product ID to link"),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Link a recipe ingredient to a specific Kroger product.

        This allows future orders to use the product directly without searching.
        Use this after finding the right product for an ingredient.
        """
        try:
            data = _load_recipes()

            for recipe in data.get("recipes", []):
                if recipe.get("id") == recipe_id:
                    ingredients = recipe.get("ingredients", [])
                    if ingredient_index < 0 or ingredient_index >= len(ingredients):
                        return {
                            "success": False,
                            "error": f"Invalid ingredient index {ingredient_index}"
                        }

                    ingredients[ingredient_index]["product_id"] = product_id
                    recipe["updated_at"] = datetime.now().isoformat()
                    _save_recipes(data)

                    return {
                        "success": True,
                        "message": (
                            f"Linked '{ingredients[ingredient_index]['name']}' "
                            f"to product {product_id}"
                        ),
                        "ingredient": ingredients[ingredient_index]
                    }

            return {
                "success": False,
                "error": f"Recipe '{recipe_id}' not found"
            }

        except Exception as e:
            return {"success": False, "error": f"Failed to link: {str(e)}"}
