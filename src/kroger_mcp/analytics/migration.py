"""
Migration from JSON storage to SQLite database.

Migrates existing order history and cart data from JSON files to the
new SQLite-based analytics database.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict

from .database import get_db_connection, initialize_database

# File paths (same as cart_tools.py)
CART_FILE = "kroger_cart.json"
ORDER_HISTORY_FILE = "kroger_order_history.json"
MIGRATION_MARKER = ".kroger_analytics_migrated"


def needs_migration() -> bool:
    """
    Check if migration is needed.

    Returns:
        True if migration should run, False otherwise
    """
    # Already migrated
    if os.path.exists(MIGRATION_MARKER):
        return False

    # No data to migrate
    if not os.path.exists(CART_FILE) and not os.path.exists(ORDER_HISTORY_FILE):
        return False

    return True


def migrate_json_to_sqlite() -> Dict[str, Any]:
    """
    Migrate existing JSON data to SQLite database.

    Returns:
        Summary of migrated data
    """
    if not needs_migration():
        return {'already_migrated': True, 'success': True}

    # Initialize database schema
    initialize_database()

    conn = get_db_connection()
    migrated = {'orders': 0, 'items': 0, 'products': set()}

    try:
        # Migrate order history
        if os.path.exists(ORDER_HISTORY_FILE):
            try:
                with open(ORDER_HISTORY_FILE, 'r') as f:
                    order_history = json.load(f)

                for order in order_history:
                    placed_at = order.get('placed_at', datetime.now().isoformat())

                    # Insert order
                    cursor = conn.execute("""
                        INSERT INTO orders
                        (placed_at, item_count, total_quantity, notes)
                        VALUES (?, ?, ?, ?)
                    """, (
                        placed_at,
                        order.get('item_count', 0),
                        order.get('total_quantity', 0),
                        order.get('notes')
                    ))
                    order_id = cursor.lastrowid
                    migrated['orders'] += 1

                    # Insert items
                    for item in order.get('items', []):
                        product_id = item.get('product_id')
                        if not product_id:
                            continue

                        # Ensure product exists
                        _ensure_product_exists(
                            conn, product_id, item, placed_at)
                        migrated['products'].add(product_id)

                        # Parse date from timestamp
                        event_date = placed_at[:10] if placed_at else None

                        # Insert purchase event
                        conn.execute("""
                            INSERT INTO purchase_events
                            (product_id, quantity, event_type, modality,
                             event_date, event_timestamp, order_id)
                            VALUES (?, ?, 'order_placed', ?, ?, ?, ?)
                        """, (
                            product_id,
                            item.get('quantity', 1),
                            item.get('modality'),
                            event_date,
                            placed_at,
                            order_id
                        ))
                        migrated['items'] += 1

            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not read order history: {e}")

        # Migrate current cart (as cart_add events)
        if os.path.exists(CART_FILE):
            try:
                with open(CART_FILE, 'r') as f:
                    cart_data = json.load(f)

                for item in cart_data.get('current_cart', []):
                    product_id = item.get('product_id')
                    if not product_id:
                        continue

                    added_at = item.get('added_at', datetime.now().isoformat())

                    # Ensure product exists
                    _ensure_product_exists(conn, product_id, item, added_at)
                    migrated['products'].add(product_id)

                    # Parse date from timestamp
                    event_date = added_at[:10] if added_at else None

                    # Insert cart_add event
                    conn.execute("""
                        INSERT INTO purchase_events
                        (product_id, quantity, event_type, modality,
                         event_date, event_timestamp)
                        VALUES (?, ?, 'cart_add', ?, ?, ?)
                    """, (
                        product_id,
                        item.get('quantity', 1),
                        item.get('modality'),
                        event_date,
                        added_at
                    ))

            except (json.JSONDecodeError, IOError) as e:
                print(f"Warning: Could not read cart data: {e}")

        conn.commit()

        # Create migration marker
        with open(MIGRATION_MARKER, 'w') as f:
            f.write(json.dumps({
                'migrated_at': datetime.now().isoformat(),
                'orders': migrated['orders'],
                'items': migrated['items'],
                'products': len(migrated['products'])
            }))

        # Update statistics for all migrated products
        _update_migrated_stats(list(migrated['products']))

        return {
            'success': True,
            'orders_migrated': migrated['orders'],
            'items_migrated': migrated['items'],
            'products_migrated': len(migrated['products'])
        }

    except Exception as e:
        conn.rollback()
        return {
            'success': False,
            'error': str(e)
        }
    finally:
        conn.close()


def _ensure_product_exists(
    conn,
    product_id: str,
    item_data: Dict[str, Any],
    first_purchased: str
) -> None:
    """Ensure a product record exists in the database."""
    conn.execute("""
        INSERT OR IGNORE INTO products
        (product_id, upc, description, brand, first_purchased_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        product_id,
        item_data.get('upc'),
        item_data.get('description'),
        item_data.get('brand'),
        first_purchased,
        datetime.now().isoformat()
    ))


def _update_migrated_stats(product_ids: list) -> None:
    """Update statistics for migrated products."""
    from .statistics import update_product_stats
    from .seasonal import update_seasonal_patterns
    from .categories import auto_categorize_all

    for product_id in product_ids:
        try:
            update_product_stats(product_id)
            update_seasonal_patterns(product_id)
        except Exception as e:
            print(f"Warning: Could not update stats for {product_id}: {e}")

    # Run auto-categorization
    try:
        auto_categorize_all()
    except Exception as e:
        print(f"Warning: Could not auto-categorize: {e}")


def get_migration_status() -> Dict[str, Any]:
    """
    Get the current migration status.

    Returns:
        Dict with migration status information
    """
    if os.path.exists(MIGRATION_MARKER):
        try:
            with open(MIGRATION_MARKER, 'r') as f:
                data = json.load(f)
                return {
                    'migrated': True,
                    **data
                }
        except (json.JSONDecodeError, IOError):
            return {'migrated': True, 'details': 'unknown'}

    return {
        'migrated': False,
        'has_order_history': os.path.exists(ORDER_HISTORY_FILE),
        'has_cart': os.path.exists(CART_FILE)
    }


def force_remigration() -> Dict[str, Any]:
    """
    Force a fresh migration by removing the marker and re-running.

    Warning: This will duplicate data if run on an already migrated database.
    Only use for testing or when you've cleared the database.

    Returns:
        Migration result
    """
    if os.path.exists(MIGRATION_MARKER):
        os.remove(MIGRATION_MARKER)

    return migrate_json_to_sqlite()
