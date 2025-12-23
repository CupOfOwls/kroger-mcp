"""
SQLite database connection and schema management for purchase analytics.
"""

import sqlite3
from contextlib import contextmanager

# Database file location (working directory)
DB_FILE = "kroger_analytics.db"

# Global initialization flag
_initialized = False


def get_db_path() -> str:
    """Get the full path to the database file."""
    return DB_FILE


def get_db_connection() -> sqlite3.Connection:
    """
    Get a connection to the SQLite database.

    Returns:
        sqlite3.Connection: Database connection with row_factory set to Row
    """
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    # Enable foreign keys
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db_cursor():
    """
    Context manager for database operations with automatic commit/rollback.

    Usage:
        with get_db_cursor() as cursor:
            cursor.execute("INSERT INTO ...")
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize_database() -> None:
    """
    Create all database tables if they don't exist.
    """
    conn = get_db_connection()
    try:
        conn.executescript("""
            -- Products with category tracking
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                upc TEXT,
                description TEXT,
                brand TEXT,
                category_type TEXT DEFAULT 'uncategorized',
                category_override INTEGER DEFAULT 0,
                first_purchased_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Every cart add/order event
            CREATE TABLE IF NOT EXISTS purchase_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL DEFAULT 1,
                event_type TEXT NOT NULL,
                modality TEXT,
                price REAL,
                event_date TEXT NOT NULL,
                event_timestamp TEXT NOT NULL,
                order_id INTEGER,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            -- Completed orders
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                placed_at TEXT NOT NULL,
                item_count INTEGER,
                total_quantity INTEGER,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Pre-computed statistics (updated on each order)
            CREATE TABLE IF NOT EXISTS product_statistics (
                product_id TEXT PRIMARY KEY,
                total_purchases INTEGER DEFAULT 0,
                total_quantity INTEGER DEFAULT 0,
                avg_quantity_per_purchase REAL,
                avg_days_between_purchases REAL,
                std_dev_days REAL,
                last_purchase_date TEXT,
                first_purchase_date TEXT,
                purchase_frequency_score REAL,
                seasonality_score REAL,
                detected_category TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            -- Seasonal patterns for treats
            CREATE TABLE IF NOT EXISTS seasonal_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                month INTEGER NOT NULL,
                week_of_year INTEGER,
                purchase_count INTEGER DEFAULT 0,
                avg_quantity REAL,
                is_peak_period INTEGER DEFAULT 0,
                holiday_association TEXT,
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                UNIQUE(product_id, month)
            );

            -- Saved recipes
            CREATE TABLE IF NOT EXISTS recipes (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                servings INTEGER DEFAULT 4,
                instructions TEXT,
                source TEXT,
                tags TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT,
                last_ordered_at TEXT,
                times_ordered INTEGER DEFAULT 0
            );

            -- Recipe ingredients
            CREATE TABLE IF NOT EXISTS recipe_ingredients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipe_id TEXT NOT NULL,
                name TEXT NOT NULL,
                quantity REAL,
                unit TEXT,
                product_id TEXT,
                product_description TEXT,
                category TEXT,
                is_optional INTEGER DEFAULT 0,
                FOREIGN KEY (recipe_id) REFERENCES recipes(id) ON DELETE CASCADE
            );

            -- Pantry inventory tracking
            CREATE TABLE IF NOT EXISTS pantry_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                description TEXT,
                level_percent INTEGER DEFAULT 100,
                last_restocked_at TEXT,
                last_updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                auto_deplete INTEGER DEFAULT 1,
                daily_depletion_rate REAL DEFAULT 0,
                low_threshold INTEGER DEFAULT 20,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            -- Indexes for performance
            CREATE INDEX IF NOT EXISTS idx_purchase_events_product
                ON purchase_events(product_id);
            CREATE INDEX IF NOT EXISTS idx_purchase_events_date
                ON purchase_events(event_date);
            CREATE INDEX IF NOT EXISTS idx_purchase_events_order
                ON purchase_events(order_id);
            CREATE INDEX IF NOT EXISTS idx_purchase_events_type
                ON purchase_events(event_type);
            CREATE INDEX IF NOT EXISTS idx_seasonal_patterns_product
                ON seasonal_patterns(product_id);
            CREATE INDEX IF NOT EXISTS idx_products_category
                ON products(category_type);
            CREATE INDEX IF NOT EXISTS idx_recipe_ingredients_recipe
                ON recipe_ingredients(recipe_id);
            CREATE INDEX IF NOT EXISTS idx_pantry_items_product
                ON pantry_items(product_id);
            CREATE INDEX IF NOT EXISTS idx_pantry_items_level
                ON pantry_items(level_percent);
        """)
        conn.commit()
    finally:
        conn.close()


def ensure_initialized() -> None:
    """
    Ensure database is initialized and migration is run if needed.

    This should be called before any analytics operations.
    """
    global _initialized
    if _initialized:
        return

    # Initialize database schema
    initialize_database()

    # Check if migration is needed
    from .migration import needs_migration, migrate_json_to_sqlite
    if needs_migration():
        migrate_json_to_sqlite()

    _initialized = True


def reset_initialization() -> None:
    """Reset the initialization flag (for testing purposes)."""
    global _initialized
    _initialized = False


def get_table_counts() -> dict:
    """
    Get row counts for all tables (for diagnostics).

    Returns:
        Dict with table names as keys and row counts as values
    """
    conn = get_db_connection()
    try:
        counts = {}
        for table in ['products', 'purchase_events', 'orders',
                      'product_statistics', 'seasonal_patterns',
                      'recipes', 'recipe_ingredients', 'pantry_items']:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
        return counts
    finally:
        conn.close()
