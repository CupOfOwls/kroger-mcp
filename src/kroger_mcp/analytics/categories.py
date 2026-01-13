"""
Item categorization - automatic detection and manual override.

Categories:
- routine: Purchased every 1-14 days (milk, bread, eggs)
- regular: Purchased every 15-60 days (cleaning supplies, seasonings)
- treat: Seasonal/holiday patterns (turkey, candy)
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized
from .config import load_config


@dataclass
class CategoryResult:
    """Result of a category change."""
    product_id: str
    category: str
    previous_category: Optional[str]
    was_override: bool


def detect_category(
    avg_days: Optional[float],
    seasonality_score: float,
    total_purchases: int
) -> str:
    """
    Auto-detect product category based on purchase patterns.

    Uses configurable thresholds from config.py.

    Args:
        avg_days: Average days between purchases
        seasonality_score: 0-1 score (higher = more seasonal)
        total_purchases: Total number of purchases

    Returns:
        Category string: 'routine', 'regular', 'treat', or 'uncategorized'
    """
    config = load_config()

    # Need at least 3 purchases for reliable detection
    if total_purchases < 3:
        return 'uncategorized'

    # Check for seasonal patterns first
    if seasonality_score > config.seasonality_threshold:
        return 'treat'

    # No average days means not enough data
    if avg_days is None:
        return 'uncategorized'

    # Frequency-based categorization (using config thresholds)
    if avg_days <= config.routine_max_days:
        return 'routine'
    elif avg_days <= config.regular_max_days:
        return 'regular'
    else:
        # Infrequent purchases - could be treat or just rare
        if seasonality_score > 0.4:
            return 'treat'
        return 'regular'


def set_product_category(
    product_id: str,
    category: str,
    is_override: bool = True
) -> CategoryResult:
    """
    Set the category for a product.

    Args:
        product_id: The product identifier
        category: Category to set ('routine', 'regular', 'treat')
        is_override: Whether this is a manual override

    Returns:
        CategoryResult with change details
    """
    ensure_initialized()

    valid_categories = ['routine', 'regular', 'treat', 'uncategorized']
    if category not in valid_categories:
        raise ValueError(f"Invalid category: {category}")

    conn = get_db_connection()
    try:
        # Get current category
        cursor = conn.execute(
            "SELECT category_type, category_override FROM products WHERE product_id = ?",
            (product_id,)
        )
        row = cursor.fetchone()

        if row:
            previous = row['category_type']
            was_override = bool(row['category_override'])

            # Update category
            conn.execute("""
                UPDATE products
                SET category_type = ?, category_override = ?, updated_at = ?
                WHERE product_id = ?
            """, (category, 1 if is_override else 0, datetime.now().isoformat(),
                  product_id))
        else:
            previous = None
            was_override = False

            # Insert new product with category
            conn.execute("""
                INSERT INTO products (product_id, category_type, category_override, created_at)
                VALUES (?, ?, ?, ?)
            """, (product_id, category, 1 if is_override else 0,
                  datetime.now().isoformat()))

        conn.commit()

        return CategoryResult(
            product_id=product_id,
            category=category,
            previous_category=previous,
            was_override=was_override
        )
    finally:
        conn.close()


def get_product_category(product_id: str) -> Optional[str]:
    """
    Get the category for a product.

    Args:
        product_id: The product identifier

    Returns:
        Category string or None if not found
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT category_type FROM products WHERE product_id = ?",
            (product_id,)
        )
        row = cursor.fetchone()
        return row['category_type'] if row else None
    finally:
        conn.close()


def get_items_by_category(
    category: str,
    include_stats: bool = True
) -> List[Dict[str, Any]]:
    """
    Get all items in a specific category.

    Args:
        category: Category to filter by
        include_stats: Whether to include statistics

    Returns:
        List of product dictionaries
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        if include_stats:
            cursor = conn.execute("""
                SELECT p.*, ps.total_purchases, ps.avg_days_between_purchases,
                       ps.last_purchase_date, ps.seasonality_score
                FROM products p
                LEFT JOIN product_statistics ps ON p.product_id = ps.product_id
                WHERE p.category_type = ?
                ORDER BY p.description
            """, (category,))
        else:
            cursor = conn.execute("""
                SELECT * FROM products
                WHERE category_type = ?
                ORDER BY description
            """, (category,))

        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_category_summary() -> Dict[str, int]:
    """
    Get count of items in each category.

    Returns:
        Dict with category names as keys and counts as values
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT category_type, COUNT(*) as count
            FROM products
            GROUP BY category_type
        """)

        result = {}
        for row in cursor.fetchall():
            result[row['category_type'] or 'uncategorized'] = row['count']

        return result
    finally:
        conn.close()


def auto_categorize_all() -> Dict[str, Any]:
    """
    Run auto-categorization on all products that don't have manual overrides.

    Returns:
        Summary of categorization changes
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get products without manual override
        cursor = conn.execute("""
            SELECT p.product_id, ps.avg_days_between_purchases,
                   ps.seasonality_score, ps.total_purchases
            FROM products p
            LEFT JOIN product_statistics ps ON p.product_id = ps.product_id
            WHERE p.category_override = 0 OR p.category_override IS NULL
        """)

        changes = {'routine': 0, 'regular': 0, 'treat': 0, 'uncategorized': 0}

        for row in cursor.fetchall():
            new_category = detect_category(
                avg_days=row['avg_days_between_purchases'],
                seasonality_score=row['seasonality_score'] or 0.0,
                total_purchases=row['total_purchases'] or 0
            )

            conn.execute("""
                UPDATE products
                SET category_type = ?, updated_at = ?
                WHERE product_id = ?
            """, (new_category, datetime.now().isoformat(), row['product_id']))

            changes[new_category] = changes.get(new_category, 0) + 1

        conn.commit()

        return {
            'success': True,
            'categorized': changes,
            'total': sum(changes.values())
        }
    finally:
        conn.close()
