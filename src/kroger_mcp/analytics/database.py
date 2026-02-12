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

            -- Favorite lists (named shopping lists)
            CREATE TABLE IF NOT EXISTS favorite_lists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                description TEXT,
                list_type TEXT DEFAULT 'custom',
                reorder_weeks INTEGER DEFAULT NULL,
                last_ordered_at TEXT DEFAULT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Favorite list items (products in each list)
            CREATE TABLE IF NOT EXISTS favorite_list_items (
                list_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                description TEXT NOT NULL,
                brand TEXT,
                default_quantity INTEGER DEFAULT 1,
                preferred_modality TEXT DEFAULT 'PICKUP',
                notes TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                times_ordered INTEGER DEFAULT 0,
                PRIMARY KEY (list_id, product_id),
                FOREIGN KEY (list_id) REFERENCES favorite_lists(id) ON DELETE CASCADE
            );

            -- Meal plans (weekly, monthly, or custom date ranges)
            CREATE TABLE IF NOT EXISTS meal_plans (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                plan_type TEXT DEFAULT 'weekly',
                is_template INTEGER DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_ordered_at TEXT,
                times_ordered INTEGER DEFAULT 0
            );

            -- Individual meal entries (recipe assignments to days/slots)
            CREATE TABLE IF NOT EXISTS meal_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id TEXT NOT NULL,
                recipe_id TEXT NOT NULL,
                meal_date TEXT NOT NULL,
                meal_slot TEXT NOT NULL,
                servings_override INTEGER,
                notes TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (plan_id) REFERENCES meal_plans(id) ON DELETE CASCADE,
                UNIQUE(plan_id, meal_date, meal_slot)
            );

            -- Safe products (user-approved, bypass all ingredient checks)
            CREATE TABLE IF NOT EXISTS safe_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                description TEXT,
                brand TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                added_reason TEXT
            );

            -- Blocked products (user-rejected, require explicit confirmation)
            CREATE TABLE IF NOT EXISTS blocked_products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                description TEXT,
                blocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
                blocked_reason TEXT,
                auto_blocked INTEGER DEFAULT 0
            );

            -- User ingredient preferences (enable/disable specific checks)
            CREATE TABLE IF NOT EXISTS ingredient_preferences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ingredient_key TEXT UNIQUE NOT NULL,
                enabled INTEGER DEFAULT 1,
                severity TEXT DEFAULT 'warning',
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Safety settings (global configuration)
            CREATE TABLE IF NOT EXISTS safety_settings (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            -- Price history tracking (for deal discovery and trend analysis)
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                regular_price REAL,
                sale_price REAL,
                on_sale INTEGER DEFAULT 0,
                savings_amount REAL DEFAULT 0,
                savings_percent REAL DEFAULT 0,
                location_id TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                source TEXT,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            -- Deal watchlist (user-tracked items for price monitoring)
            CREATE TABLE IF NOT EXISTS deal_watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT UNIQUE NOT NULL,
                description TEXT,
                target_price REAL,
                priority INTEGER DEFAULT 1,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_checked_at TEXT,
                best_price_seen REAL,
                best_price_date TEXT,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            -- Whole foods catalog (curated list of clean/natural foods)
            CREATE TABLE IF NOT EXISTS whole_foods_catalog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                description TEXT,
                brand TEXT,
                added_at TEXT DEFAULT CURRENT_TIMESTAMP,
                added_by TEXT DEFAULT 'auto',
                safety_status TEXT,
                ingredient_count INTEGER,
                processing_level TEXT,
                notes TEXT,
                last_verified_at TEXT,
                is_currently_available INTEGER DEFAULT 1,
                FOREIGN KEY (product_id) REFERENCES products(product_id),
                UNIQUE(product_id)
            );

            -- Background scan results (deals found during automated scans)
            CREATE TABLE IF NOT EXISTS deal_scan_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id TEXT NOT NULL,
                description TEXT,
                regular_price REAL,
                sale_price REAL,
                savings_amount REAL,
                scan_date TEXT NOT NULL,
                scan_time TEXT NOT NULL,
                viewed INTEGER DEFAULT 0,
                FOREIGN KEY (product_id) REFERENCES products(product_id)
            );

            -- Create default favorites list
            INSERT OR IGNORE INTO favorite_lists (id, name, description, list_type)
            VALUES ('default', 'My Favorites', 'Default favorites list', 'custom');

            -- Initialize default safety settings
            INSERT OR IGNORE INTO safety_settings (key, value)
            VALUES ('filtering_enabled', '1');
            INSERT OR IGNORE INTO safety_settings (key, value)
            VALUES ('block_mode', 'soft');

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
            CREATE INDEX IF NOT EXISTS idx_favorite_list_items_list
                ON favorite_list_items(list_id);
            CREATE INDEX IF NOT EXISTS idx_favorite_list_items_product
                ON favorite_list_items(product_id);
            CREATE INDEX IF NOT EXISTS idx_meal_entries_plan
                ON meal_entries(plan_id);
            CREATE INDEX IF NOT EXISTS idx_meal_entries_date
                ON meal_entries(meal_date);
            CREATE INDEX IF NOT EXISTS idx_meal_plans_dates
                ON meal_plans(start_date, end_date);
            CREATE INDEX IF NOT EXISTS idx_safe_products_product
                ON safe_products(product_id);
            CREATE INDEX IF NOT EXISTS idx_blocked_products_product
                ON blocked_products(product_id);
            CREATE INDEX IF NOT EXISTS idx_ingredient_preferences_key
                ON ingredient_preferences(ingredient_key);
            CREATE INDEX IF NOT EXISTS idx_price_history_product
                ON price_history(product_id);
            CREATE INDEX IF NOT EXISTS idx_price_history_date
                ON price_history(observed_at);
            CREATE INDEX IF NOT EXISTS idx_price_history_on_sale
                ON price_history(on_sale);
            CREATE INDEX IF NOT EXISTS idx_price_history_product_date
                ON price_history(product_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_watchlist_priority
                ON deal_watchlist(priority DESC, last_checked_at ASC);
            CREATE INDEX IF NOT EXISTS idx_whole_foods_catalog_product
                ON whole_foods_catalog(product_id);
            CREATE INDEX IF NOT EXISTS idx_whole_foods_catalog_available
                ON whole_foods_catalog(is_currently_available);
            CREATE INDEX IF NOT EXISTS idx_deal_scan_results_date
                ON deal_scan_results(scan_date DESC);
            CREATE INDEX IF NOT EXISTS idx_deal_scan_results_viewed
                ON deal_scan_results(viewed);
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

    # Run schema migrations for new columns
    run_schema_migrations()

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
                      'recipes', 'recipe_ingredients', 'pantry_items',
                      'favorite_lists', 'favorite_list_items',
                      'meal_plans', 'meal_entries',
                      'safe_products', 'blocked_products',
                      'ingredient_preferences', 'safety_settings',
                      'price_history', 'deal_watchlist',
                      'whole_foods_catalog', 'deal_scan_results']:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            counts[table] = cursor.fetchone()[0]
        return counts
    finally:
        conn.close()


def run_schema_migrations() -> None:
    """
    Run schema migrations to add new columns to existing tables.

    This is idempotent - safe to run multiple times.
    """
    conn = get_db_connection()
    try:
        # Get existing columns in product_statistics
        cursor = conn.execute("PRAGMA table_info(product_statistics)")
        existing_columns = {row[1] for row in cursor.fetchall()}

        # Add new columns if they don't exist
        new_columns = [
            ("trend_direction", "TEXT DEFAULT 'stable'"),
            ("trend_strength", "REAL DEFAULT 0.0"),
            ("quantity_adjusted_rate", "REAL DEFAULT NULL"),
            ("prediction_accuracy", "REAL DEFAULT NULL"),
        ]

        for col_name, col_def in new_columns:
            if col_name not in existing_columns:
                conn.execute(
                    f"ALTER TABLE product_statistics ADD COLUMN {col_name} {col_def}"
                )

        # Migrate favorite_lists table - add reorder schedule columns
        cursor = conn.execute("PRAGMA table_info(favorite_lists)")
        favorite_lists_columns = {row[1] for row in cursor.fetchall()}

        favorite_lists_new_columns = [
            ("reorder_weeks", "INTEGER DEFAULT NULL"),
            ("last_ordered_at", "TEXT DEFAULT NULL"),
        ]

        for col_name, col_def in favorite_lists_new_columns:
            if col_name not in favorite_lists_columns:
                conn.execute(
                    f"ALTER TABLE favorite_lists ADD COLUMN {col_name} {col_def}"
                )

        conn.commit()
    finally:
        conn.close()
