"""
Meal planning business logic.

Provides functions for:
- Creating and managing meal plans
- Assigning recipes to meal slots
- Generating shopping lists for meal plans
- Checking pantry availability for meal plans
"""

import json
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import get_db_connection, get_db_cursor, ensure_initialized
from .pantry import get_pantry_status
from .recipe_integration import match_ingredient_to_pantry


VALID_MEAL_SLOTS = {'breakfast', 'lunch', 'dinner', 'snack'}
VALID_PLAN_TYPES = {'weekly', 'monthly', 'custom'}
RECIPES_FILE = "kroger_recipes.json"


def _parse_date(date_str: str) -> datetime:
    """Parse a YYYY-MM-DD date string."""
    return datetime.strptime(date_str, "%Y-%m-%d")


def _format_date(dt: datetime) -> str:
    """Format a datetime as YYYY-MM-DD."""
    return dt.strftime("%Y-%m-%d")


def _get_recipe_from_json(recipe_id: str) -> Optional[Dict[str, Any]]:
    """Get recipe from JSON file (primary storage)."""
    try:
        if os.path.exists(RECIPES_FILE):
            with open(RECIPES_FILE, 'r') as f:
                data = json.load(f)
                for recipe in data.get("recipes", []):
                    if recipe.get("id") == recipe_id:
                        return recipe
    except Exception:
        pass
    return None


def _get_recipe_from_db(recipe_id: str) -> Optional[Dict[str, Any]]:
    """Get recipe from SQLite database."""
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM recipes WHERE id = ?", (recipe_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        recipe = dict(row)

        # Get ingredients
        cursor = conn.execute(
            "SELECT * FROM recipe_ingredients WHERE recipe_id = ?",
            (recipe_id,)
        )
        recipe['ingredients'] = [dict(r) for r in cursor.fetchall()]

        return recipe
    finally:
        conn.close()


def get_recipe(recipe_id: str) -> Optional[Dict[str, Any]]:
    """Get recipe from either JSON or database."""
    # Try JSON first (primary storage)
    recipe = _get_recipe_from_json(recipe_id)
    if recipe:
        return recipe

    # Fallback to database
    return _get_recipe_from_db(recipe_id)


# ============== Meal Plan CRUD ==============


def create_meal_plan(
    name: str,
    start_date: str,
    end_date: Optional[str] = None,
    plan_type: str = "weekly",
    description: Optional[str] = None,
    is_template: bool = False
) -> Dict[str, Any]:
    """
    Create a new meal plan.

    Args:
        name: Plan name (e.g., "Week of Jan 27")
        start_date: Start date YYYY-MM-DD
        end_date: End date YYYY-MM-DD (defaults to start + 6 days for weekly)
        plan_type: 'weekly', 'monthly', or 'custom'
        description: Optional description
        is_template: Whether this is a reusable template

    Returns:
        Created plan info with plan_id
    """
    ensure_initialized()

    if plan_type not in VALID_PLAN_TYPES:
        return {
            "success": False,
            "error": f"Invalid plan_type. Must be one of: {VALID_PLAN_TYPES}"
        }

    try:
        start_dt = _parse_date(start_date)
    except ValueError:
        return {
            "success": False,
            "error": "Invalid start_date format. Use YYYY-MM-DD"
        }

    # Default end_date based on plan_type
    if not end_date:
        if plan_type == "weekly":
            end_dt = start_dt + timedelta(days=6)
        elif plan_type == "monthly":
            # Roughly 30 days
            end_dt = start_dt + timedelta(days=29)
        else:
            end_dt = start_dt + timedelta(days=6)
        end_date = _format_date(end_dt)
    else:
        try:
            end_dt = _parse_date(end_date)
        except ValueError:
            return {
                "success": False,
                "error": "Invalid end_date format. Use YYYY-MM-DD"
            }

    if end_dt < start_dt:
        return {
            "success": False,
            "error": "end_date must be on or after start_date"
        }

    plan_id = str(uuid.uuid4())[:8]
    now = datetime.now().isoformat()
    days_count = (end_dt - start_dt).days + 1

    with get_db_cursor() as cursor:
        cursor.execute("""
            INSERT INTO meal_plans
            (id, name, description, start_date, end_date, plan_type,
             is_template, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            plan_id, name, description, start_date, end_date,
            plan_type, int(is_template), now, now
        ))

    return {
        "success": True,
        "plan_id": plan_id,
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "days_count": days_count,
        "plan_type": plan_type,
        "is_template": is_template,
        "message": f"Created meal plan '{name}' covering {days_count} days"
    }


def get_meal_plans(
    include_past: bool = False,
    include_templates: bool = False,
    limit: int = 20
) -> Dict[str, Any]:
    """
    List meal plans with summary info.

    Args:
        include_past: Include plans with end_date before today
        include_templates: Include template plans
        limit: Maximum number of plans to return

    Returns:
        List of plan summaries
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        today = _format_date(datetime.now())

        query = "SELECT * FROM meal_plans WHERE 1=1"
        params: List[Any] = []

        if not include_past:
            query += " AND end_date >= ?"
            params.append(today)

        if not include_templates:
            query += " AND is_template = 0"

        query += " ORDER BY start_date DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        plans = [dict(row) for row in cursor.fetchall()]

        # Get meal counts for each plan
        for plan in plans:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM meal_entries WHERE plan_id = ?",
                (plan['id'],)
            )
            plan['meal_count'] = cursor.fetchone()[0]
            plan['is_template'] = bool(plan.get('is_template'))

        # Count templates and upcoming
        cursor = conn.execute(
            "SELECT COUNT(*) FROM meal_plans WHERE is_template = 1"
        )
        template_count = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM meal_plans WHERE end_date >= ? AND is_template = 0",
            (today,)
        )
        upcoming_count = cursor.fetchone()[0]

        return {
            "success": True,
            "plans": plans,
            "total_count": len(plans),
            "upcoming_count": upcoming_count,
            "template_count": template_count
        }
    finally:
        conn.close()


def get_meal_plan(
    plan_id: str,
    include_recipe_details: bool = True
) -> Dict[str, Any]:
    """
    Get full details of a meal plan including all meal entries.

    Args:
        plan_id: Plan identifier
        include_recipe_details: Whether to fetch full recipe info

    Returns:
        Plan with meals_by_date and recipe_summary
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get plan
        cursor = conn.execute(
            "SELECT * FROM meal_plans WHERE id = ?", (plan_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {
                "success": False,
                "error": f"Meal plan '{plan_id}' not found"
            }

        plan = dict(row)
        plan['is_template'] = bool(plan.get('is_template'))

        # Get meal entries
        cursor = conn.execute("""
            SELECT * FROM meal_entries
            WHERE plan_id = ?
            ORDER BY meal_date, meal_slot
        """, (plan_id,))
        entries = [dict(r) for r in cursor.fetchall()]

        # Organize by date
        meals_by_date: Dict[str, Dict[str, Any]] = {}
        recipe_ids = set()

        for entry in entries:
            date = entry['meal_date']
            slot = entry['meal_slot']

            if date not in meals_by_date:
                meals_by_date[date] = {}

            meal_info = {
                "recipe_id": entry['recipe_id'],
                "servings_override": entry.get('servings_override'),
                "notes": entry.get('notes')
            }

            if include_recipe_details:
                recipe = get_recipe(entry['recipe_id'])
                if recipe:
                    meal_info['recipe_name'] = recipe.get('name')
                    meal_info['recipe_servings'] = recipe.get('servings', 4)
                    recipe_ids.add(entry['recipe_id'])

            meals_by_date[date][slot] = meal_info

        # Recipe summary
        recipe_summary = []
        recipe_counts: Dict[str, int] = {}
        for entry in entries:
            rid = entry['recipe_id']
            recipe_counts[rid] = recipe_counts.get(rid, 0) + 1

        for rid, count in recipe_counts.items():
            recipe = get_recipe(rid)
            recipe_summary.append({
                "recipe_id": rid,
                "recipe_name": recipe.get('name') if recipe else rid,
                "times_used": count
            })

        return {
            "success": True,
            "plan": plan,
            "meals_by_date": meals_by_date,
            "meal_count": len(entries),
            "recipe_summary": recipe_summary,
            "unique_recipes": len(recipe_ids)
        }
    finally:
        conn.close()


def update_meal_plan(
    plan_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Update meal plan metadata.

    Args:
        plan_id: Plan identifier
        name: New name (optional)
        description: New description (optional)
        start_date: New start date (optional)
        end_date: New end date (optional)

    Returns:
        Updated plan info
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Check plan exists
        cursor = conn.execute(
            "SELECT * FROM meal_plans WHERE id = ?", (plan_id,)
        )
        if not cursor.fetchone():
            return {
                "success": False,
                "error": f"Meal plan '{plan_id}' not found"
            }

        updates = []
        params: List[Any] = []

        if name is not None:
            updates.append("name = ?")
            params.append(name)
        if description is not None:
            updates.append("description = ?")
            params.append(description)
        if start_date is not None:
            try:
                _parse_date(start_date)
            except ValueError:
                return {"success": False, "error": "Invalid start_date format"}
            updates.append("start_date = ?")
            params.append(start_date)
        if end_date is not None:
            try:
                _parse_date(end_date)
            except ValueError:
                return {"success": False, "error": "Invalid end_date format"}
            updates.append("end_date = ?")
            params.append(end_date)

        if not updates:
            return {
                "success": False,
                "error": "No fields to update"
            }

        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(plan_id)

        conn.execute(
            f"UPDATE meal_plans SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

        return {
            "success": True,
            "plan_id": plan_id,
            "message": "Meal plan updated",
            "fields_updated": len(updates) - 1  # Exclude updated_at
        }
    finally:
        conn.close()


def delete_meal_plan(plan_id: str) -> Dict[str, Any]:
    """
    Delete a meal plan and all its meal entries.

    Args:
        plan_id: Plan identifier

    Returns:
        Confirmation of deletion
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Check plan exists
        cursor = conn.execute(
            "SELECT name FROM meal_plans WHERE id = ?", (plan_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {
                "success": False,
                "error": f"Meal plan '{plan_id}' not found"
            }

        plan_name = row[0]

        # Get meal count before delete
        cursor = conn.execute(
            "SELECT COUNT(*) FROM meal_entries WHERE plan_id = ?", (plan_id,)
        )
        meal_count = cursor.fetchone()[0]

        # Delete (CASCADE will remove meal_entries)
        conn.execute("DELETE FROM meal_plans WHERE id = ?", (plan_id,))
        conn.commit()

        return {
            "success": True,
            "message": f"Deleted meal plan '{plan_name}'",
            "meals_removed": meal_count
        }
    finally:
        conn.close()


def copy_meal_plan(
    source_plan_id: str,
    new_name: str,
    new_start_date: str
) -> Dict[str, Any]:
    """
    Copy a meal plan to a new date range.

    All meals are shifted to the new date range maintaining their
    relative positions (day offset and meal slot).

    Args:
        source_plan_id: Plan to copy from
        new_name: Name for the new plan
        new_start_date: Start date for the new plan YYYY-MM-DD

    Returns:
        New plan info
    """
    ensure_initialized()

    # Get source plan
    source = get_meal_plan(source_plan_id, include_recipe_details=False)
    if not source.get('success'):
        return source

    plan = source['plan']
    source_start = _parse_date(plan['start_date'])
    source_end = _parse_date(plan['end_date'])
    duration = (source_end - source_start).days

    try:
        new_start_dt = _parse_date(new_start_date)
    except ValueError:
        return {
            "success": False,
            "error": "Invalid new_start_date format. Use YYYY-MM-DD"
        }

    new_end_dt = new_start_dt + timedelta(days=duration)
    new_end_date = _format_date(new_end_dt)

    # Create new plan
    result = create_meal_plan(
        name=new_name,
        start_date=new_start_date,
        end_date=new_end_date,
        plan_type=plan['plan_type'],
        description=plan.get('description'),
        is_template=False
    )

    if not result.get('success'):
        return result

    new_plan_id = result['plan_id']

    # Copy meal entries with date offset
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM meal_entries WHERE plan_id = ?",
            (source_plan_id,)
        )
        entries = [dict(r) for r in cursor.fetchall()]

        copied = 0
        for entry in entries:
            old_date = _parse_date(entry['meal_date'])
            offset = (old_date - source_start).days
            new_date = _format_date(new_start_dt + timedelta(days=offset))

            conn.execute("""
                INSERT INTO meal_entries
                (plan_id, recipe_id, meal_date, meal_slot,
                 servings_override, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                new_plan_id,
                entry['recipe_id'],
                new_date,
                entry['meal_slot'],
                entry.get('servings_override'),
                entry.get('notes'),
                datetime.now().isoformat()
            ))
            copied += 1

        conn.commit()

        result['meals_copied'] = copied
        result['message'] = f"Copied plan with {copied} meals"
        return result
    finally:
        conn.close()


# ============== Meal Assignment ==============


def assign_meal(
    plan_id: str,
    recipe_id: str,
    meal_date: str,
    meal_slot: str,
    servings_override: Optional[int] = None,
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Assign a recipe to a specific day and meal slot.

    Replaces any existing recipe in that slot.

    Args:
        plan_id: Plan identifier
        recipe_id: Recipe to assign
        meal_date: Date YYYY-MM-DD
        meal_slot: 'breakfast', 'lunch', 'dinner', or 'snack'
        servings_override: Override recipe default servings
        notes: Optional notes

    Returns:
        Confirmation of assignment
    """
    ensure_initialized()

    if meal_slot not in VALID_MEAL_SLOTS:
        return {
            "success": False,
            "error": f"Invalid meal_slot. Must be one of: {VALID_MEAL_SLOTS}"
        }

    try:
        meal_dt = _parse_date(meal_date)
    except ValueError:
        return {
            "success": False,
            "error": "Invalid meal_date format. Use YYYY-MM-DD"
        }

    conn = get_db_connection()
    try:
        # Verify plan exists and date is in range
        cursor = conn.execute(
            "SELECT start_date, end_date FROM meal_plans WHERE id = ?",
            (plan_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {
                "success": False,
                "error": f"Meal plan '{plan_id}' not found"
            }

        start_dt = _parse_date(row[0])
        end_dt = _parse_date(row[1])

        if not (start_dt <= meal_dt <= end_dt):
            return {
                "success": False,
                "error": f"meal_date must be between {row[0]} and {row[1]}"
            }

        # Verify recipe exists
        recipe = get_recipe(recipe_id)
        if not recipe:
            return {
                "success": False,
                "error": f"Recipe '{recipe_id}' not found"
            }

        # Insert or replace (UNIQUE constraint handles this)
        conn.execute("""
            INSERT OR REPLACE INTO meal_entries
            (plan_id, recipe_id, meal_date, meal_slot,
             servings_override, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            plan_id, recipe_id, meal_date, meal_slot,
            servings_override, notes, datetime.now().isoformat()
        ))
        conn.commit()

        return {
            "success": True,
            "plan_id": plan_id,
            "meal_date": meal_date,
            "meal_slot": meal_slot,
            "recipe_id": recipe_id,
            "recipe_name": recipe.get('name'),
            "message": f"Assigned '{recipe.get('name')}' to {meal_slot} on {meal_date}"
        }
    finally:
        conn.close()


def remove_meal(
    plan_id: str,
    meal_date: str,
    meal_slot: str
) -> Dict[str, Any]:
    """
    Remove a recipe from a meal slot.

    Args:
        plan_id: Plan identifier
        meal_date: Date YYYY-MM-DD
        meal_slot: 'breakfast', 'lunch', 'dinner', or 'snack'

    Returns:
        Confirmation of removal
    """
    ensure_initialized()

    if meal_slot not in VALID_MEAL_SLOTS:
        return {
            "success": False,
            "error": f"Invalid meal_slot. Must be one of: {VALID_MEAL_SLOTS}"
        }

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            DELETE FROM meal_entries
            WHERE plan_id = ? AND meal_date = ? AND meal_slot = ?
        """, (plan_id, meal_date, meal_slot))
        conn.commit()

        if cursor.rowcount == 0:
            return {
                "success": False,
                "error": f"No meal found at {meal_slot} on {meal_date}"
            }

        return {
            "success": True,
            "message": f"Removed {meal_slot} on {meal_date}"
        }
    finally:
        conn.close()


def swap_meals(
    plan_id: str,
    date1: str,
    slot1: str,
    date2: str,
    slot2: str
) -> Dict[str, Any]:
    """
    Swap two meal assignments within the same plan.

    Args:
        plan_id: Plan identifier
        date1, slot1: First meal
        date2, slot2: Second meal

    Returns:
        Confirmation of swap
    """
    ensure_initialized()

    for slot in [slot1, slot2]:
        if slot not in VALID_MEAL_SLOTS:
            return {
                "success": False,
                "error": f"Invalid meal_slot '{slot}'. Must be one of: {VALID_MEAL_SLOTS}"
            }

    conn = get_db_connection()
    try:
        # Get both entries
        cursor = conn.execute("""
            SELECT meal_date, meal_slot, recipe_id, servings_override, notes
            FROM meal_entries
            WHERE plan_id = ? AND
                  ((meal_date = ? AND meal_slot = ?) OR
                   (meal_date = ? AND meal_slot = ?))
        """, (plan_id, date1, slot1, date2, slot2))

        entries = {(r[0], r[1]): r for r in cursor.fetchall()}

        entry1 = entries.get((date1, slot1))
        entry2 = entries.get((date2, slot2))

        if not entry1 and not entry2:
            return {
                "success": False,
                "error": "Neither meal slot has an assignment"
            }

        # Perform swap
        # Delete both
        conn.execute("""
            DELETE FROM meal_entries
            WHERE plan_id = ? AND
                  ((meal_date = ? AND meal_slot = ?) OR
                   (meal_date = ? AND meal_slot = ?))
        """, (plan_id, date1, slot1, date2, slot2))

        # Re-insert swapped
        now = datetime.now().isoformat()

        if entry1:
            conn.execute("""
                INSERT INTO meal_entries
                (plan_id, recipe_id, meal_date, meal_slot,
                 servings_override, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (plan_id, entry1[2], date2, slot2, entry1[3], entry1[4], now))

        if entry2:
            conn.execute("""
                INSERT INTO meal_entries
                (plan_id, recipe_id, meal_date, meal_slot,
                 servings_override, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (plan_id, entry2[2], date1, slot1, entry2[3], entry2[4], now))

        conn.commit()

        return {
            "success": True,
            "message": f"Swapped {slot1} on {date1} with {slot2} on {date2}"
        }
    finally:
        conn.close()


def bulk_assign_meals(
    plan_id: str,
    assignments: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Assign multiple meals at once.

    Args:
        plan_id: Plan identifier
        assignments: List of dicts with recipe_id, meal_date, meal_slot,
                    and optional servings_override

    Returns:
        Summary of assignments
    """
    ensure_initialized()

    if not assignments:
        return {
            "success": False,
            "error": "No assignments provided"
        }

    results = {
        "success": True,
        "assigned": 0,
        "failed": 0,
        "errors": []
    }

    for assignment in assignments:
        result = assign_meal(
            plan_id=plan_id,
            recipe_id=assignment.get('recipe_id', ''),
            meal_date=assignment.get('meal_date', ''),
            meal_slot=assignment.get('meal_slot', ''),
            servings_override=assignment.get('servings_override'),
            notes=assignment.get('notes')
        )

        if result.get('success'):
            results['assigned'] += 1
        else:
            results['failed'] += 1
            results['errors'].append({
                "assignment": assignment,
                "error": result.get('error')
            })

    results['message'] = f"Assigned {results['assigned']} meals"
    if results['failed'] > 0:
        results['message'] += f", {results['failed']} failed"

    return results


# ============== Shopping Integration ==============


def get_meal_entries_for_dates(
    plan_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get meal entries for a date range (optionally filtered by plan).

    Args:
        plan_id: Optional plan to filter by
        start_date: Start of date range YYYY-MM-DD
        end_date: End of date range YYYY-MM-DD

    Returns:
        List of meal entries with recipe info
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        query = """
            SELECT me.*, mp.name as plan_name
            FROM meal_entries me
            JOIN meal_plans mp ON me.plan_id = mp.id
            WHERE 1=1
        """
        params: List[Any] = []

        if plan_id:
            query += " AND me.plan_id = ?"
            params.append(plan_id)

        if start_date:
            query += " AND me.meal_date >= ?"
            params.append(start_date)

        if end_date:
            query += " AND me.meal_date <= ?"
            params.append(end_date)

        query += " ORDER BY me.meal_date, me.meal_slot"

        cursor = conn.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def generate_meal_plan_shopping_list(
    plan_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    days_ahead: Optional[int] = None,
    pantry_threshold: int = 30,
    combine_duplicates: bool = True,
    skip_items: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate shopping list for meal plan(s).

    Can specify meals by:
    - plan_id: All meals in a specific plan
    - start_date + end_date: All meals in date range
    - days_ahead: Next N days from today

    Args:
        plan_id: Specific plan to shop for
        start_date: Start of date range
        end_date: End of date range
        days_ahead: Days from today to include
        pantry_threshold: Skip items above this pantry level
        combine_duplicates: Merge same ingredients
        skip_items: Ingredient names to skip

    Returns:
        Shopping list with items categorized by action
    """
    ensure_initialized()

    skip_items = skip_items or []

    # Determine date range
    if days_ahead is not None:
        start_date = _format_date(datetime.now())
        end_date = _format_date(datetime.now() + timedelta(days=days_ahead - 1))
    elif plan_id and not start_date:
        # Get dates from plan
        plan_result = get_meal_plan(plan_id, include_recipe_details=False)
        if not plan_result.get('success'):
            return plan_result
        start_date = plan_result['plan']['start_date']
        end_date = plan_result['plan']['end_date']

    if not start_date or not end_date:
        return {
            "success": False,
            "error": "Must specify plan_id, date range, or days_ahead"
        }

    # Get meal entries
    entries = get_meal_entries_for_dates(plan_id, start_date, end_date)

    if not entries:
        return {
            "success": True,
            "message": "No meals found for the specified date range",
            "date_range": {"start": start_date, "end": end_date},
            "ingredients": [],
            "recipes_included": [],
            "summary": {
                "items_to_add": 0,
                "items_to_skip": 0,
                "items_unknown": 0
            }
        }

    # Get pantry context
    pantry_context: Dict[str, Dict[str, Any]] = {}
    try:
        pantry_items = get_pantry_status(apply_depletion=True)
        for item in pantry_items:
            pantry_context[item['product_id']] = {
                "level_percent": item.get("level_percent", 0),
                "status": item.get("status"),
                "days_until_empty": item.get("days_until_empty"),
                "description": item.get("description")
            }
    except Exception:
        pass

    # Collect all ingredients from all recipes
    all_ingredients: Dict[str, Dict[str, Any]] = {}
    recipes_included = []
    recipe_info: Dict[str, Dict[str, Any]] = {}

    for entry in entries:
        recipe_id = entry['recipe_id']
        recipe = get_recipe(recipe_id)

        if not recipe:
            continue

        servings_override = entry.get('servings_override')
        base_servings = recipe.get('servings', 4)
        scale = servings_override / base_servings if servings_override else 1.0

        if recipe_id not in recipe_info:
            recipe_info[recipe_id] = {
                "recipe_id": recipe_id,
                "recipe_name": recipe.get('name'),
                "times_used": 0
            }
        recipe_info[recipe_id]['times_used'] += 1

        for ing in recipe.get('ingredients', []):
            ing_name = ing.get('name', 'Unknown')
            product_id = ing.get('product_id')
            quantity = (ing.get('quantity') or 1) * scale
            unit = ing.get('unit', '')

            # Key for combining
            key = product_id if product_id else ing_name.lower()

            if combine_duplicates and key in all_ingredients:
                existing = all_ingredients[key]
                if existing.get('unit') == unit:
                    existing['quantity'] += quantity
                existing['from_recipes'].append(recipe.get('name'))
            else:
                all_ingredients[key] = {
                    "name": ing_name,
                    "quantity": quantity,
                    "unit": unit,
                    "product_id": product_id,
                    "from_recipes": [recipe.get('name')]
                }

    recipes_included = list(recipe_info.values())

    # Categorize ingredients
    items_to_add = []
    items_to_skip = []
    items_unknown = []

    def _matches_skip(name: str) -> bool:
        name_lower = name.lower()
        for skip in skip_items:
            skip_lower = skip.lower()
            if skip_lower in name_lower or name_lower in skip_lower:
                return True
        return False

    for key, ing in all_ingredients.items():
        product_id = ing.get('product_id')
        name = ing.get('name', 'Unknown')

        # Check user skip list
        user_skip = _matches_skip(name)

        # Check pantry
        pantry = pantry_context.get(product_id, {}) if product_id else {}
        pantry_level = pantry.get('level_percent')

        # Try fuzzy pantry match if no product_id
        if not product_id and not pantry_level:
            pantry_match = match_ingredient_to_pantry(name, None)
            if pantry_match:
                pantry_level = pantry_match.get('level_percent')
                pantry = {
                    "level_percent": pantry_level,
                    "description": pantry_match.get('description')
                }

        in_pantry = pantry_level is not None

        # Determine action
        if user_skip:
            action = "SKIP"
            reason = "User specified to skip"
        elif in_pantry and pantry_level >= pantry_threshold:
            action = "SKIP"
            reason = f"Pantry: {pantry_level}% remaining"
        elif not product_id:
            action = "UNKNOWN"
            reason = "No product linked - search needed"
        else:
            action = "ADD"
            if in_pantry:
                reason = f"Pantry low: {pantry_level}%"
            else:
                reason = "Not in pantry"

        ingredient_info = {
            "name": name,
            "quantity": round(ing['quantity'], 2) if ing['quantity'] else 1,
            "unit": ing.get('unit', ''),
            "product_id": product_id,
            "from_recipes": list(set(ing['from_recipes'])),
            "action": action,
            "reason": reason,
            "pantry_level": pantry_level
        }

        if action == "ADD":
            items_to_add.append(ingredient_info)
        elif action == "SKIP":
            items_to_skip.append(ingredient_info)
        else:
            items_unknown.append(ingredient_info)

    return {
        "success": True,
        "date_range": {
            "start": start_date,
            "end": end_date,
            "days_count": (_parse_date(end_date) - _parse_date(start_date)).days + 1
        },
        "meals_included": len(entries),
        "recipes_included": recipes_included,
        "ingredients": items_to_add + items_to_skip + items_unknown,
        "items_to_add": items_to_add,
        "items_to_skip": items_to_skip,
        "items_unknown": items_unknown,
        "summary": {
            "items_to_add": len(items_to_add),
            "items_to_skip": len(items_to_skip),
            "items_unknown": len(items_unknown),
            "total_ingredients": len(all_ingredients)
        }
    }


# ============== Utility Functions ==============


def get_week_view(start_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Get a calendar-style view of meals for a week.

    Args:
        start_date: Monday of the week (defaults to current week)

    Returns:
        Week view with meals for each day
    """
    ensure_initialized()

    if start_date:
        try:
            week_start = _parse_date(start_date)
        except ValueError:
            return {
                "success": False,
                "error": "Invalid start_date format. Use YYYY-MM-DD"
            }
    else:
        # Get Monday of current week
        today = datetime.now()
        days_since_monday = today.weekday()
        week_start = today - timedelta(days=days_since_monday)

    week_end = week_start + timedelta(days=6)

    # Get all entries for this week
    entries = get_meal_entries_for_dates(
        start_date=_format_date(week_start),
        end_date=_format_date(week_end)
    )

    # Organize by date
    entries_by_date: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for entry in entries:
        date = entry['meal_date']
        slot = entry['meal_slot']
        if date not in entries_by_date:
            entries_by_date[date] = {}

        recipe = get_recipe(entry['recipe_id'])
        entries_by_date[date][slot] = {
            "recipe_id": entry['recipe_id'],
            "recipe_name": recipe.get('name') if recipe else entry['recipe_id'],
            "servings": entry.get('servings_override') or (
                recipe.get('servings', 4) if recipe else 4
            )
        }

    # Build week view
    day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                 'Friday', 'Saturday', 'Sunday']
    days = []

    for i in range(7):
        day_dt = week_start + timedelta(days=i)
        day_str = _format_date(day_dt)
        day_meals = entries_by_date.get(day_str, {})

        days.append({
            "date": day_str,
            "day_name": day_names[i],
            "meals": {
                "breakfast": day_meals.get('breakfast'),
                "lunch": day_meals.get('lunch'),
                "dinner": day_meals.get('dinner'),
                "snack": day_meals.get('snack')
            },
            "meal_count": len(day_meals)
        })

    return {
        "success": True,
        "week_start": _format_date(week_start),
        "week_end": _format_date(week_end),
        "days": days,
        "total_meals": len(entries)
    }


def get_meal_plan_summary(plan_id: str) -> Dict[str, Any]:
    """
    Get summary statistics for a meal plan.

    Args:
        plan_id: Plan identifier

    Returns:
        Summary with meal counts, recipe stats, and pantry readiness
    """
    ensure_initialized()

    plan_result = get_meal_plan(plan_id, include_recipe_details=True)
    if not plan_result.get('success'):
        return plan_result

    plan = plan_result['plan']
    meals_by_date = plan_result.get('meals_by_date', {})

    # Count by slot
    slot_counts = {'breakfast': 0, 'lunch': 0, 'dinner': 0, 'snack': 0}
    for date_meals in meals_by_date.values():
        for slot in date_meals:
            if slot in slot_counts:
                slot_counts[slot] += 1

    # Calculate coverage
    start_dt = _parse_date(plan['start_date'])
    end_dt = _parse_date(plan['end_date'])
    days_count = (end_dt - start_dt).days + 1
    max_meals = days_count * 4  # 4 slots per day
    coverage = plan_result['meal_count'] / max_meals if max_meals > 0 else 0

    # Check pantry readiness
    shopping = generate_meal_plan_shopping_list(plan_id=plan_id)

    return {
        "success": True,
        "plan_id": plan_id,
        "plan_name": plan['name'],
        "date_range": {
            "start": plan['start_date'],
            "end": plan['end_date'],
            "days": days_count
        },
        "meal_counts": {
            "total": plan_result['meal_count'],
            "by_slot": slot_counts
        },
        "recipes": {
            "unique_count": plan_result['unique_recipes'],
            "list": plan_result['recipe_summary']
        },
        "coverage": round(coverage * 100, 1),
        "pantry_readiness": {
            "items_needed": shopping.get('summary', {}).get('items_to_add', 0),
            "items_available": shopping.get('summary', {}).get('items_to_skip', 0),
            "items_unknown": shopping.get('summary', {}).get('items_unknown', 0)
        }
    }
