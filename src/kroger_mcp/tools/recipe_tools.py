"""
Recipe management tools for the Kroger MCP server.

Provides a single action-based tool for managing recipes and ordering ingredients,
including pantry integration via the recipe_integration analytics module.
Supports sub-recipes, side dishes, and structured cooking steps.
"""

import json
import os
import re
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

from fastmcp import Context
from pydantic import Field

from .shared import get_authenticated_client


# Recipe storage file
RECIPES_FILE = "kroger_recipes.json"


def _trigger_notion_sync(op: str, data) -> None:
    """Fire-and-forget Notion sync. Never raises."""
    try:
        from ..analytics.notion_sync import (
            _load_sync_state,
            delete_recipe_page,
            push_recipe,
        )
        state = _load_sync_state()
        if not state.get("database_id"):
            return  # Not configured yet
        api_key = os.getenv("NOTION_API_KEY")
        if not api_key:
            return
        database_id = state["database_id"]
        if op == "push" and data:
            push_recipe(data, api_key, database_id)
        elif op == "delete" and data:
            delete_recipe_page(data, api_key)
    except Exception:
        pass  # Never block recipe operations

# Valid step phases
VALID_PHASES = {"prep", "cook", "rest", "serve"}


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
        if skip_lower in ingredient_lower or ingredient_lower in skip_lower:
            return True
    return False


def _validate_ingredient(ing: dict, index: int) -> Optional[str]:
    """Validate an ingredient dict; returns error string or None if valid."""
    if not ing.get("name"):
        return f"Ingredient {index + 1} is missing 'name' field"
    for j, sub in enumerate(ing.get("substitutes") or []):
        if not sub.get("name"):
            return f"Ingredient {index + 1} substitute {j + 1} is missing 'name' field"
    return None


def _resolve_scale(recipe, servings, scale):
    """Resolve effective scale: servings-first, then explicit scale, then household default."""
    from .shared import get_default_servings

    base = recipe.get("servings", 4)

    if servings is not None:
        # Explicit servings provided
        effective = servings / base
        return effective, {"target_servings": servings, "base_servings": base, "source": "explicit"}

    if scale != 1.0:
        # Explicit non-default scale provided (backward compat)
        return scale, {"target_servings": int(base * scale), "base_servings": base, "source": "manual_scale"}

    # Default: use household servings
    household = get_default_servings()
    effective = household / base
    return effective, {"target_servings": household, "base_servings": base, "source": "household_default"}


def _collect_ingredients_recursive(
    recipe_id: str,
    scale: float = 1.0,
    visited: Optional[Set[str]] = None,
    depth: int = 0,
    max_depth: int = 10
) -> Dict[str, Any]:
    """
    Recursively collect ingredients from a recipe and its sub-recipes/sides.

    Args:
        recipe_id: Root recipe to collect from
        scale: Multiplier for ingredient quantities
        visited: Set of already-visited recipe IDs (circular detection)
        depth: Current recursion depth
        max_depth: Maximum recursion depth

    Returns:
        Dict with ingredients list, recipes_resolved list, circular flag, errors
    """
    if visited is None:
        visited = set()

    result = {
        "ingredients": [],
        "recipes_resolved": [],
        "circular_detected": False,
        "errors": []
    }

    if recipe_id in visited:
        result["circular_detected"] = True
        result["errors"].append(f"Circular reference detected: recipe '{recipe_id}' already visited")
        return result

    if depth > max_depth:
        result["errors"].append(f"Max recursion depth ({max_depth}) exceeded")
        return result

    recipe = _find_recipe(recipe_id)
    if not recipe:
        result["errors"].append(f"Recipe '{recipe_id}' not found")
        return result

    result["recipes_resolved"].append({
        "recipe_id": recipe_id,
        "recipe_name": recipe.get("name"),
        "relationship": "root" if depth == 0 else "child",
        "depth": depth
    })

    # Collect direct ingredients
    for ing in recipe.get("ingredients", []):
        qty = ing.get("quantity", 1)
        result["ingredients"].append({
            "name": ing.get("name", "Unknown"),
            "quantity": qty,
            "unit": ing.get("unit", ""),
            "product_id": ing.get("product_id"),
            "category": ing.get("category"),
            "scaled_quantity": round(qty * scale, 2) if qty else None,
            "from_recipe_id": recipe_id,
            "from_recipe_name": recipe.get("name"),
            "relationship": "direct"
        })

    current_visited = visited | {recipe_id}

    # Recurse into sub_recipes
    for sub in recipe.get("sub_recipes", []):
        sub_id = sub.get("recipe_id")
        if not sub_id:
            continue

        sub_recipe = _find_recipe(sub_id)
        if not sub_recipe:
            result["errors"].append(f"Sub-recipe '{sub_id}' not found (referenced by '{recipe.get('name')}')")
            continue

        override = sub.get("servings_override")
        if override is not None:
            sub_base = sub_recipe.get("servings", 4)
            sub_scale = override / sub_base
        else:
            sub_scale = scale

        child = _collect_ingredients_recursive(
            sub_id, sub_scale, current_visited, depth + 1, max_depth
        )

        if child["circular_detected"]:
            result["circular_detected"] = True

        for ing in child["ingredients"]:
            ing["relationship"] = "sub_recipe"
        result["ingredients"].extend(child["ingredients"])
        result["recipes_resolved"].extend(child["recipes_resolved"])
        result["errors"].extend(child["errors"])

    # Recurse into sides
    for side in recipe.get("sides", []):
        side_id = side.get("recipe_id")
        if not side_id:
            continue

        side_recipe = _find_recipe(side_id)
        if not side_recipe:
            result["errors"].append(f"Side '{side_id}' not found (referenced by '{recipe.get('name')}')")
            continue

        override = side.get("servings_override")
        if override is not None:
            side_base = side_recipe.get("servings", 4)
            side_scale = override / side_base
        else:
            side_scale = scale

        child = _collect_ingredients_recursive(
            side_id, side_scale, current_visited, depth + 1, max_depth
        )

        if child["circular_detected"]:
            result["circular_detected"] = True

        for ing in child["ingredients"]:
            ing["relationship"] = "side"
        result["ingredients"].extend(child["ingredients"])
        result["recipes_resolved"].extend(child["recipes_resolved"])
        result["errors"].extend(child["errors"])

    return result


def _parse_instructions_to_steps(instructions: str) -> List[Dict[str, Any]]:
    """
    Auto-generate basic steps from an instructions text blob.

    Splits on numbered patterns (1., 2.) or newlines.
    """
    if not instructions:
        return []

    steps = []
    # Try numbered pattern first: "1. Do this\n2. Do that"
    numbered = re.split(r'\n\s*\d+[\.\)]\s*', instructions.strip())
    # If the split produced meaningful results
    if len(numbered) > 1:
        lines = [l.strip() for l in numbered if l.strip()]
    else:
        # Fall back to newline splitting
        lines = [l.strip() for l in instructions.strip().split('\n') if l.strip()]

    for i, line in enumerate(lines, 1):
        steps.append({
            "step_number": i,
            "instruction": line,
            "phase": "prep" if i == 1 else ("serve" if i == len(lines) else "cook"),
            "duration_minutes": None,
            "sub_recipe_id": None
        })

    return steps


def _build_composition_summary(recipe_id: str) -> Dict[str, Any]:
    """
    Build a composition summary for a recipe showing its sub-recipes,
    sides, counts, and total resolved ingredients.

    Returns a dict suitable for embedding in response payloads.
    """
    recipe = _find_recipe(recipe_id)
    if not recipe:
        return {"error": f"Recipe '{recipe_id}' not found"}

    sub_details = []
    for sub in recipe.get("sub_recipes", []):
        sub_r = _find_recipe(sub.get("recipe_id", ""))
        sub_details.append({
            "recipe_id": sub.get("recipe_id"),
            "name": sub_r.get("name") if sub_r else "(not found)",
            "found": sub_r is not None,
            "relationship": "sub_recipe",
            "servings_override": sub.get("servings_override"),
            "ingredient_count": len(sub_r.get("ingredients", [])) if sub_r else 0
        })

    side_details = []
    for side in recipe.get("sides", []):
        side_r = _find_recipe(side.get("recipe_id", ""))
        side_details.append({
            "recipe_id": side.get("recipe_id"),
            "name": side_r.get("name") if side_r else "(not found)",
            "found": side_r is not None,
            "relationship": "side",
            "servings_override": side.get("servings_override"),
            "ingredient_count": len(side_r.get("ingredients", [])) if side_r else 0
        })

    collected = _collect_ingredients_recursive(recipe_id)

    return {
        "recipe_name": recipe.get("name"),
        "sub_recipes": sub_details,
        "sides": side_details,
        "total_sub_recipes": len(sub_details),
        "total_sides": len(side_details),
        "total_resolved_ingredients": len(collected["ingredients"]),
        "resolution_errors": collected["errors"] if collected["errors"] else None
    }


def _renumber_steps(steps: List[Dict[str, Any]]) -> None:
    """Renumber steps sequentially starting from 1."""
    for i, step in enumerate(steps, 1):
        step["step_number"] = i


def register_tools(mcp):
    """Register recipe tools with the FastMCP server."""

    @mcp.tool()
    async def recipes(
        action: str = Field(
            description=(
                "Action to perform: "
                "'save' - save a new recipe (requires name, ingredients); "
                "'list' - list all saved recipes; "
                "'get' - get full recipe details (requires recipe_id); "
                "'delete' - delete a recipe (requires recipe_id); "
                "'update' - update recipe fields (requires recipe_id); "
                "'search' - search by name/tags (requires query); "
                "'preview_order' - preview ingredients before adding to cart (requires recipe_id); "
                "'link_ingredient' - link ingredient (or substitute) to Kroger product (requires recipe_id+ingredient_index+product_id or links; add substitute_index to link a substitute); "
                "'manage_substitutes' - manage ingredient substitutes/alternatives (requires recipe_id+ingredient_index+sub_action); "
                "'add_to_cart' - add recipe ingredients to cart (requires recipe_id, confirm=True to execute); "
                "'check_pantry' - check pantry status for recipe (requires recipe_id); "
                "'generate_shopping_list' - generate shopping list for recipe(s) (requires recipe_ids); "
                "'get_cookable' - find recipes you can make with current pantry; "
                "'add_sub_recipe' - add sub-recipe/side (single: recipe_id+sub_recipe_id, batch: recipe_id+sub_recipe_links); "
                "'update_sub_recipe' - update servings_override or relationship of a linked sub-recipe/side (requires recipe_id, sub_recipe_id); "
                "'remove_sub_recipe' - remove sub-recipe or side (requires recipe_id, sub_recipe_id); "
                "'list_sub_recipes' - list sub-recipes and sides with child info (requires recipe_id); "
                "'add_step' - add a cooking step (requires recipe_id, step_instruction); "
                "'update_step' - update a step (requires recipe_id, step_number); "
                "'remove_step' - remove a step (requires recipe_id, step_number); "
                "'reorder_steps' - reorder steps (requires recipe_id, step_numbers); "
                "'generate_merged_steps' - generate merged cooking plan (requires recipe_id)"
            )
        ),
        recipe_id: Optional[str] = Field(
            default=None,
            description="Recipe ID. Required for: get, delete, update, preview_order, add_to_cart, check_pantry, sub-recipe/step actions"
        ),
        name: Optional[str] = Field(
            default=None,
            description="Recipe name. Required for: save. Optional for: update"
        ),
        ingredients: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description=(
                "List of ingredients. Required for: save. Optional for: update. "
                "Each: {name (required), quantity?, unit?, product_id?, category?, notes?, "
                "substitutes?: [{name (required), quantity?, unit?, product_id?, notes?}, ...]}"
            )
        ),
        instructions: Optional[str] = Field(
            default=None,
            description="Cooking instructions. Used by: save, update"
        ),
        servings: Optional[int] = Field(
            default=None, ge=1, le=20,
            description=(
                "Number of servings. For save/update: sets recipe base servings. "
                "For preview_order, add_to_cart, check_pantry, generate_shopping_list: "
                "target servings (defaults to household setting, auto-computes scale)."
            )
        ),
        description: Optional[str] = Field(
            default=None,
            description="Brief recipe description. Used by: save, update"
        ),
        source: str = Field(
            default="user provided",
            description="Recipe source. Used by: save"
        ),
        tags: Optional[List[str]] = Field(
            default=None,
            description="Tags for categorization. Used by: save, update"
        ),
        tag_filter: Optional[str] = Field(
            default=None,
            description="Filter by tag (e.g., 'italian'). Used by: list"
        ),
        limit: int = Field(
            default=20, ge=1, le=100,
            description="Max recipes to return. Used by: list"
        ),
        scale_to_household: bool = Field(
            default=False,
            description="Auto-scale ingredients to household default servings. Used by: get"
        ),
        query: Optional[str] = Field(
            default=None,
            description="Search term. Required for: search"
        ),
        skip_items: Optional[List[str]] = Field(
            default=None,
            description="Ingredient names to skip (items you already have). Used by: preview_order, add_to_cart"
        ),
        scale: float = Field(
            default=1.0, ge=0.25, le=10.0,
            description=(
                "Manual scale override. Only used when servings is not provided and "
                "you want a raw multiplier instead of servings-based scaling. "
                "Used by: preview_order, add_to_cart, check_pantry, generate_shopping_list"
            )
        ),
        modality: str = Field(
            default="PICKUP",
            description="Fulfillment method: PICKUP or DELIVERY. Used by: add_to_cart"
        ),
        confirm: bool = Field(
            default=False,
            description="Set to True to actually add items (after preview). Used by: add_to_cart"
        ),
        ingredient_index: Optional[int] = Field(
            default=None,
            description="0-based ingredient index. Used by: link_ingredient (single mode)"
        ),
        product_id: Optional[str] = Field(
            default=None,
            description="Kroger product ID to link. Used by: link_ingredient (single mode)"
        ),
        links: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description=(
                "Batch links: [{recipe_id, ingredient_index, product_id}, ...] (max 50). "
                "Used by: link_ingredient (batch mode)"
            )
        ),
        recipe_ids: Optional[List[str]] = Field(
            default=None,
            description="List of recipe IDs. Required for: generate_shopping_list"
        ),
        low_threshold: int = Field(
            default=30, ge=0, le=100,
            description="Pantry level above which items are considered 'have enough'. Used by: check_pantry"
        ),
        combine_duplicates: bool = Field(
            default=True,
            description="Merge same ingredients across recipes. Used by: generate_shopping_list"
        ),
        skip_in_pantry: bool = Field(
            default=True,
            description="Skip items already in pantry above threshold. Used by: generate_shopping_list"
        ),
        pantry_threshold: int = Field(
            default=30, ge=0, le=100,
            description="Minimum pantry level to skip items. Used by: generate_shopping_list"
        ),
        sub_recipe_id: Optional[str] = Field(
            default=None,
            description="Recipe ID to add/remove/update as sub-recipe or side. Used by: add_sub_recipe, update_sub_recipe, remove_sub_recipe"
        ),
        sub_recipe_links: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description=(
                "Batch sub-recipe/side links: [{sub_recipe_id, relationship?, servings_override?}, ...] (max 20). "
                "Used by: add_sub_recipe (batch mode). relationship defaults to 'sub_recipe' if omitted."
            )
        ),
        relationship: str = Field(
            default="sub_recipe",
            description="Relationship type: 'sub_recipe' or 'side'. Used by: add_sub_recipe, update_sub_recipe, remove_sub_recipe"
        ),
        servings_override: Optional[int] = Field(
            default=None, ge=1, le=20,
            description="Fixed servings for sub-recipe/side (null = inherit parent scale). Used by: add_sub_recipe, update_sub_recipe"
        ),
        step_number: Optional[int] = Field(
            default=None, ge=1,
            description="Step number to update/remove, or insertion point. Used by: add_step, update_step, remove_step"
        ),
        step_instruction: Optional[str] = Field(
            default=None,
            description="Step text. Used by: add_step, update_step"
        ),
        step_phase: Optional[str] = Field(
            default=None,
            description="Step phase: 'prep', 'cook', 'rest', or 'serve'. Used by: add_step, update_step"
        ),
        step_duration: Optional[int] = Field(
            default=None, ge=0,
            description="Duration in minutes. Used by: add_step, update_step"
        ),
        step_numbers: Optional[List[int]] = Field(
            default=None,
            description="New step ordering (e.g., [3, 1, 2, 4]). Used by: reorder_steps"
        ),
        sub_action: Optional[str] = Field(
            default=None,
            description="Sub-action for manage_substitutes: 'add', 'update', 'remove', 'list'"
        ),
        substitute_index: Optional[int] = Field(
            default=None,
            description=(
                "0-based substitute index within an ingredient. "
                "Used by: manage_substitutes (update/remove), link_ingredient (to link a substitute)"
            )
        ),
        substitute: Optional[Dict[str, Any]] = Field(
            default=None,
            description=(
                "Substitute ingredient data. Used by: manage_substitutes (add/update). "
                "Format: {name (required), quantity?, unit?, product_id?, notes?}"
            )
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Manage recipes, order ingredients, and integrate with pantry.
        Supports sub-recipes, side dishes, and structured cooking steps.

        Actions:
        - save: Save a new recipe with ingredients list
        - list: List saved recipes (summaries)
        - get: Full recipe details with optional household scaling
        - delete: Permanently delete a recipe
        - update: Update recipe fields (only provided fields changed)
        - search: Find recipes by name, description, or tags
        - preview_order: Preview what would be added to cart (includes sub-recipe ingredients)
        - link_ingredient: Link recipe ingredient(s) to Kroger product IDs
        - add_to_cart: Add recipe ingredients to cart (includes sub-recipes/sides)
        - check_pantry: Check pantry for recipe ingredients, categorized by availability
        - generate_shopping_list: Generate optimized shopping list for recipe(s)
        - get_cookable: Find recipes you can cook with current pantry inventory
        - add_sub_recipe: Add sub-recipe/side (single or batch via sub_recipe_links)
        - update_sub_recipe: Update servings_override or relationship of a linked sub-recipe/side
        - remove_sub_recipe: Remove a sub-recipe or side dish
        - list_sub_recipes: List all sub-recipes and sides with child info
        - add_step: Add a cooking step to a recipe
        - update_step: Update instruction, phase, or duration of a step
        - remove_step: Remove a cooking step
        - reorder_steps: Reorder cooking steps
        - generate_merged_steps: Generate optimized merged cooking plan
        - manage_substitutes: Add/update/remove/list substitutes for an ingredient
        """
        match action:
            case "save":
                if not name:
                    return {"success": False, "error": "name is required for 'save'"}
                if not ingredients:
                    return {"success": False, "error": "ingredients is required for 'save'"}

                try:
                    from .shared import get_default_servings

                    if servings is None:
                        effective_servings = get_default_servings()
                        using_default = True
                    else:
                        effective_servings = servings
                        using_default = False

                    for i, ing in enumerate(ingredients):
                        err = _validate_ingredient(ing, i)
                        if err:
                            return {"success": False, "error": err}
                        if "substitutes" not in ing:
                            ing["substitutes"] = []

                    recipe_id_new = str(uuid.uuid4())[:8]
                    recipe = {
                        "id": recipe_id_new,
                        "name": name,
                        "description": description,
                        "servings": effective_servings,
                        "ingredients": ingredients,
                        "instructions": instructions,
                        "source": source,
                        "tags": tags or [],
                        "sub_recipes": [],
                        "sides": [],
                        "steps": [],
                        "created_at": datetime.now().isoformat(),
                        "last_ordered_at": None,
                        "times_ordered": 0
                    }

                    data = _load_recipes()
                    data["recipes"].append(recipe)
                    _save_recipes(data)
                    _trigger_notion_sync("push", recipe)

                    if ctx:
                        await ctx.info(f"Saved recipe '{name}' with {len(ingredients)} ingredients")

                    household_default = get_default_servings()
                    return {
                        "success": True,
                        "recipe_id": recipe_id_new,
                        "name": name,
                        "servings": effective_servings,
                        "using_default_servings": using_default,
                        "household_default": household_default,
                        "message": f"Recipe '{name}' saved with {effective_servings} servings" +
                                  (" (your household default)" if using_default else ""),
                        "ingredient_count": len(ingredients)
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to save recipe: {str(e)}"}

            case "list":
                try:
                    data = _load_recipes()
                    recipe_list = data.get("recipes", [])

                    if tag_filter:
                        tag_lower = tag_filter.lower()
                        recipe_list = [
                            r for r in recipe_list
                            if any(tag_lower in t.lower() for t in r.get("tags", []))
                        ]

                    recipe_list = sorted(
                        recipe_list,
                        key=lambda r: r.get("created_at", ""),
                        reverse=True
                    )[:limit]

                    summaries = [
                        {
                            "id": r["id"],
                            "name": r["name"],
                            "description": r.get("description"),
                            "servings": r.get("servings"),
                            "ingredient_count": len(r.get("ingredients", [])),
                            "sub_recipe_count": len(r.get("sub_recipes", [])),
                            "side_count": len(r.get("sides", [])),
                            "step_count": len(r.get("steps", [])),
                            "tags": r.get("tags", []),
                            "times_ordered": r.get("times_ordered", 0),
                            "created_at": r.get("created_at")
                        }
                        for r in recipe_list
                    ]

                    return {
                        "success": True,
                        "recipes": summaries,
                        "count": len(summaries),
                        "total_saved": len(data.get("recipes", []))
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to get recipes: {str(e)}"}

            case "get":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'get'"}

                try:
                    from .shared import get_default_servings

                    recipe = _find_recipe(recipe_id)
                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    household_default = get_default_servings()
                    recipe_servings = recipe.get("servings", 4)
                    servings_match = recipe_servings == household_default

                    result = {
                        "success": True,
                        "recipe": recipe,
                        "household_default_servings": household_default,
                        "servings_match": servings_match,
                        "servings_note": (
                            f"Matches your household default ({household_default} servings)"
                            if servings_match
                            else f"Recipe has {recipe_servings} servings, your household default is {household_default}"
                        )
                    }

                    if scale_to_household and not servings_match:
                        scale_factor = household_default / recipe_servings
                        scaled_ingredients = []
                        for ing in recipe.get("ingredients", []):
                            scaled_ing = ing.copy()
                            if ing.get("quantity"):
                                scaled_ing["quantity"] = round(ing["quantity"] * scale_factor, 2)
                                scaled_ing["original_quantity"] = ing["quantity"]
                            scaled_ingredients.append(scaled_ing)
                        result["scaled_ingredients"] = scaled_ingredients
                        result["scale_factor"] = scale_factor
                        result["scaled_servings"] = household_default
                        result["scaling_note"] = f"Ingredients scaled from {recipe_servings} to {household_default} servings"
                    elif scale_to_household and servings_match:
                        result["scaling_note"] = "No scaling needed - recipe already matches household default"

                    if not scale_to_household and not servings_match:
                        result["suggestion"] = f"Use scale_to_household=True to auto-scale to {household_default} servings"

                    # Sub-recipe and side details
                    sub_details = []
                    for sub in recipe.get("sub_recipes", []):
                        sub_r = _find_recipe(sub.get("recipe_id", ""))
                        sub_details.append({
                            "recipe_id": sub.get("recipe_id"),
                            "name": sub_r.get("name") if sub_r else "(not found)",
                            "found": sub_r is not None,
                            "servings_override": sub.get("servings_override"),
                            "ingredient_count": len(sub_r.get("ingredients", [])) if sub_r else 0
                        })

                    side_details = []
                    for side in recipe.get("sides", []):
                        side_r = _find_recipe(side.get("recipe_id", ""))
                        side_details.append({
                            "recipe_id": side.get("recipe_id"),
                            "name": side_r.get("name") if side_r else "(not found)",
                            "found": side_r is not None,
                            "servings_override": side.get("servings_override"),
                            "ingredient_count": len(side_r.get("ingredients", [])) if side_r else 0
                        })

                    if sub_details or side_details:
                        result["sub_recipe_details"] = sub_details
                        result["sides_details"] = side_details

                        # Resolved ingredient summary
                        collected = _collect_ingredients_recursive(recipe_id)
                        result["resolved_ingredient_count"] = len(collected["ingredients"])
                        if collected["errors"]:
                            result["resolution_errors"] = collected["errors"]

                    # Steps info
                    steps = recipe.get("steps", [])
                    if steps:
                        result["step_count"] = len(steps)
                    elif recipe.get("instructions"):
                        result["step_count"] = 0
                        result["steps_note"] = "Recipe has instructions text but no structured steps. Use add_step to add steps, or generate_merged_steps to auto-generate."

                    return result
                except Exception as e:
                    return {"success": False, "error": f"Failed to get recipe: {str(e)}"}

            case "delete":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'delete'"}

                try:
                    data = _load_recipes()
                    original_count = len(data.get("recipes", []))
                    data["recipes"] = [r for r in data.get("recipes", []) if r.get("id") != recipe_id]

                    if len(data["recipes"]) == original_count:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    _save_recipes(data)
                    _trigger_notion_sync("delete", recipe_id)
                    return {
                        "success": True,
                        "message": f"Recipe '{recipe_id}' deleted",
                        "remaining_recipes": len(data["recipes"])
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to delete recipe: {str(e)}"}

            case "update":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'update'"}

                try:
                    data = _load_recipes()
                    found = False
                    for recipe in data.get("recipes", []):
                        if recipe.get("id") == recipe_id:
                            found = True
                            if name is not None:
                                recipe["name"] = name
                            if ingredients is not None:
                                for i, ing in enumerate(ingredients):
                                    err = _validate_ingredient(ing, i)
                                    if err:
                                        return {"success": False, "error": err}
                                    if "substitutes" not in ing:
                                        ing["substitutes"] = []
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
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    _save_recipes(data)
                    _trigger_notion_sync("push", _find_recipe(recipe_id))
                    return {
                        "success": True,
                        "message": f"Recipe '{recipe_id}' updated",
                        "recipe_id": recipe_id
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to update recipe: {str(e)}"}

            case "search":
                if not query:
                    return {"success": False, "error": "query is required for 'search'"}

                try:
                    data = _load_recipes()
                    query_lower = query.lower()
                    matches = []
                    for recipe in data.get("recipes", []):
                        if query_lower in recipe.get("name", "").lower():
                            matches.append(recipe)
                            continue
                        if any(query_lower in tag.lower() for tag in recipe.get("tags", [])):
                            matches.append(recipe)
                            continue
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

            case "preview_order":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'preview_order'"}

                try:
                    recipe = _find_recipe(recipe_id)
                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    scale, servings_info = _resolve_scale(recipe, servings, scale)
                    skip = skip_items or []

                    # Use recursive collector for all ingredients
                    collected = _collect_ingredients_recursive(recipe_id, scale)

                    ingredients_preview = []
                    items_to_order = 0
                    items_to_skip = 0

                    for i, ing in enumerate(collected["ingredients"]):
                        ing_name = ing.get("name", "Unknown")
                        scaled_qty = ing.get("scaled_quantity")
                        unit = ing.get("unit", "")
                        pid = ing.get("product_id")
                        will_skip = _ingredient_matches(ing_name, skip)

                        if will_skip:
                            items_to_skip += 1
                        else:
                            items_to_order += 1

                        ingredients_preview.append({
                            "index": i,
                            "name": ing_name,
                            "quantity": ing.get("quantity", 1),
                            "unit": unit,
                            "scaled_quantity": scaled_qty,
                            "product_id": pid,
                            "has_product_id": pid is not None,
                            "will_order": not will_skip,
                            "skip_reason": "user has item" if will_skip else None,
                            "from_recipe": ing.get("from_recipe_name"),
                            "relationship": ing.get("relationship")
                        })

                    from .shared import get_default_servings
                    result = {
                        "success": True,
                        "recipe_id": recipe_id,
                        "recipe_name": recipe.get("name"),
                        "base_servings": servings_info["base_servings"],
                        "scaled_servings": servings_info["target_servings"],
                        "household_default_servings": get_default_servings(),
                        "servings_info": servings_info,
                        "scale": scale,
                        "ingredients": ingredients_preview,
                        "items_to_order": items_to_order,
                        "items_to_skip": items_to_skip,
                        "total_ingredients": len(ingredients_preview),
                        "recipes_resolved": collected["recipes_resolved"]
                    }
                    if collected["errors"]:
                        result["resolution_errors"] = collected["errors"]
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Failed to preview: {str(e)}"}

            case "link_ingredient":
                try:
                    if links:
                        if len(links) > 50:
                            return {"success": False, "error": "Maximum 50 links per batch request"}

                        data = _load_recipes()
                        results = []
                        updated_recipes = set()

                        for link in links:
                            rid = link.get("recipe_id")
                            idx = link.get("ingredient_index")
                            pid = link.get("product_id")

                            if not all([rid, idx is not None, pid]):
                                results.append({
                                    "success": False,
                                    "error": "Missing required fields",
                                    "link": link
                                })
                                continue

                            recipe = None
                            for r in data.get("recipes", []):
                                if r.get("id") == rid:
                                    recipe = r
                                    break

                            if not recipe:
                                results.append({
                                    "success": False,
                                    "error": f"Recipe '{rid}' not found",
                                    "link": link
                                })
                                continue

                            ing_list = recipe.get("ingredients", [])
                            if idx < 0 or idx >= len(ing_list):
                                results.append({
                                    "success": False,
                                    "error": f"Invalid ingredient index {idx}",
                                    "link": link
                                })
                                continue

                            sub_idx = link.get("substitute_index")
                            if sub_idx is not None:
                                subs = ing_list[idx].get("substitutes", [])
                                if sub_idx < 0 or sub_idx >= len(subs):
                                    results.append({
                                        "success": False,
                                        "error": f"Invalid substitute_index {sub_idx}",
                                        "link": link
                                    })
                                    continue
                                subs[sub_idx]["product_id"] = pid
                                linked_name = subs[sub_idx].get("name")
                            else:
                                ing_list[idx]["product_id"] = pid
                                linked_name = ing_list[idx].get("name")
                            updated_recipes.add(rid)
                            results.append({
                                "success": True,
                                "recipe_id": rid,
                                "ingredient_name": ing_list[idx].get("name"),
                                "linked_name": linked_name,
                                "product_id": pid
                            })

                        for r in data.get("recipes", []):
                            if r.get("id") in updated_recipes:
                                r["updated_at"] = datetime.now().isoformat()

                        _save_recipes(data)

                        success_count = sum(1 for r in results if r.get("success"))
                        return {
                            "success": True,
                            "results": results,
                            "summary": {
                                "total": len(links),
                                "successful": success_count,
                                "failed": len(links) - success_count
                            }
                        }

                    if not all([recipe_id, ingredient_index is not None, product_id]):
                        return {
                            "success": False,
                            "error": (
                                "For single mode, provide recipe_id, ingredient_index, and product_id. "
                                "For batch mode, provide links list."
                            )
                        }

                    data = _load_recipes()
                    for recipe in data.get("recipes", []):
                        if recipe.get("id") == recipe_id:
                            ing_list = recipe.get("ingredients", [])
                            if ingredient_index < 0 or ingredient_index >= len(ing_list):
                                return {"success": False, "error": f"Invalid ingredient index {ingredient_index}"}
                            if substitute_index is not None:
                                subs = ing_list[ingredient_index].get("substitutes", [])
                                if substitute_index < 0 or substitute_index >= len(subs):
                                    return {"success": False, "error": f"Invalid substitute_index {substitute_index}"}
                                subs[substitute_index]["product_id"] = product_id
                                linked_name = subs[substitute_index].get("name")
                                msg = f"Linked substitute '{linked_name}' to product {product_id}"
                            else:
                                ing_list[ingredient_index]["product_id"] = product_id
                                linked_name = ing_list[ingredient_index].get("name")
                                msg = f"Linked '{linked_name}' to product {product_id}"
                            recipe["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)
                            return {
                                "success": True,
                                "message": msg,
                                "ingredient": ing_list[ingredient_index]
                            }

                    return {"success": False, "error": f"Recipe '{recipe_id}' not found"}
                except Exception as e:
                    return {"success": False, "error": f"Failed to link: {str(e)}"}

            case "add_to_cart":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'add_to_cart'"}

                try:
                    recipe = _find_recipe(recipe_id)
                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    scale, servings_info = _resolve_scale(recipe, servings, scale)
                    skip = skip_items or []
                    pantry_context = {}
                    try:
                        from ..analytics.pantry import get_pantry_status
                        pantry_items = get_pantry_status(apply_depletion=True)
                        for item in pantry_items:
                            pantry_context[item['product_id']] = {
                                "level_percent": item.get("level_percent", 0),
                                "status": item.get("status"),
                                "days_until_empty": item.get("days_until_empty")
                            }
                    except Exception:
                        pass

                    # Use recursive collector for all ingredients
                    collected = _collect_ingredients_recursive(recipe_id, scale)

                    ingredients_preview = []
                    items_to_add = []
                    items_to_skip_list = []
                    items_in_pantry = []

                    for i, ing in enumerate(collected["ingredients"]):
                        ing_name = ing.get("name", "Unknown")
                        scaled_qty = ing.get("scaled_quantity") or 1
                        unit = ing.get("unit", "")
                        pid = ing.get("product_id")

                        cart_qty = max(1, int(round(scaled_qty)))
                        user_skip = _ingredient_matches(ing_name, skip)
                        pantry = pantry_context.get(pid, {}) if pid else {}
                        pantry_level = pantry.get("level_percent")
                        in_pantry = pantry_level is not None

                        if user_skip:
                            action_label = "SKIP"
                            reason = "User specified to skip"
                            items_to_skip_list.append(ing_name)
                        elif in_pantry and pantry_level >= 30:
                            action_label = "SKIP"
                            reason = f"Pantry: {pantry_level}% remaining"
                            items_in_pantry.append({"name": ing_name, "pantry_level": pantry_level})
                            items_to_skip_list.append(ing_name)
                        else:
                            action_label = "ADD"
                            reason = "Not in pantry" if not in_pantry else f"Pantry low: {pantry_level}%"
                            if pid:
                                items_to_add.append({
                                    "product_id": pid,
                                    "name": ing_name,
                                    "quantity": cart_qty,
                                    "modality": modality
                                })

                        ingredients_preview.append({
                            "index": i,
                            "name": ing_name,
                            "quantity": f"{cart_qty} {unit}".strip(),
                            "action": action_label,
                            "reason": reason,
                            "product_id": pid,
                            "pantry_level": pantry_level,
                            "in_favorites": False,
                            "from_recipe": ing.get("from_recipe_name"),
                            "relationship": ing.get("relationship")
                        })

                    if not confirm:
                        from .shared import get_default_servings
                        return {
                            "success": True,
                            "confirmation_required": True,
                            "preview": {
                                "recipe_name": recipe.get("name"),
                                "recipe_base_servings": servings_info["base_servings"],
                                "servings": servings_info["target_servings"],
                                "household_default": get_default_servings(),
                                "servings_info": servings_info,
                                "scale": scale,
                                "modality": modality,
                                "ingredients": ingredients_preview,
                                "summary": {
                                    "items_to_add": len(items_to_add),
                                    "items_to_skip": len(items_to_skip_list),
                                    "items_in_pantry": len(items_in_pantry)
                                },
                                "recipes_resolved": collected["recipes_resolved"]
                            },
                            "items_in_pantry": items_in_pantry,
                            "next_step": (
                                "Review the ingredients above. "
                                "Call this tool again with confirm=True to add items to cart. "
                                "Use skip_items to exclude any additional items."
                            )
                        }

                    if not items_to_add:
                        return {
                            "success": True,
                            "message": "No items to add - all ingredients are well-stocked or skipped",
                            "items_ordered": [],
                            "items_skipped": items_to_skip_list
                        }

                    if ctx:
                        await ctx.info(f"Adding {len(items_to_add)} items to cart...")

                    try:
                        client = get_authenticated_client()
                        api_items = [
                            {"upc": item["product_id"], "quantity": item["quantity"], "modality": item["modality"]}
                            for item in items_to_add
                        ]
                        client.cart.add_to_cart(api_items)

                        from .cart_tools import _add_item_to_local_cart
                        for item in items_to_add:
                            _add_item_to_local_cart(item["product_id"], item["quantity"], item["modality"])

                        data = _load_recipes()
                        for r in data.get("recipes", []):
                            if r.get("id") == recipe_id:
                                r["times_ordered"] = r.get("times_ordered", 0) + 1
                                r["last_ordered_at"] = datetime.now().isoformat()
                                break
                        _save_recipes(data)

                        return {
                            "success": True,
                            "message": f"Added {len(items_to_add)} items to cart for '{recipe.get('name')}'",
                            "items_ordered": [
                                {"name": item["name"], "quantity": item["quantity"], "product_id": item["product_id"]}
                                for item in items_to_add
                            ],
                            "items_skipped": items_to_skip_list,
                            "modality": modality,
                            "reminder": (
                                "Please review your cart in the Kroger app before checkout. "
                                "Would you like to update any pantry levels?"
                            )
                        }
                    except Exception as cart_error:
                        error_msg = str(cart_error)
                        if "401" in error_msg or "Unauthorized" in error_msg:
                            return {
                                "success": False,
                                "error": "Authentication failed. Run auth(action='force_reauth').",
                                "details": error_msg
                            }
                        return {
                            "success": False,
                            "error": f"Failed to add to cart: {error_msg}",
                            "items_attempted": len(items_to_add)
                        }
                except Exception as e:
                    return {"success": False, "error": f"Failed to process recipe order: {str(e)}"}

            case "check_pantry":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'check_pantry'"}

                try:
                    recipe = _find_recipe(recipe_id)
                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}
                    scale, servings_info = _resolve_scale(recipe, servings, scale)

                    collected = _collect_ingredients_recursive(recipe_id, scale)
                    from ..analytics.recipe_integration import check_recipe_pantry as _check_recipe_pantry
                    result = _check_recipe_pantry(
                        recipe_id=recipe_id,
                        scale=scale,
                        low_threshold=low_threshold,
                        preloaded_ingredients=collected["ingredients"]
                    )
                    if isinstance(result, dict):
                        result["success"] = result.get("success", True)
                        result["servings_info"] = servings_info
                        if collected["recipes_resolved"] and len(collected["recipes_resolved"]) > 1:
                            result["recipes_resolved"] = collected["recipes_resolved"]
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Failed to check pantry: {str(e)}"}

            case "generate_shopping_list":
                if not recipe_ids:
                    return {"success": False, "error": "recipe_ids is required for 'generate_shopping_list'"}

                try:
                    # Resolve scale per recipe (each may have different base servings)
                    per_recipe_scales = {}
                    servings_info_all = {}
                    for rid in recipe_ids:
                        r = _find_recipe(rid)
                        if r:
                            s, info = _resolve_scale(r, servings, scale)
                            per_recipe_scales[rid] = s
                            servings_info_all[rid] = info

                    # Pre-collect ingredients per recipe with resolved scales
                    preloaded = {}
                    for rid in recipe_ids:
                        preloaded[rid] = _collect_ingredients_recursive(
                            rid, per_recipe_scales.get(rid, scale)
                        )

                    from ..analytics.recipe_integration import generate_shopping_list as _generate_shopping_list
                    result = _generate_shopping_list(
                        recipe_ids=recipe_ids,
                        combine_duplicates=combine_duplicates,
                        skip_in_pantry=skip_in_pantry,
                        pantry_threshold=pantry_threshold,
                        scale=1.0,  # ingredients already pre-scaled
                        preloaded_ingredients=preloaded
                    )
                    if isinstance(result, dict):
                        result["servings_info"] = servings_info_all
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Failed to generate shopping list: {str(e)}"}

            case "get_cookable":
                try:
                    from ..analytics.recipe_integration import get_recipes_for_pantry
                    result = get_recipes_for_pantry()
                    result["success"] = True
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Failed to get cookable recipes: {str(e)}"}

            # ---- Sub-recipe management ----

            case "add_sub_recipe":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'add_sub_recipe'"}

                try:
                    # --- Batch mode ---
                    if sub_recipe_links is not None:
                        if len(sub_recipe_links) > 20:
                            return {"success": False, "error": "Maximum 20 sub-recipe links per batch request"}

                        parent = _find_recipe(recipe_id)
                        if not parent:
                            return {"success": False, "error": f"Parent recipe '{recipe_id}' not found"}

                        data = _load_recipes()
                        results = []

                        for link in sub_recipe_links:
                            link_sub_id = link.get("sub_recipe_id")
                            link_rel = link.get("relationship", "sub_recipe")
                            link_override = link.get("servings_override")

                            if not link_sub_id:
                                results.append({"success": False, "error": "Missing sub_recipe_id", "link": link})
                                continue

                            if link_rel not in ("sub_recipe", "side"):
                                results.append({
                                    "success": False,
                                    "error": f"Invalid relationship '{link_rel}'",
                                    "sub_recipe_id": link_sub_id
                                })
                                continue

                            if recipe_id == link_sub_id:
                                results.append({
                                    "success": False,
                                    "error": "A recipe cannot be a sub-recipe of itself",
                                    "sub_recipe_id": link_sub_id
                                })
                                continue

                            child = _find_recipe(link_sub_id)
                            if not child:
                                results.append({
                                    "success": False,
                                    "error": f"Sub-recipe '{link_sub_id}' not found",
                                    "sub_recipe_id": link_sub_id
                                })
                                continue

                            # Circular detection
                            check = _collect_ingredients_recursive(link_sub_id, visited={recipe_id})
                            if check["circular_detected"]:
                                results.append({
                                    "success": False,
                                    "error": "Would create circular reference",
                                    "sub_recipe_id": link_sub_id
                                })
                                continue

                            field = "sub_recipes" if link_rel == "sub_recipe" else "sides"

                            # Find parent in data and check for duplicates
                            for r in data.get("recipes", []):
                                if r.get("id") == recipe_id:
                                    # Check both lists for duplicates
                                    already_exists = False
                                    for f in ("sub_recipes", "sides"):
                                        for entry in r.get(f, []):
                                            if entry.get("recipe_id") == link_sub_id:
                                                already_exists = True
                                                break
                                        if already_exists:
                                            break

                                    if already_exists:
                                        results.append({
                                            "success": False,
                                            "error": f"'{child.get('name')}' is already linked to '{parent.get('name')}'",
                                            "sub_recipe_id": link_sub_id
                                        })
                                    else:
                                        if field not in r:
                                            r[field] = []
                                        r[field].append({
                                            "recipe_id": link_sub_id,
                                            "servings_override": link_override
                                        })
                                        r["updated_at"] = datetime.now().isoformat()
                                        results.append({
                                            "success": True,
                                            "sub_recipe_id": link_sub_id,
                                            "name": child.get("name"),
                                            "relationship": link_rel,
                                            "servings_override": link_override
                                        })
                                    break

                        _save_recipes(data)

                        success_count = sum(1 for r in results if r.get("success"))
                        return {
                            "success": True,
                            "results": results,
                            "summary": {
                                "total": len(sub_recipe_links),
                                "successful": success_count,
                                "failed": len(sub_recipe_links) - success_count
                            },
                            "composition": _build_composition_summary(recipe_id)
                        }

                    # --- Single mode ---
                    if not sub_recipe_id:
                        return {
                            "success": False,
                            "error": (
                                "Provide sub_recipe_id for single mode, "
                                "or sub_recipe_links for batch mode."
                            )
                        }
                    if relationship not in ("sub_recipe", "side"):
                        return {"success": False, "error": "relationship must be 'sub_recipe' or 'side'"}

                    if recipe_id == sub_recipe_id:
                        return {"success": False, "error": "A recipe cannot be a sub-recipe of itself"}

                    parent = _find_recipe(recipe_id)
                    if not parent:
                        return {"success": False, "error": f"Parent recipe '{recipe_id}' not found"}

                    child = _find_recipe(sub_recipe_id)
                    if not child:
                        return {"success": False, "error": f"Sub-recipe '{sub_recipe_id}' not found"}

                    # Circular detection
                    check = _collect_ingredients_recursive(
                        sub_recipe_id, visited={recipe_id}
                    )
                    if check["circular_detected"]:
                        return {
                            "success": False,
                            "error": "Adding this sub-recipe would create a circular reference",
                            "details": check["errors"]
                        }

                    field = "sub_recipes" if relationship == "sub_recipe" else "sides"

                    # Duplicate check
                    data = _load_recipes()
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            for f in ("sub_recipes", "sides"):
                                for entry in r.get(f, []):
                                    if entry.get("recipe_id") == sub_recipe_id:
                                        return {
                                            "success": False,
                                            "error": f"'{child.get('name')}' is already linked to '{parent.get('name')}'"
                                        }

                            if field not in r:
                                r[field] = []
                            r[field].append({
                                "recipe_id": sub_recipe_id,
                                "servings_override": servings_override
                            })
                            r["updated_at"] = datetime.now().isoformat()
                            break

                    _save_recipes(data)

                    return {
                        "success": True,
                        "message": f"Added '{child.get('name')}' as {relationship} of '{parent.get('name')}'",
                        "recipe_id": recipe_id,
                        "sub_recipe_id": sub_recipe_id,
                        "relationship": relationship,
                        "servings_override": servings_override,
                        "composition": _build_composition_summary(recipe_id)
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to add sub-recipe: {str(e)}"}

            case "update_sub_recipe":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'update_sub_recipe'"}
                if not sub_recipe_id:
                    return {"success": False, "error": "sub_recipe_id is required for 'update_sub_recipe'"}

                try:
                    data = _load_recipes()
                    found_entry = None
                    found_field = None
                    parent_recipe = None

                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            parent_recipe = r
                            for field_name in ("sub_recipes", "sides"):
                                for entry in r.get(field_name, []):
                                    if entry.get("recipe_id") == sub_recipe_id:
                                        found_entry = entry
                                        found_field = field_name
                                        break
                                if found_entry:
                                    break
                            break

                    if not parent_recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    if not found_entry:
                        return {
                            "success": False,
                            "error": f"Sub-recipe '{sub_recipe_id}' not found in recipe '{recipe_id}'"
                        }

                    child = _find_recipe(sub_recipe_id)
                    changes = {}

                    # Update servings_override (write current param value, including None to clear)
                    old_override = found_entry.get("servings_override")
                    if servings_override != old_override:
                        found_entry["servings_override"] = servings_override
                        changes["servings_override"] = {"old": old_override, "new": servings_override}

                    # Handle relationship change
                    current_rel = "sub_recipe" if found_field == "sub_recipes" else "side"
                    target_field = "sub_recipes" if relationship == "sub_recipe" else "sides"

                    if relationship != current_rel:
                        if relationship not in ("sub_recipe", "side"):
                            return {"success": False, "error": "relationship must be 'sub_recipe' or 'side'"}
                        # Move from current list to target list
                        parent_recipe[found_field] = [
                            e for e in parent_recipe.get(found_field, [])
                            if e.get("recipe_id") != sub_recipe_id
                        ]
                        if target_field not in parent_recipe:
                            parent_recipe[target_field] = []
                        parent_recipe[target_field].append(found_entry)
                        changes["relationship"] = {"old": current_rel, "new": relationship}

                    if not changes:
                        return {
                            "success": True,
                            "message": "No changes needed",
                            "recipe_id": recipe_id,
                            "sub_recipe_id": sub_recipe_id,
                            "composition": _build_composition_summary(recipe_id)
                        }

                    parent_recipe["updated_at"] = datetime.now().isoformat()
                    _save_recipes(data)

                    return {
                        "success": True,
                        "message": f"Updated '{child.get('name') if child else sub_recipe_id}' link",
                        "recipe_id": recipe_id,
                        "sub_recipe_id": sub_recipe_id,
                        "changes": changes,
                        "composition": _build_composition_summary(recipe_id)
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to update sub-recipe: {str(e)}"}

            case "remove_sub_recipe":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'remove_sub_recipe'"}
                if not sub_recipe_id:
                    return {"success": False, "error": "sub_recipe_id is required for 'remove_sub_recipe'"}

                try:
                    child = _find_recipe(sub_recipe_id)
                    removed_name = child.get("name") if child else sub_recipe_id

                    data = _load_recipes()
                    removed = False
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            for field in ("sub_recipes", "sides"):
                                original = r.get(field, [])
                                filtered = [e for e in original if e.get("recipe_id") != sub_recipe_id]
                                if len(filtered) < len(original):
                                    r[field] = filtered
                                    removed = True
                            if removed:
                                r["updated_at"] = datetime.now().isoformat()
                            break

                    if not removed:
                        return {"success": False, "error": f"Sub-recipe '{sub_recipe_id}' not found in recipe '{recipe_id}'"}

                    _save_recipes(data)
                    return {
                        "success": True,
                        "message": f"Removed '{removed_name}' from recipe '{recipe_id}'",
                        "removed_recipe_name": removed_name,
                        "composition": _build_composition_summary(recipe_id)
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to remove sub-recipe: {str(e)}"}

            case "list_sub_recipes":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'list_sub_recipes'"}

                try:
                    recipe = _find_recipe(recipe_id)
                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    sub_details = []
                    for sub in recipe.get("sub_recipes", []):
                        sub_r = _find_recipe(sub.get("recipe_id", ""))
                        child_subs = len(sub_r.get("sub_recipes", [])) if sub_r else 0
                        child_sides = len(sub_r.get("sides", [])) if sub_r else 0
                        sub_details.append({
                            "recipe_id": sub.get("recipe_id"),
                            "name": sub_r.get("name") if sub_r else "(not found)",
                            "found": sub_r is not None,
                            "relationship": "sub_recipe",
                            "servings_override": sub.get("servings_override"),
                            "ingredient_count": len(sub_r.get("ingredients", [])) if sub_r else 0,
                            "has_sub_recipes": child_subs > 0,
                            "has_sides": child_sides > 0,
                            "child_count": child_subs + child_sides
                        })

                    side_details = []
                    for side in recipe.get("sides", []):
                        side_r = _find_recipe(side.get("recipe_id", ""))
                        child_subs = len(side_r.get("sub_recipes", [])) if side_r else 0
                        child_sides = len(side_r.get("sides", [])) if side_r else 0
                        side_details.append({
                            "recipe_id": side.get("recipe_id"),
                            "name": side_r.get("name") if side_r else "(not found)",
                            "found": side_r is not None,
                            "relationship": "side",
                            "servings_override": side.get("servings_override"),
                            "ingredient_count": len(side_r.get("ingredients", [])) if side_r else 0,
                            "has_sub_recipes": child_subs > 0,
                            "has_sides": child_sides > 0,
                            "child_count": child_subs + child_sides
                        })

                    collected = _collect_ingredients_recursive(recipe_id)

                    return {
                        "success": True,
                        "recipe_id": recipe_id,
                        "recipe_name": recipe.get("name"),
                        "sub_recipes": sub_details,
                        "sides": side_details,
                        "total_sub_recipes": len(sub_details),
                        "total_sides": len(side_details),
                        "total_resolved_ingredients": len(collected["ingredients"]),
                        "resolution_errors": collected["errors"] if collected["errors"] else None
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to list sub-recipes: {str(e)}"}

            # ---- Step management ----

            case "add_step":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'add_step'"}
                if not step_instruction:
                    return {"success": False, "error": "step_instruction is required for 'add_step'"}
                if step_phase and step_phase not in VALID_PHASES:
                    return {"success": False, "error": f"step_phase must be one of: {VALID_PHASES}"}

                try:
                    data = _load_recipes()
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            steps = r.get("steps", [])
                            if "steps" not in r:
                                r["steps"] = steps

                            new_step = {
                                "step_number": 0,  # will be set below
                                "instruction": step_instruction,
                                "phase": step_phase or "cook",
                                "duration_minutes": step_duration,
                                "sub_recipe_id": None
                            }

                            if step_number is not None and 1 <= step_number <= len(steps) + 1:
                                steps.insert(step_number - 1, new_step)
                            else:
                                steps.append(new_step)

                            _renumber_steps(steps)
                            r["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)

                            return {
                                "success": True,
                                "message": f"Added step {new_step['step_number']} to recipe '{r.get('name')}'",
                                "step": new_step,
                                "total_steps": len(steps)
                            }

                    return {"success": False, "error": f"Recipe '{recipe_id}' not found"}
                except Exception as e:
                    return {"success": False, "error": f"Failed to add step: {str(e)}"}

            case "update_step":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'update_step'"}
                if not step_number:
                    return {"success": False, "error": "step_number is required for 'update_step'"}
                if step_phase and step_phase not in VALID_PHASES:
                    return {"success": False, "error": f"step_phase must be one of: {VALID_PHASES}"}

                try:
                    data = _load_recipes()
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            steps = r.get("steps", [])
                            for step in steps:
                                if step.get("step_number") == step_number:
                                    if step_instruction is not None:
                                        step["instruction"] = step_instruction
                                    if step_phase is not None:
                                        step["phase"] = step_phase
                                    if step_duration is not None:
                                        step["duration_minutes"] = step_duration
                                    r["updated_at"] = datetime.now().isoformat()
                                    _save_recipes(data)
                                    return {
                                        "success": True,
                                        "message": f"Updated step {step_number}",
                                        "step": step
                                    }
                            return {"success": False, "error": f"Step {step_number} not found"}

                    return {"success": False, "error": f"Recipe '{recipe_id}' not found"}
                except Exception as e:
                    return {"success": False, "error": f"Failed to update step: {str(e)}"}

            case "remove_step":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'remove_step'"}
                if not step_number:
                    return {"success": False, "error": "step_number is required for 'remove_step'"}

                try:
                    data = _load_recipes()
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            steps = r.get("steps", [])
                            original_count = len(steps)
                            r["steps"] = [s for s in steps if s.get("step_number") != step_number]

                            if len(r["steps"]) == original_count:
                                return {"success": False, "error": f"Step {step_number} not found"}

                            _renumber_steps(r["steps"])
                            r["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)
                            return {
                                "success": True,
                                "message": f"Removed step {step_number}",
                                "remaining_steps": len(r["steps"])
                            }

                    return {"success": False, "error": f"Recipe '{recipe_id}' not found"}
                except Exception as e:
                    return {"success": False, "error": f"Failed to remove step: {str(e)}"}

            case "reorder_steps":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'reorder_steps'"}
                if not step_numbers:
                    return {"success": False, "error": "step_numbers is required for 'reorder_steps'"}

                try:
                    data = _load_recipes()
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            steps = r.get("steps", [])
                            existing_nums = {s.get("step_number") for s in steps}

                            if set(step_numbers) != existing_nums:
                                return {
                                    "success": False,
                                    "error": f"step_numbers must contain exactly the existing step numbers: {sorted(existing_nums)}"
                                }

                            step_map = {s["step_number"]: s for s in steps}
                            r["steps"] = [step_map[n] for n in step_numbers]
                            _renumber_steps(r["steps"])
                            r["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)

                            return {
                                "success": True,
                                "message": "Steps reordered",
                                "steps": r["steps"]
                            }

                    return {"success": False, "error": f"Recipe '{recipe_id}' not found"}
                except Exception as e:
                    return {"success": False, "error": f"Failed to reorder steps: {str(e)}"}

            case "generate_merged_steps":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'generate_merged_steps'"}

                try:
                    recipe = _find_recipe(recipe_id)
                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    # Collect steps from parent
                    all_steps = []
                    parent_steps = recipe.get("steps", [])
                    if not parent_steps and recipe.get("instructions"):
                        parent_steps = _parse_instructions_to_steps(recipe["instructions"])

                    for s in parent_steps:
                        all_steps.append({
                            **s,
                            "source_recipe_id": recipe_id,
                            "source_recipe_name": recipe.get("name"),
                            "source_type": "main"
                        })

                    skipped_recipes = []

                    # Collect from sub-recipes
                    for sub in recipe.get("sub_recipes", []):
                        sub_r = _find_recipe(sub.get("recipe_id", ""))
                        if not sub_r:
                            skipped_recipes.append(sub.get("recipe_id"))
                            continue
                        sub_steps = sub_r.get("steps", [])
                        if not sub_steps and sub_r.get("instructions"):
                            sub_steps = _parse_instructions_to_steps(sub_r["instructions"])
                        if not sub_steps:
                            skipped_recipes.append(sub.get("recipe_id"))
                            continue
                        for s in sub_steps:
                            all_steps.append({
                                **s,
                                "source_recipe_id": sub.get("recipe_id"),
                                "source_recipe_name": sub_r.get("name"),
                                "source_type": "sub_recipe"
                            })

                    # Collect from sides
                    for side in recipe.get("sides", []):
                        side_r = _find_recipe(side.get("recipe_id", ""))
                        if not side_r:
                            skipped_recipes.append(side.get("recipe_id"))
                            continue
                        side_steps = side_r.get("steps", [])
                        if not side_steps and side_r.get("instructions"):
                            side_steps = _parse_instructions_to_steps(side_r["instructions"])
                        if not side_steps:
                            skipped_recipes.append(side.get("recipe_id"))
                            continue
                        for s in side_steps:
                            all_steps.append({
                                **s,
                                "source_recipe_id": side.get("recipe_id"),
                                "source_recipe_name": side_r.get("name"),
                                "source_type": "side"
                            })

                    if not all_steps:
                        return {
                            "success": True,
                            "message": "No steps found in recipe or its sub-recipes/sides",
                            "merged_steps": [],
                            "skipped_recipes": skipped_recipes
                        }

                    # Group by phase
                    phase_order = ["prep", "cook", "rest", "serve"]
                    phase_groups = {p: [] for p in phase_order}

                    for step in all_steps:
                        phase = step.get("phase", "cook")
                        if phase not in phase_groups:
                            phase = "cook"
                        phase_groups[phase].append(step)

                    # Sort within phases
                    # Prep: sub-recipe/side prep first, then main
                    type_priority = {"sub_recipe": 0, "side": 1, "main": 2}
                    phase_groups["prep"].sort(
                        key=lambda s: type_priority.get(s.get("source_type", "main"), 2)
                    )

                    # Cook: longest duration first (so they start early)
                    phase_groups["cook"].sort(
                        key=lambda s: -(s.get("duration_minutes") or 0)
                    )

                    # Serve: main first, then sides
                    type_priority_serve = {"main": 0, "sub_recipe": 1, "side": 2}
                    phase_groups["serve"].sort(
                        key=lambda s: type_priority_serve.get(s.get("source_type", "main"), 2)
                    )

                    # Build merged list
                    merged = []
                    step_num = 1

                    # Calculate longest cook time for timing hints
                    cook_durations = [
                        s.get("duration_minutes", 0) or 0
                        for s in phase_groups["cook"]
                    ]
                    max_cook = max(cook_durations) if cook_durations else 0

                    for phase in phase_order:
                        for step in phase_groups[phase]:
                            source_name = step.get("source_recipe_name", "")
                            instruction = step.get("instruction", "")

                            # Label with source if not main recipe
                            if step.get("source_type") != "main":
                                label = f"[{source_name}] {instruction}"
                            else:
                                label = instruction

                            # Timing hint for cook phase
                            timing_hint = None
                            if phase == "cook" and step.get("duration_minutes"):
                                dur = step["duration_minutes"]
                                if dur < max_cook and max_cook > 0:
                                    start_offset = max_cook - dur
                                    timing_hint = f"Start {start_offset} minutes after first cook step"

                            merged.append({
                                "step_number": step_num,
                                "instruction": label,
                                "phase": phase,
                                "duration_minutes": step.get("duration_minutes"),
                                "timing_hint": timing_hint,
                                "source_recipe": source_name,
                                "source_type": step.get("source_type")
                            })
                            step_num += 1

                    return {
                        "success": True,
                        "recipe_name": recipe.get("name"),
                        "merged_steps": merged,
                        "total_steps": len(merged),
                        "phase_counts": {p: len(phase_groups[p]) for p in phase_order},
                        "estimated_total_minutes": sum(
                            s.get("duration_minutes") or 0 for s in all_steps
                        ),
                        "skipped_recipes": skipped_recipes if skipped_recipes else None
                    }
                except Exception as e:
                    return {"success": False, "error": f"Failed to generate merged steps: {str(e)}"}

            case "manage_substitutes":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'manage_substitutes'"}
                if ingredient_index is None:
                    return {"success": False, "error": "ingredient_index is required for 'manage_substitutes'"}
                if not sub_action:
                    return {"success": False, "error": "sub_action is required: 'add', 'update', 'remove', 'list'"}

                try:
                    data = _load_recipes()
                    recipe = None
                    for r in data.get("recipes", []):
                        if r.get("id") == recipe_id:
                            recipe = r
                            break

                    if not recipe:
                        return {"success": False, "error": f"Recipe '{recipe_id}' not found"}

                    ing_list = recipe.get("ingredients", [])
                    if ingredient_index < 0 or ingredient_index >= len(ing_list):
                        return {"success": False, "error": f"Invalid ingredient_index {ingredient_index}"}

                    ing = ing_list[ingredient_index]
                    # Ensure substitutes key exists
                    if "substitutes" not in ing:
                        ing["substitutes"] = []
                    subs = ing["substitutes"]

                    match sub_action:
                        case "list":
                            return {
                                "success": True,
                                "recipe_id": recipe_id,
                                "ingredient_index": ingredient_index,
                                "ingredient_name": ing.get("name"),
                                "substitutes": subs,
                                "count": len(subs)
                            }

                        case "add":
                            if not substitute:
                                return {"success": False, "error": "substitute is required for sub_action 'add'"}
                            if not substitute.get("name"):
                                return {"success": False, "error": "substitute 'name' is required"}
                            new_sub = {
                                "name": substitute["name"],
                                "quantity": substitute.get("quantity"),
                                "unit": substitute.get("unit"),
                                "product_id": substitute.get("product_id"),
                                "notes": substitute.get("notes")
                            }
                            subs.append(new_sub)
                            recipe["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)
                            return {
                                "success": True,
                                "message": f"Added substitute '{new_sub['name']}' to '{ing.get('name')}'",
                                "substitute_index": len(subs) - 1,
                                "substitute": new_sub,
                                "total_substitutes": len(subs)
                            }

                        case "update":
                            if substitute_index is None:
                                return {"success": False, "error": "substitute_index is required for sub_action 'update'"}
                            if not substitute:
                                return {"success": False, "error": "substitute is required for sub_action 'update'"}
                            if substitute_index < 0 or substitute_index >= len(subs):
                                return {"success": False, "error": f"Invalid substitute_index {substitute_index}"}
                            if "name" in substitute and not substitute["name"]:
                                return {"success": False, "error": "substitute 'name' cannot be empty"}
                            existing = subs[substitute_index]
                            if "name" in substitute:
                                existing["name"] = substitute["name"]
                            if "quantity" in substitute:
                                existing["quantity"] = substitute["quantity"]
                            if "unit" in substitute:
                                existing["unit"] = substitute["unit"]
                            if "product_id" in substitute:
                                existing["product_id"] = substitute["product_id"]
                            if "notes" in substitute:
                                existing["notes"] = substitute["notes"]
                            recipe["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)
                            return {
                                "success": True,
                                "message": f"Updated substitute {substitute_index} for '{ing.get('name')}'",
                                "substitute_index": substitute_index,
                                "substitute": existing
                            }

                        case "remove":
                            if substitute_index is None:
                                return {"success": False, "error": "substitute_index is required for sub_action 'remove'"}
                            if substitute_index < 0 or substitute_index >= len(subs):
                                return {"success": False, "error": f"Invalid substitute_index {substitute_index}"}
                            removed = subs.pop(substitute_index)
                            recipe["updated_at"] = datetime.now().isoformat()
                            _save_recipes(data)
                            return {
                                "success": True,
                                "message": f"Removed substitute '{removed.get('name')}' from '{ing.get('name')}'",
                                "removed": removed,
                                "remaining_substitutes": len(subs)
                            }

                        case _:
                            return {
                                "success": False,
                                "error": f"Unknown sub_action '{sub_action}'. Valid: 'add', 'update', 'remove', 'list'"
                            }

                except Exception as e:
                    return {"success": False, "error": f"Failed to manage substitutes: {str(e)}"}

            case _:
                return {
                    "success": False,
                    "error": (
                        f"Unknown action: '{action}'. Valid actions: "
                        "save, list, get, delete, update, search, preview_order, "
                        "link_ingredient, add_to_cart, check_pantry, generate_shopping_list, "
                        "get_cookable, add_sub_recipe, update_sub_recipe, remove_sub_recipe, "
                        "list_sub_recipes, add_step, update_step, remove_step, reorder_steps, "
                        "generate_merged_steps, manage_substitutes"
                    )
                }
