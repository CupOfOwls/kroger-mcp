"""
Pantry inventory tracking with auto-depletion.

Tracks estimated inventory levels using percentage-based tracking.
- Auto-depletes based on consumption rate analytics
- Manual adjustments supported
- Low inventory alerts when items drop below threshold
- Automatic expiration date tracking based on product category
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized


# Shelf life in days for common categories
CATEGORY_SHELF_LIFE = {
    'routine': {
        # IMPORTANT: More specific (longer) keywords must come FIRST
        # because matching uses simple substring search

        # Frozen Foods (3-6 months) - MUST BE FIRST due to keyword priority
        'frozen vegetable': 240,
        'frozen fruit': 240,
        'frozen chicken': 180,
        'frozen beef': 180,
        'frozen pork': 180,
        'frozen fish': 120,
        'frozen seafood': 120,
        'frozen pizza': 120,
        'frozen meal': 90,
        'frozen dinner': 90,
        'ice cream': 60,
        'frozen': 120,  # Generic frozen (after specific items)

        # Dairy & Refrigerated
        'sour cream': 14,  # Must come before 'cream'
        'milk': 7,
        'dairy': 7,
        'cheese': 14,
        'yogurt': 14,
        'eggs': 21,
        'butter': 30,
        'cream': 7,

        # Bakery
        'bread': 5,
        'bakery': 5,
        'bagel': 5,
        'roll': 5,
        'tortilla': 7,

        # Fresh Meat & Seafood (Refrigerated)
        'ground': 2,  # Ground meat is shorter shelf life
        'deli': 5,
        'meat': 3,
        'poultry': 3,
        'chicken': 3,
        'beef': 3,
        'pork': 3,
        'seafood': 2,
        'fish': 2,

        # Produce
        'berries': 3,  # Must come before 'berry'
        'berry': 3,
        'lettuce': 5,
        'greens': 5,
        'salad': 5,
        'apple': 14,
        'orange': 14,
        'banana': 5,
        'vegetable': 7,  # Generic after specific
        'fruit': 7,  # Generic after specific
        'produce': 5,
    },
    'regular': {
        # Longer shelf life perishables
        'condiment': 90,
        'juice': 14,
        'refrigerated': 14,
        'sauce': 60,
        'ketchup': 180,
        'mustard': 180,
        'mayonnaise': 60,
    },
    'treat': None,  # Seasonal items typically don't expire quickly
}

# Default fallback (no category match)
DEFAULT_SHELF_LIFE = {
    'routine': 7,    # Weekly items default to 7 days
    'regular': 30,   # Monthly items default to 30 days
    'treat': None    # Seasonal items no default
}


def calculate_depletion_rate(product_id: str) -> float:
    """
    Calculate daily depletion percentage from consumption rate analytics.

    Uses avg_days_between_purchases to estimate how quickly an item is used.

    Example:
    - Milk purchased every 7 days -> 100% / 7 = 14.3% per day
    - Eggs purchased every 14 days -> 100% / 14 = 7.1% per day

    Args:
        product_id: The product identifier

    Returns:
        Daily depletion rate as percentage (0-100)
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT avg_days_between_purchases
            FROM product_statistics
            WHERE product_id = ?
        """, (product_id,))
        row = cursor.fetchone()

        if row and row['avg_days_between_purchases']:
            avg_days = row['avg_days_between_purchases']
            if avg_days > 0:
                return 100.0 / avg_days

        return 0.0  # No data, don't auto-deplete
    finally:
        conn.close()


def get_shelf_life_days(category: str, description: str) -> Optional[int]:
    """
    Determine shelf life days for a product based on category and keywords.

    Scans product description for keyword matches to determine appropriate
    shelf life. Returns None for non-perishable items.

    Args:
        category: Product category ('routine', 'regular', 'treat')
        description: Product description to scan for keywords

    Returns:
        Shelf life in days, or None for non-perishables
    """
    if not category or not description:
        return None

    desc_lower = description.lower()
    category_map = CATEGORY_SHELF_LIFE.get(category, {})

    if category_map is None:
        return None

    # Check for keyword matches
    for keyword, days in category_map.items():
        if keyword in desc_lower:
            return days

    # Fallback to category default
    return DEFAULT_SHELF_LIFE.get(category)


def calculate_expiration_date(
    purchase_date: str,
    category: str,
    description: str
) -> Optional[str]:
    """
    Automatically calculate expiration date based on purchase date and category.

    Args:
        purchase_date: ISO date string (YYYY-MM-DD or full ISO timestamp)
        category: Product category ('routine', 'regular', 'treat')
        description: Product description for keyword matching

    Returns:
        ISO date string (YYYY-MM-DD) or None for non-perishables
    """
    shelf_life = get_shelf_life_days(category, description)
    if not shelf_life:
        return None

    try:
        # Handle both full ISO timestamps and date-only strings
        if 'T' in purchase_date:
            purchase = datetime.fromisoformat(purchase_date).date()
        else:
            purchase = datetime.fromisoformat(purchase_date).date()
        expiration = purchase + timedelta(days=shelf_life)
        return expiration.isoformat()
    except (ValueError, TypeError):
        return None


def calculate_days_to_expiration(expiration_date: Optional[str]) -> Optional[int]:
    """
    Calculate days until expiration from ISO date string.

    Args:
        expiration_date: ISO date string (YYYY-MM-DD)

    Returns:
        Days until expiration (positive for future, negative for past),
        or None if no expiration date
    """
    if not expiration_date:
        return None

    try:
        exp_date = datetime.fromisoformat(expiration_date).date()
        today = datetime.now().date()
        delta = (exp_date - today).days
        return delta
    except (ValueError, TypeError):
        return None


def get_expiration_status(days_to_expiration: Optional[int]) -> str:
    """
    Map days to expiration into status categories.

    Args:
        days_to_expiration: Days until expiration (can be negative)

    Returns:
        Status string: 'expired', 'critical', 'warning', 'ok', 'fresh', or 'none'
    """
    if days_to_expiration is None:
        return 'none'

    if days_to_expiration < 0:
        return 'expired'
    elif days_to_expiration <= 2:
        return 'critical'
    elif days_to_expiration <= 6:
        return 'warning'
    elif days_to_expiration <= 13:
        return 'ok'
    else:
        return 'fresh'


def restock_item(
    product_id: str,
    level: int = 100,
    description: Optional[str] = None
) -> Dict[str, Any]:
    """
    Set item to restocked level (default 100%).

    Called automatically when an order is placed, or manually
    when user restocks from another source.

    AUTOMATIC EXPIRATION TRACKING:
    - Calculates expiration date based on product category and shelf life
    - No user input required - completely automatic!

    Args:
        product_id: The product identifier
        level: Percentage level (0-100), default 100
        description: Product description (optional)

    Returns:
        Dict with success status and item info (includes expiration data)
    """
    ensure_initialized()

    level = max(0, min(100, level))  # Clamp to 0-100
    now = datetime.now().isoformat()

    # Calculate depletion rate from analytics
    depletion_rate = calculate_depletion_rate(product_id)

    conn = get_db_connection()
    try:
        # Get description from products table if not provided
        if not description:
            cursor = conn.execute(
                "SELECT description FROM products WHERE product_id = ?",
                (product_id,)
            )
            row = cursor.fetchone()
            description = row['description'] if row else None

        # Get category from product_statistics for expiration calculation
        cursor = conn.execute(
            "SELECT detected_category FROM product_statistics WHERE product_id = ?",
            (product_id,)
        )
        row = cursor.fetchone()
        category = row['detected_category'] if row else 'regular'

        # AUTO-CALCULATE EXPIRATION DATE (no user input needed!)
        purchase_date = datetime.now().isoformat()
        expiration_date = calculate_expiration_date(
            purchase_date,
            category,
            description or ''
        )
        days_to_exp = calculate_days_to_expiration(expiration_date)

        # Ensure product exists in products table (required for foreign key)
        conn.execute("""
            INSERT INTO products (product_id, description, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                description = COALESCE(excluded.description, products.description),
                updated_at = excluded.updated_at
        """, (product_id, description, now, now))

        # Upsert pantry item WITH expiration tracking
        conn.execute("""
            INSERT INTO pantry_items
            (product_id, description, level_percent, last_restocked_at,
             last_updated_at, daily_depletion_rate, expiration_date, days_to_expiration)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                level_percent = excluded.level_percent,
                last_restocked_at = excluded.last_restocked_at,
                last_updated_at = excluded.last_updated_at,
                daily_depletion_rate = excluded.daily_depletion_rate,
                expiration_date = excluded.expiration_date,
                days_to_expiration = excluded.days_to_expiration,
                description = COALESCE(excluded.description, description)
        """, (product_id, description, level, now, now, depletion_rate,
              expiration_date, days_to_exp))
        conn.commit()

        return {
            'success': True,
            'product_id': product_id,
            'description': description,
            'level_percent': level,
            'daily_depletion_rate': round(depletion_rate, 2),
            'restocked_at': now,
            'expiration_date': expiration_date,
            'days_to_expiration': days_to_exp,
            'auto_calculated': expiration_date is not None
        }
    finally:
        conn.close()


def update_pantry_level(
    product_id: str,
    level: int
) -> Dict[str, Any]:
    """
    Manually set pantry level for an item.

    When level is set to 0 (empty), records a depletion event that feeds
    back into consumption rate calculations for more accurate predictions.

    Args:
        product_id: The product identifier
        level: Percentage level (0-100)

    Returns:
        Dict with success status and updated info
    """
    ensure_initialized()

    level = max(0, min(100, level))  # Clamp to 0-100
    now = datetime.now()
    now_str = now.isoformat()

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT id, last_restocked_at, level_percent FROM pantry_items WHERE product_id = ?",
            (product_id,)
        )
        row = cursor.fetchone()
        if not row:
            return {
                'success': False,
                'error': f"Item '{product_id}' not in pantry. Use add_to_pantry first."
            }

        previous_level = row['level_percent']
        last_restocked = row['last_restocked_at']

        # Record depletion event when item marked as empty (level <= 5%)
        # This feeds back into consumption rate calculations
        depletion_recorded = False
        if level <= 5 and previous_level > 5 and last_restocked:
            depletion_recorded = _record_depletion_event(
                product_id, last_restocked, now_str
            )

        conn.execute("""
            UPDATE pantry_items
            SET level_percent = ?, last_updated_at = ?
            WHERE product_id = ?
        """, (level, now_str, product_id))
        conn.commit()

        result = {
            'success': True,
            'product_id': product_id,
            'level_percent': level,
            'updated_at': now_str
        }

        if depletion_recorded:
            result['depletion_recorded'] = True
            result['message'] = 'Consumption data recorded for better predictions'

        return result
    finally:
        conn.close()


def _record_depletion_event(
    product_id: str,
    last_restocked_at: str,
    depleted_at: str
) -> bool:
    """
    Record a pantry depletion event for consumption analytics.

    This creates a purchase event record that captures the actual consumption
    time between restock and depletion, improving prediction accuracy.

    Args:
        product_id: The product identifier
        last_restocked_at: When the item was last restocked
        depleted_at: When the item was marked as depleted

    Returns:
        True if event was recorded, False otherwise
    """
    try:
        conn = get_db_connection()
        try:
            # Record as a special event type that gets included in consumption calc
            conn.execute("""
                INSERT INTO purchase_events
                (product_id, quantity, event_type, event_date, event_timestamp)
                VALUES (?, 1, 'pantry_depleted', ?, ?)
            """, (
                product_id,
                depleted_at[:10],  # Just the date part
                depleted_at
            ))
            conn.commit()

            # Trigger stats recalculation to incorporate the new data point
            from .statistics import update_product_stats
            update_product_stats(product_id)

            # Update depletion rate based on new stats
            new_rate = calculate_depletion_rate(product_id)
            conn = get_db_connection()
            conn.execute("""
                UPDATE pantry_items
                SET daily_depletion_rate = ?
                WHERE product_id = ?
            """, (new_rate, product_id))
            conn.commit()

            return True
        finally:
            conn.close()
    except Exception:
        return False


def add_to_pantry(
    product_id: str,
    description: Optional[str] = None,
    level: int = 100,
    low_threshold: int = 20,
    auto_deplete: bool = True
) -> Dict[str, Any]:
    """
    Add an item to pantry tracking.

    Args:
        product_id: The product identifier
        description: Product description
        level: Initial percentage level (0-100)
        low_threshold: Alert when level drops below this (default 20%)
        auto_deplete: Enable automatic depletion (default True)

    Returns:
        Dict with success status
    """
    ensure_initialized()

    level = max(0, min(100, level))
    now = datetime.now().isoformat()
    depletion_rate = calculate_depletion_rate(product_id) if auto_deplete else 0

    conn = get_db_connection()
    try:
        # Get description from products table if not provided
        if not description:
            cursor = conn.execute(
                "SELECT description FROM products WHERE product_id = ?",
                (product_id,)
            )
            row = cursor.fetchone()
            description = row['description'] if row else None

        # Ensure product exists in products table (required for foreign key)
        conn.execute("""
            INSERT INTO products (product_id, description, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                description = COALESCE(excluded.description, products.description),
                updated_at = excluded.updated_at
        """, (product_id, description, now, now))

        conn.execute("""
            INSERT INTO pantry_items
            (product_id, description, level_percent, last_restocked_at,
             last_updated_at, auto_deplete, daily_depletion_rate, low_threshold)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                description = COALESCE(excluded.description, description),
                low_threshold = excluded.low_threshold,
                auto_deplete = excluded.auto_deplete
        """, (product_id, description, level, now, now,
              1 if auto_deplete else 0, depletion_rate, low_threshold))
        conn.commit()

        return {
            'success': True,
            'product_id': product_id,
            'description': description,
            'level_percent': level,
            'low_threshold': low_threshold,
            'auto_deplete': auto_deplete
        }
    finally:
        conn.close()


def remove_from_pantry(product_id: str) -> Dict[str, Any]:
    """
    Remove an item from pantry tracking.

    Args:
        product_id: The product identifier

    Returns:
        Dict with success status
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "DELETE FROM pantry_items WHERE product_id = ?",
            (product_id,)
        )
        conn.commit()

        if cursor.rowcount > 0:
            return {'success': True, 'message': f"Removed '{product_id}' from pantry"}
        else:
            return {'success': False, 'error': f"Item '{product_id}' not found"}
    finally:
        conn.close()


def get_pantry_status(apply_depletion: bool = True) -> List[Dict[str, Any]]:
    """
    Get all pantry items with current estimated levels and expiration status.

    If apply_depletion is True, calculates current level based on
    time elapsed since last update and depletion rate.

    EXPIRATION TRACKING:
    - Automatically recalculates days_to_expiration for current date
    - Includes expiration_status ('expired', 'critical', 'warning', 'ok', 'fresh', 'none')

    Args:
        apply_depletion: Whether to calculate current depleted level

    Returns:
        List of pantry items with status info including expiration data
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT product_id, description, level_percent,
                   last_restocked_at, last_updated_at,
                   auto_deplete, daily_depletion_rate, low_threshold,
                   expiration_date, days_to_expiration
            FROM pantry_items
            ORDER BY level_percent ASC
        """)

        items = []
        now = datetime.now()

        for row in cursor.fetchall():
            item = dict(row)
            level = item['level_percent']

            # Apply depletion if enabled
            if apply_depletion and item['auto_deplete'] and item['daily_depletion_rate']:
                last_updated = item['last_updated_at']
                if last_updated:
                    try:
                        last_dt = datetime.fromisoformat(last_updated)
                        days_elapsed = (now - last_dt).total_seconds() / 86400
                        depletion = days_elapsed * item['daily_depletion_rate']
                        level = max(0, level - depletion)
                    except (ValueError, TypeError):
                        pass

            # Calculate days until empty
            days_until_empty = None
            if item['daily_depletion_rate'] and item['daily_depletion_rate'] > 0:
                days_until_empty = round(level / item['daily_depletion_rate'], 1)

            # Determine inventory status
            if level <= 0:
                status = 'out'
            elif level <= item['low_threshold']:
                status = 'low'
            else:
                status = 'ok'

            # LAZY RECALCULATION: Always recalculate days_to_expiration for current date
            exp_date = item['expiration_date']
            days_to_exp = calculate_days_to_expiration(exp_date)
            exp_status = get_expiration_status(days_to_exp)

            items.append({
                'product_id': item['product_id'],
                'description': item['description'],
                'level_percent': round(level),
                'status': status,
                'days_until_empty': days_until_empty,
                'last_restocked': item['last_restocked_at'],
                'low_threshold': item['low_threshold'],
                'auto_deplete': bool(item['auto_deplete']),
                'daily_depletion_rate': round(item['daily_depletion_rate'], 2)
                if item['daily_depletion_rate'] else 0,
                # Expiration tracking (freshly calculated!)
                'expiration_date': exp_date,
                'days_to_expiration': days_to_exp,
                'expiration_status': exp_status
            })

        return items
    finally:
        conn.close()


def get_low_inventory_items(threshold: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Get items below their low threshold.

    Args:
        threshold: Override threshold (use item's own threshold if None)

    Returns:
        List of low inventory items
    """
    items = get_pantry_status(apply_depletion=True)

    low_items = []
    for item in items:
        check_threshold = threshold if threshold is not None else item['low_threshold']
        if item['level_percent'] <= check_threshold:
            low_items.append(item)

    return low_items


def apply_daily_depletion() -> Dict[str, Any]:
    """
    Apply depletion to all pantry items based on their rates.

    This updates the stored level_percent values in the database.
    Can be called periodically or on-demand.

    Returns:
        Summary of updates applied
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        now = datetime.now()
        now_str = now.isoformat()

        cursor = conn.execute("""
            SELECT product_id, level_percent, last_updated_at,
                   daily_depletion_rate
            FROM pantry_items
            WHERE auto_deplete = 1 AND daily_depletion_rate > 0
        """)

        updated_count = 0
        for row in cursor.fetchall():
            last_updated = row['last_updated_at']
            if not last_updated:
                continue

            try:
                last_dt = datetime.fromisoformat(last_updated)
                days_elapsed = (now - last_dt).total_seconds() / 86400

                if days_elapsed < 0.01:  # Skip if < ~15 minutes
                    continue

                depletion = days_elapsed * row['daily_depletion_rate']
                new_level = max(0, row['level_percent'] - depletion)

                conn.execute("""
                    UPDATE pantry_items
                    SET level_percent = ?, last_updated_at = ?
                    WHERE product_id = ?
                """, (round(new_level), now_str, row['product_id']))
                updated_count += 1
            except (ValueError, TypeError):
                continue

        conn.commit()

        return {
            'success': True,
            'items_updated': updated_count,
            'updated_at': now_str
        }
    finally:
        conn.close()


def get_pantry_item(product_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a single pantry item by product ID.

    Args:
        product_id: The product identifier

    Returns:
        Pantry item info or None if not found
    """
    items = get_pantry_status(apply_depletion=True)
    for item in items:
        if item['product_id'] == product_id:
            return item
    return None
