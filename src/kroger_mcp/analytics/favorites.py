"""
Favorite lists management for the Kroger MCP server.

Provides core functions for managing named favorite lists and items,
integrating with the pantry system for smart reordering.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import get_db_cursor, ensure_initialized


# ========== Helper Functions ==========


def get_all_favorite_product_ids() -> set:
    """
    Get all product IDs across all favorite lists.

    Returns a set of product_ids for fast O(1) lookup when checking
    if a product is in any favorites list.

    Returns:
        Set of product_id strings
    """
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute("SELECT DISTINCT product_id FROM favorite_list_items")
        return {row["product_id"] for row in cursor.fetchall()}


# ========== List Management ==========


def create_list(
    name: str,
    description: Optional[str] = None,
    list_type: str = "custom"
) -> Dict[str, Any]:
    """
    Create a new favorite list.

    Args:
        name: List name (must be unique)
        description: Optional description
        list_type: Type of list ('custom', 'weekly', 'monthly', 'seasonal')

    Returns:
        Dict with list_id and success status
    """
    ensure_initialized()

    # Generate a URL-safe ID from the name
    list_id = f"{name.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}"

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO favorite_lists (id, name, description, list_type)
                VALUES (?, ?, ?, ?)
                """,
                (list_id, name, description, list_type)
            )
            return {
                "success": True,
                "list_id": list_id,
                "name": name,
                "list_type": list_type
            }
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return {
                "success": False,
                "error": f"A list named '{name}' already exists"
            }
        return {"success": False, "error": str(e)}


def get_lists() -> List[Dict[str, Any]]:
    """
    Get all favorite lists with item counts.

    Returns:
        List of lists with id, name, description, item_count, etc.
    """
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                fl.id,
                fl.name,
                fl.description,
                fl.list_type,
                fl.created_at,
                fl.updated_at,
                COUNT(fli.product_id) as item_count
            FROM favorite_lists fl
            LEFT JOIN favorite_list_items fli ON fl.id = fli.list_id
            GROUP BY fl.id
            ORDER BY
                CASE WHEN fl.id = 'default' THEN 0 ELSE 1 END,
                fl.name
            """
        )
        rows = cursor.fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "list_type": row["list_type"],
            "item_count": row["item_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "is_default": row["id"] == "default"
        }
        for row in rows
    ]


def get_list(list_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single list by ID.

    Args:
        list_id: The list ID

    Returns:
        List details or None if not found
    """
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                fl.id,
                fl.name,
                fl.description,
                fl.list_type,
                fl.created_at,
                fl.updated_at,
                COUNT(fli.product_id) as item_count
            FROM favorite_lists fl
            LEFT JOIN favorite_list_items fli ON fl.id = fli.list_id
            WHERE fl.id = ?
            GROUP BY fl.id
            """,
            (list_id,)
        )
        row = cursor.fetchone()

    if not row:
        return None

    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "list_type": row["list_type"],
        "item_count": row["item_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "is_default": row["id"] == "default"
    }


def rename_list(
    list_id: str,
    new_name: Optional[str] = None,
    new_description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Rename a list or update its description.

    Args:
        list_id: The list ID
        new_name: New name (optional)
        new_description: New description (optional)

    Returns:
        Success status
    """
    ensure_initialized()

    if list_id == "default":
        return {
            "success": False,
            "error": "Cannot rename the default list"
        }

    if not new_name and new_description is None:
        return {
            "success": False,
            "error": "Must provide new_name or new_description"
        }

    try:
        with get_db_cursor() as cursor:
            updates = []
            params = []

            if new_name:
                updates.append("name = ?")
                params.append(new_name)

            if new_description is not None:
                updates.append("description = ?")
                params.append(new_description)

            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(list_id)

            cursor.execute(
                f"""
                UPDATE favorite_lists
                SET {', '.join(updates)}
                WHERE id = ?
                """,
                params
            )

            if cursor.rowcount == 0:
                return {
                    "success": False,
                    "error": f"List '{list_id}' not found"
                }

            return {"success": True, "list_id": list_id}
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return {
                "success": False,
                "error": f"A list named '{new_name}' already exists"
            }
        return {"success": False, "error": str(e)}


def delete_list(list_id: str) -> Dict[str, Any]:
    """
    Delete a list and all its items.

    Args:
        list_id: The list ID (cannot be 'default')

    Returns:
        Success status
    """
    ensure_initialized()

    if list_id == "default":
        return {
            "success": False,
            "error": "Cannot delete the default list"
        }

    with get_db_cursor() as cursor:
        # Get item count before deletion
        cursor.execute(
            "SELECT COUNT(*) as cnt FROM favorite_list_items WHERE list_id = ?",
            (list_id,)
        )
        item_count = cursor.fetchone()["cnt"]

        # Delete the list (cascade deletes items)
        cursor.execute("DELETE FROM favorite_lists WHERE id = ?", (list_id,))

        if cursor.rowcount == 0:
            return {
                "success": False,
                "error": f"List '{list_id}' not found"
            }

        return {
            "success": True,
            "list_id": list_id,
            "items_deleted": item_count
        }


# ========== Item Management ==========


def add_to_list(
    list_id: str,
    product_id: str,
    description: str,
    brand: Optional[str] = None,
    default_quantity: int = 1,
    preferred_modality: str = "PICKUP",
    notes: Optional[str] = None
) -> Dict[str, Any]:
    """
    Add a product to a favorite list.

    Args:
        list_id: The list ID
        product_id: Kroger product ID
        description: Product description
        brand: Product brand (optional)
        default_quantity: Default quantity when ordering
        preferred_modality: PICKUP or DELIVERY
        notes: Optional notes

    Returns:
        Success status
    """
    ensure_initialized()

    # Verify list exists
    lst = get_list(list_id)
    if not lst:
        return {
            "success": False,
            "error": f"List '{list_id}' not found"
        }

    try:
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO favorite_list_items
                (list_id, product_id, description, brand, default_quantity,
                 preferred_modality, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (list_id, product_id, description, brand, default_quantity,
                 preferred_modality, notes)
            )

            # Update list's updated_at
            cursor.execute(
                "UPDATE favorite_lists SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), list_id)
            )

            return {
                "success": True,
                "list_id": list_id,
                "product_id": product_id,
                "description": description
            }
    except Exception as e:
        if "UNIQUE constraint" in str(e):
            return {
                "success": False,
                "error": f"Product '{product_id}' is already in list '{lst['name']}'"
            }
        return {"success": False, "error": str(e)}


def bulk_add_to_list(
    list_id: str,
    items: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Add multiple products to a favorite list in one operation.

    Args:
        list_id: The list ID
        items: List of items, each with:
            - product_id (required): Kroger product ID
            - description (required): Product description
            - brand (optional): Product brand
            - default_quantity (optional): Default quantity (default 1)
            - preferred_modality (optional): PICKUP or DELIVERY (default PICKUP)
            - notes (optional): Notes

    Returns:
        Success status with counts of added/failed items
    """
    ensure_initialized()

    # Verify list exists
    lst = get_list(list_id)
    if not lst:
        return {
            "success": False,
            "error": f"List '{list_id}' not found"
        }

    added = []
    failed = []

    with get_db_cursor() as cursor:
        for item in items:
            product_id = item.get("product_id")
            description = item.get("description")

            if not product_id or not description:
                failed.append({
                    "product_id": product_id,
                    "error": "Missing required field: product_id or description"
                })
                continue

            try:
                cursor.execute(
                    """
                    INSERT INTO favorite_list_items
                    (list_id, product_id, description, brand, default_quantity,
                     preferred_modality, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        list_id,
                        product_id,
                        description,
                        item.get("brand"),
                        item.get("default_quantity", 1),
                        item.get("preferred_modality", "PICKUP"),
                        item.get("notes")
                    )
                )
                added.append({
                    "product_id": product_id,
                    "description": description
                })
            except Exception as e:
                if "UNIQUE constraint" in str(e):
                    failed.append({
                        "product_id": product_id,
                        "error": "Already in list"
                    })
                else:
                    failed.append({
                        "product_id": product_id,
                        "error": str(e)
                    })

        # Update list's updated_at if any items were added
        if added:
            cursor.execute(
                "UPDATE favorite_lists SET updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), list_id)
            )

    return {
        "success": len(added) > 0,
        "list_id": list_id,
        "list_name": lst["name"],
        "added": added,
        "failed": failed,
        "added_count": len(added),
        "failed_count": len(failed)
    }


def remove_from_list(list_id: str, product_id: str) -> Dict[str, Any]:
    """
    Remove a product from a favorite list.

    Args:
        list_id: The list ID
        product_id: Kroger product ID

    Returns:
        Success status
    """
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            "DELETE FROM favorite_list_items WHERE list_id = ? AND product_id = ?",
            (list_id, product_id)
        )

        if cursor.rowcount == 0:
            return {
                "success": False,
                "error": f"Product '{product_id}' not found in list '{list_id}'"
            }

        # Update list's updated_at
        cursor.execute(
            "UPDATE favorite_lists SET updated_at = ? WHERE id = ?",
            (datetime.now().isoformat(), list_id)
        )

        return {
            "success": True,
            "list_id": list_id,
            "product_id": product_id
        }


def get_list_items(
    list_id: str,
    include_pantry_status: bool = True,
    sort_by: str = "description"
) -> Dict[str, Any]:
    """
    Get all items in a favorite list with optional pantry status.

    Args:
        list_id: The list ID
        include_pantry_status: Include current pantry levels
        sort_by: Sort field ('description', 'times_ordered', 'added_at')

    Returns:
        Dict with list info and items
    """
    ensure_initialized()

    # Get list info
    lst = get_list(list_id)
    if not lst:
        return {
            "success": False,
            "error": f"List '{list_id}' not found"
        }

    # Determine sort order
    sort_column = {
        "description": "fli.description",
        "times_ordered": "fli.times_ordered DESC",
        "added_at": "fli.added_at DESC"
    }.get(sort_by, "fli.description")

    with get_db_cursor() as cursor:
        if include_pantry_status:
            cursor.execute(
                f"""
                SELECT
                    fli.product_id,
                    fli.description,
                    fli.brand,
                    fli.default_quantity,
                    fli.preferred_modality,
                    fli.notes,
                    fli.added_at,
                    fli.times_ordered,
                    pi.level_percent,
                    pi.daily_depletion_rate,
                    pi.low_threshold
                FROM favorite_list_items fli
                LEFT JOIN pantry_items pi ON fli.product_id = pi.product_id
                WHERE fli.list_id = ?
                ORDER BY {sort_column}
                """,
                (list_id,)
            )
        else:
            cursor.execute(
                f"""
                SELECT
                    fli.product_id,
                    fli.description,
                    fli.brand,
                    fli.default_quantity,
                    fli.preferred_modality,
                    fli.notes,
                    fli.added_at,
                    fli.times_ordered
                FROM favorite_list_items fli
                WHERE fli.list_id = ?
                ORDER BY {sort_column}
                """,
                (list_id,)
            )

        rows = cursor.fetchall()

    items = []
    for row in rows:
        item = {
            "product_id": row["product_id"],
            "description": row["description"],
            "brand": row["brand"],
            "default_quantity": row["default_quantity"],
            "preferred_modality": row["preferred_modality"],
            "notes": row["notes"],
            "added_at": row["added_at"],
            "times_ordered": row["times_ordered"]
        }

        if include_pantry_status:
            level = row["level_percent"]
            if level is not None:
                threshold = row["low_threshold"] or 20
                depletion = row["daily_depletion_rate"] or 0

                days_until_empty = None
                if depletion > 0:
                    days_until_empty = round(level / depletion, 1)

                item["pantry_status"] = {
                    "tracked": True,
                    "level_percent": level,
                    "days_until_empty": days_until_empty,
                    "is_low": level < threshold,
                    "needs_reorder": level < threshold
                }
            else:
                item["pantry_status"] = {
                    "tracked": False,
                    "level_percent": None,
                    "needs_reorder": None
                }

        items.append(item)

    return {
        "success": True,
        "list": lst,
        "items": items,
        "total_items": len(items)
    }


def update_list_item(
    list_id: str,
    product_id: str,
    **kwargs
) -> Dict[str, Any]:
    """
    Update an item in a favorite list.

    Args:
        list_id: The list ID
        product_id: Kroger product ID
        **kwargs: Fields to update (default_quantity, preferred_modality, notes)

    Returns:
        Success status
    """
    ensure_initialized()

    allowed_fields = {"default_quantity", "preferred_modality", "notes"}
    updates = {k: v for k, v in kwargs.items() if k in allowed_fields and v is not None}

    if not updates:
        return {
            "success": False,
            "error": "No valid fields to update"
        }

    set_clause = ", ".join(f"{k} = ?" for k in updates.keys())
    params = list(updates.values()) + [list_id, product_id]

    with get_db_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE favorite_list_items
            SET {set_clause}
            WHERE list_id = ? AND product_id = ?
            """,
            params
        )

        if cursor.rowcount == 0:
            return {
                "success": False,
                "error": f"Product '{product_id}' not found in list '{list_id}'"
            }

        return {
            "success": True,
            "list_id": list_id,
            "product_id": product_id,
            "updated_fields": list(updates.keys())
        }


def increment_times_ordered(list_id: str, product_ids: List[str]) -> None:
    """
    Increment the times_ordered counter for products that were ordered.

    Args:
        list_id: The list ID
        product_ids: List of product IDs that were ordered
    """
    ensure_initialized()

    if not product_ids:
        return

    placeholders = ", ".join("?" * len(product_ids))
    with get_db_cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE favorite_list_items
            SET times_ordered = times_ordered + 1
            WHERE list_id = ? AND product_id IN ({placeholders})
            """,
            [list_id] + product_ids
        )


# ========== Smart Features ==========


def get_items_needing_reorder(
    list_id: str = "default",
    pantry_threshold: int = 30
) -> Dict[str, Any]:
    """
    Get items from a list that need reordering based on pantry levels.

    Args:
        list_id: The list ID
        pantry_threshold: Pantry level below which items need reorder

    Returns:
        Dict with items needing reorder
    """
    ensure_initialized()

    lst = get_list(list_id)
    if not lst:
        return {
            "success": False,
            "error": f"List '{list_id}' not found"
        }

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT
                fli.product_id,
                fli.description,
                fli.brand,
                fli.default_quantity,
                fli.preferred_modality,
                pi.level_percent,
                pi.daily_depletion_rate
            FROM favorite_list_items fli
            LEFT JOIN pantry_items pi ON fli.product_id = pi.product_id
            WHERE fli.list_id = ?
              AND (pi.level_percent IS NULL OR pi.level_percent < ?)
            ORDER BY COALESCE(pi.level_percent, 0) ASC
            """,
            (list_id, pantry_threshold)
        )
        rows = cursor.fetchall()

    items = []
    for row in rows:
        level = row["level_percent"]
        depletion = row["daily_depletion_rate"] or 0

        days_until_empty = None
        if level is not None and depletion > 0:
            days_until_empty = round(level / depletion, 1)

        items.append({
            "product_id": row["product_id"],
            "description": row["description"],
            "brand": row["brand"],
            "default_quantity": row["default_quantity"],
            "preferred_modality": row["preferred_modality"],
            "pantry_level": level,
            "days_until_empty": days_until_empty,
            "in_pantry": level is not None
        })

    return {
        "success": True,
        "list": lst,
        "items_needing_reorder": items,
        "count": len(items),
        "threshold_used": pantry_threshold
    }


def suggest_for_list(
    list_id: Optional[str] = None,
    min_purchases: int = 3,
    min_frequency_score: float = 0.5,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Suggest products to add to favorites based on purchase history.

    Args:
        list_id: If provided, excludes items already in that list
        min_purchases: Minimum number of purchases to be suggested
        min_frequency_score: Minimum frequency score
        limit: Max suggestions to return

    Returns:
        List of suggested products
    """
    ensure_initialized()

    with get_db_cursor() as cursor:
        # Get products already in any list
        if list_id:
            cursor.execute(
                """
                SELECT DISTINCT product_id FROM favorite_list_items
                WHERE list_id = ?
                """,
                (list_id,)
            )
        else:
            cursor.execute("SELECT DISTINCT product_id FROM favorite_list_items")

        existing_products = {row["product_id"] for row in cursor.fetchall()}

        # Get frequently purchased products not in favorites
        cursor.execute(
            """
            SELECT
                p.product_id,
                p.description,
                p.brand,
                ps.total_purchases,
                ps.purchase_frequency_score,
                ps.avg_days_between_purchases,
                ps.last_purchase_date
            FROM products p
            JOIN product_statistics ps ON p.product_id = ps.product_id
            WHERE ps.total_purchases >= ?
              AND ps.purchase_frequency_score >= ?
            ORDER BY ps.purchase_frequency_score DESC, ps.total_purchases DESC
            LIMIT ?
            """,
            (min_purchases, min_frequency_score, limit * 3)  # Get extra to filter
        )
        rows = cursor.fetchall()

    suggestions = []
    for row in rows:
        if row["product_id"] not in existing_products:
            suggestions.append({
                "product_id": row["product_id"],
                "description": row["description"],
                "brand": row["brand"],
                "total_purchases": row["total_purchases"],
                "frequency_score": round(row["purchase_frequency_score"], 2),
                "avg_days_between": (
                    round(row["avg_days_between_purchases"], 1)
                    if row["avg_days_between_purchases"] else None
                ),
                "last_purchased": row["last_purchase_date"]
            })
            if len(suggestions) >= limit:
                break

    return {
        "success": True,
        "suggestions": suggestions,
        "count": len(suggestions),
        "excluded_list": list_id
    }
