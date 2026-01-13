"""
Recipe-Pantry integration for smart shopping lists.

Matches recipe ingredients to pantry items and generates optimized shopping lists
that consider current inventory levels.
"""

from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized
from .pantry import get_pantry_status, get_pantry_item


def match_ingredient_to_pantry(
    ingredient_name: str,
    product_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """
    Find pantry item matching a recipe ingredient.

    Args:
        ingredient_name: Name of the ingredient
        product_id: Optional product ID if linked

    Returns:
        Pantry item info or None if not found
    """
    # If we have a product_id, try direct match
    if product_id:
        pantry_item = get_pantry_item(product_id)
        if pantry_item:
            return pantry_item

    # Otherwise, try to match by description (fuzzy matching)
    pantry_items = get_pantry_status(apply_depletion=True)

    # Normalize ingredient name for matching
    ingredient_lower = ingredient_name.lower()
    ingredient_words = set(ingredient_lower.split())

    best_match = None
    best_score = 0

    for item in pantry_items:
        description = (item.get('description') or '').lower()
        if not description:
            continue

        # Simple word overlap scoring
        desc_words = set(description.split())
        overlap = len(ingredient_words & desc_words)

        # Boost for exact substring match
        if ingredient_lower in description or description in ingredient_lower:
            overlap += 2

        if overlap > best_score:
            best_score = overlap
            best_match = item

    # Require at least one word match
    if best_score > 0:
        return best_match

    return None


def check_recipe_pantry(
    recipe_id: str,
    scale: float = 1.0,
    low_threshold: int = 30
) -> Dict[str, Any]:
    """
    Check pantry for recipe ingredients and categorize by availability.

    Args:
        recipe_id: Recipe identifier
        scale: Multiplier for recipe quantities
        low_threshold: Consider "have enough" if pantry level above this

    Returns:
        Dict with categorized ingredients:
        - have_enough: Items with sufficient pantry level
        - low_but_usable: Items low but might still work
        - need_to_buy: Items below threshold or not in pantry
        - unknown: Items not tracked in pantry
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get recipe ingredients
        cursor = conn.execute("""
            SELECT ri.*, r.name as recipe_name, r.servings
            FROM recipe_ingredients ri
            JOIN recipes r ON ri.recipe_id = r.id
            WHERE ri.recipe_id = ?
        """, (recipe_id,))
        ingredients = [dict(row) for row in cursor.fetchall()]

        if not ingredients:
            return {
                'success': False,
                'error': f"Recipe '{recipe_id}' not found or has no ingredients"
            }

        recipe_name = ingredients[0].get('recipe_name', recipe_id)

        result = {
            'recipe_id': recipe_id,
            'recipe_name': recipe_name,
            'scale': scale,
            'have_enough': [],
            'low_but_usable': [],
            'need_to_buy': [],
            'unknown': []
        }

        for ing in ingredients:
            ing_name = ing.get('name', '')
            product_id = ing.get('product_id')
            is_optional = ing.get('is_optional', False)

            # Try to find in pantry
            pantry_item = match_ingredient_to_pantry(ing_name, product_id)

            item_info = {
                'ingredient': ing_name,
                'quantity': ing.get('quantity'),
                'unit': ing.get('unit'),
                'product_id': product_id,
                'is_optional': bool(is_optional)
            }

            if pantry_item:
                level = pantry_item.get('level_percent', 0)
                item_info['pantry_level'] = level
                item_info['pantry_description'] = pantry_item.get('description')
                item_info['days_until_empty'] = pantry_item.get('days_until_empty')

                if level >= low_threshold:
                    result['have_enough'].append(item_info)
                elif level > 10:
                    result['low_but_usable'].append(item_info)
                else:
                    result['need_to_buy'].append(item_info)
            else:
                result['unknown'].append(item_info)

        # Summary
        result['summary'] = {
            'total_ingredients': len(ingredients),
            'have_enough_count': len(result['have_enough']),
            'low_count': len(result['low_but_usable']),
            'need_count': len(result['need_to_buy']),
            'unknown_count': len(result['unknown']),
            'ready_to_cook': len(result['need_to_buy']) == 0 and len(result['unknown']) == 0
        }

        return result
    finally:
        conn.close()


def generate_shopping_list(
    recipe_ids: List[str],
    combine_duplicates: bool = True,
    skip_in_pantry: bool = True,
    pantry_threshold: int = 30,
    scale: float = 1.0
) -> Dict[str, Any]:
    """
    Generate optimized shopping list for multiple recipes.

    Args:
        recipe_ids: List of recipe identifiers
        combine_duplicates: Merge same ingredients across recipes
        skip_in_pantry: Skip items already in pantry above threshold
        pantry_threshold: Minimum pantry level to skip
        scale: Recipe quantity multiplier

    Returns:
        Shopping list with items to buy and optional items
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        all_ingredients = []
        recipe_names = {}

        # Gather ingredients from all recipes
        for recipe_id in recipe_ids:
            cursor = conn.execute("""
                SELECT ri.*, r.name as recipe_name
                FROM recipe_ingredients ri
                JOIN recipes r ON ri.recipe_id = r.id
                WHERE ri.recipe_id = ?
            """, (recipe_id,))

            for row in cursor.fetchall():
                ing = dict(row)
                recipe_names[recipe_id] = ing.get('recipe_name', recipe_id)
                all_ingredients.append({
                    **ing,
                    'from_recipe': recipe_id
                })

        if not all_ingredients:
            return {
                'success': False,
                'error': 'No ingredients found for specified recipes'
            }

        # Group and optionally combine ingredients
        shopping_items = {}
        optional_items = {}
        skipped_items = []

        for ing in all_ingredients:
            ing_name = ing.get('name', '').lower()
            product_id = ing.get('product_id')
            is_optional = ing.get('is_optional', False)
            quantity = (ing.get('quantity') or 1) * scale
            unit = ing.get('unit', '')

            # Check pantry if skip_in_pantry is enabled
            if skip_in_pantry:
                pantry_item = match_ingredient_to_pantry(ing_name, product_id)
                if pantry_item and pantry_item.get('level_percent', 0) >= pantry_threshold:
                    skipped_items.append({
                        'ingredient': ing.get('name'),
                        'pantry_level': pantry_item.get('level_percent'),
                        'from_recipe': recipe_names.get(ing.get('from_recipe'))
                    })
                    continue

            # Create key for combining
            key = product_id or ing_name

            target = optional_items if is_optional else shopping_items

            if combine_duplicates and key in target:
                # Combine quantities if same unit
                existing = target[key]
                if existing.get('unit') == unit:
                    existing['quantity'] = (existing.get('quantity') or 0) + quantity
                    existing['from_recipes'].append(
                        recipe_names.get(ing.get('from_recipe')))
            else:
                target[key] = {
                    'ingredient': ing.get('name'),
                    'quantity': quantity,
                    'unit': unit,
                    'product_id': product_id,
                    'product_description': ing.get('product_description'),
                    'from_recipes': [recipe_names.get(ing.get('from_recipe'))]
                }

        return {
            'success': True,
            'recipes': list(recipe_names.values()),
            'scale': scale,
            'to_buy': list(shopping_items.values()),
            'optional': list(optional_items.values()),
            'skipped_in_pantry': skipped_items,
            'summary': {
                'items_to_buy': len(shopping_items),
                'optional_items': len(optional_items),
                'skipped_from_pantry': len(skipped_items)
            }
        }
    finally:
        conn.close()


def get_recipes_for_pantry() -> Dict[str, Any]:
    """
    Find recipes that can be made with current pantry inventory.

    Returns:
        Dict with recipes sorted by feasibility
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get all recipes
        cursor = conn.execute("SELECT id, name FROM recipes")
        recipes = [dict(row) for row in cursor.fetchall()]

        results = []
        for recipe in recipes:
            check = check_recipe_pantry(recipe['id'])
            if check.get('summary'):
                summary = check['summary']
                feasibility = (
                    summary['have_enough_count'] /
                    max(1, summary['total_ingredients'])
                )
                results.append({
                    'recipe_id': recipe['id'],
                    'recipe_name': recipe['name'],
                    'feasibility': round(feasibility, 2),
                    'have_ingredients': summary['have_enough_count'],
                    'need_ingredients': summary['need_count'] + summary['unknown_count'],
                    'ready_to_cook': summary['ready_to_cook']
                })

        # Sort by feasibility (highest first)
        results.sort(key=lambda r: r['feasibility'], reverse=True)

        return {
            'recipes': results,
            'ready_to_cook': [r for r in results if r['ready_to_cook']],
            'summary': {
                'total_recipes': len(results),
                'ready_count': len([r for r in results if r['ready_to_cook']])
            }
        }
    finally:
        conn.close()
