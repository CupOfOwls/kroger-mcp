"""
Tests for deal discovery and price tracking functionality.
"""

import pytest
from datetime import datetime, timedelta
from src.kroger_mcp.analytics.database import (
    ensure_initialized,
    get_db_connection,
    reset_initialization,
)
from src.kroger_mcp.analytics.deals import (
    record_price_observation,
    get_price_statistics,
    calculate_cart_savings,
    score_deal_quality,
)


@pytest.fixture(scope="function")
def clean_db():
    """Ensure clean database state for each test."""
    reset_initialization()
    ensure_initialized()

    # Clean test data - just clean the deal tables
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM price_history WHERE product_id LIKE 'TEST%'")
        conn.execute("DELETE FROM deal_watchlist WHERE product_id LIKE 'TEST%'")
        conn.execute("DELETE FROM whole_foods_catalog WHERE product_id LIKE 'TEST%'")
        conn.execute("DELETE FROM deal_scan_results WHERE product_id LIKE 'TEST%'")
        conn.commit()
    finally:
        conn.close()

    yield

    # Cleanup after test - clean everything
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM price_history WHERE product_id LIKE 'TEST%'")
        conn.execute("DELETE FROM deal_watchlist WHERE product_id LIKE 'TEST%'")
        conn.execute("DELETE FROM whole_foods_catalog WHERE product_id LIKE 'TEST%'")
        conn.execute("DELETE FROM deal_scan_results WHERE product_id LIKE 'TEST%'")
        conn.commit()
    finally:
        conn.close()

    reset_initialization()


def insert_test_product(product_id: str, description: str = "Test Product"):
    """Helper to insert a test product."""
    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO products (product_id, description)
            VALUES (?, ?)
            """,
            (product_id, description),
        )
        conn.commit()
    finally:
        conn.close()


def test_record_price_observation(clean_db):
    """Test recording a price observation."""
    # Insert test product first
    insert_test_product("TEST001", "Test Milk")

    # Record a price
    record_price_observation(
        product_id="TEST001",
        regular_price=4.99,
        sale_price=3.99,
        location_id="01400943",
        source="test",
    )

    # Verify it was recorded
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM price_history WHERE product_id = ?", ("TEST001",)
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["regular_price"] == 4.99
        assert result["sale_price"] == 3.99
        assert result["on_sale"] == 1
        assert abs(result["savings_amount"] - 1.0) < 0.01
        assert abs(result["savings_percent"] - 20.04) < 0.1
    finally:
        conn.close()


def test_record_price_observation_no_sale(clean_db):
    """Test recording a regular price (not on sale)."""
    insert_test_product("TEST002", "Test Bread")

    record_price_observation(
        product_id="TEST002",
        regular_price=4.99,
        sale_price=None,
        location_id="01400943",
        source="test",
    )

    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT * FROM price_history WHERE product_id = ?", ("TEST002",)
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["on_sale"] == 0
        assert result["savings_amount"] == 0.0
    finally:
        conn.close()


def test_get_price_statistics_no_data(clean_db):
    """Test price statistics with no data."""
    stats = get_price_statistics("NONEXISTENT", days=30, location_id="01400943")
    assert stats["has_data"] is False


def test_get_price_statistics_with_data(clean_db):
    """Test price statistics with historical data."""
    insert_test_product("TEST003", "Test Eggs")

    # Record multiple observations over time
    now = datetime.now()
    for i in range(10):
        # Simulate observations over 10 days
        obs_time = (now - timedelta(days=9 - i)).isoformat()

        # Alternate between sale and regular price
        if i % 3 == 0:
            sale_price = 3.49
        else:
            sale_price = None

        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO price_history
                (product_id, regular_price, sale_price, on_sale,
                 savings_amount, savings_percent, location_id,
                 observed_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "TEST003",
                    4.99,
                    sale_price,
                    1 if sale_price else 0,
                    (4.99 - sale_price) if sale_price else 0,
                    ((4.99 - sale_price) / 4.99 * 100) if sale_price else 0,
                    "01400943",
                    obs_time,
                    "test",
                ),
            )
            conn.commit()
        finally:
            conn.close()

    # Get statistics
    stats = get_price_statistics("TEST003", days=30, location_id="01400943")
    assert stats["has_data"] is True
    assert stats["lowest_price_30d"] == 3.49
    assert stats["highest_price_30d"] == 4.99
    assert stats["times_on_sale"] > 0
    assert stats["observations_count"] == 10


def test_calculate_cart_savings_mixed(clean_db):
    """Test calculating savings for cart with mixed items."""
    cart_items = [
        {
            "product_id": "ITEM1",
            "quantity": 2,
            "regular_price": 4.99,
            "price": 3.99,  # On sale
        },
        {
            "product_id": "ITEM2",
            "quantity": 1,
            "regular_price": 6.99,
            "price": 6.99,  # Regular price
        },
        {
            "product_id": "ITEM3",
            "quantity": 3,
            "regular_price": 2.99,
            "price": 1.99,  # On sale
        },
    ]

    savings = calculate_cart_savings(cart_items)

    # Expected: (2 * 4.99) + 6.99 + (3 * 2.99) = 25.94 regular
    # Actual: (2 * 3.99) + 6.99 + (3 * 1.99) = 20.94 sale
    # Savings: 5.00
    assert savings["total_items"] == 3
    assert savings["items_on_sale"] == 2
    assert savings["items_regular_price"] == 1
    assert abs(savings["total_regular_price"] - 25.94) < 0.01
    assert abs(savings["total_sale_price"] - 20.94) < 0.01
    assert abs(savings["total_savings"] - 5.0) < 0.01


def test_calculate_cart_savings_all_regular(clean_db):
    """Test calculating savings for cart with no sales."""
    cart_items = [
        {"product_id": "ITEM1", "quantity": 1, "regular_price": 4.99, "price": 4.99},
        {"product_id": "ITEM2", "quantity": 1, "regular_price": 6.99, "price": 6.99},
    ]

    savings = calculate_cart_savings(cart_items)
    assert savings["total_items"] == 2
    assert savings["items_on_sale"] == 0
    assert savings["total_savings"] == 0.0


def test_score_deal_quality_excellent(clean_db):
    """Test deal quality scoring for excellent deals."""
    product = {
        "pricing": {
            "regular_price": 4.99,
            "sale_price": 2.49,
            "savings_percent": 50.1,
        },
        "is_favorite": True,
        "is_in_pantry": True,
        "pantry_level": 20,
    }

    score = score_deal_quality(product)
    assert score["quality_score"] >= 80
    assert score["quality_label"] == "excellent"
    assert score["urgency"] == "high"


def test_score_deal_quality_poor(clean_db):
    """Test deal quality scoring for poor deals."""
    product = {
        "pricing": {
            "regular_price": 4.99,
            "sale_price": 4.89,
            "savings_percent": 2.0,
        },
        "is_favorite": False,
        "is_in_pantry": False,
    }

    score = score_deal_quality(product)
    assert score["quality_score"] < 40
    assert score["quality_label"] == "poor"


def test_price_deduplication(clean_db):
    """Test that duplicate observations within an hour are merged."""
    insert_test_product("TEST004", "Test Cheese")

    # Record same product twice within an hour
    record_price_observation(
        product_id="TEST004",
        regular_price=4.99,
        sale_price=3.99,
        location_id="01400943",
        source="test1",
    )

    record_price_observation(
        product_id="TEST004",
        regular_price=4.99,
        sale_price=3.99,
        location_id="01400943",
        source="test2",
    )

    # Should only have 1 record (deduplicated)
    conn = get_db_connection()
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM price_history WHERE product_id = ?",
            ("TEST004",),
        )
        count = cursor.fetchone()["cnt"]
        assert count == 1
    finally:
        conn.close()


def test_whole_foods_catalog_add(clean_db):
    """Test adding product to whole foods catalog."""
    insert_test_product("TEST_WF001", "Organic Baby Spinach")

    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO whole_foods_catalog
            (product_id, description, safety_status, added_by)
            VALUES (?, ?, ?, ?)
            """,
            ("TEST_WF001", "Organic Baby Spinach", "SAFE", "test"),
        )
        conn.commit()

        # Verify
        cursor = conn.execute(
            "SELECT * FROM whole_foods_catalog WHERE product_id = ?",
            ("TEST_WF001",),
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["description"] == "Organic Baby Spinach"
        assert result["safety_status"] == "SAFE"
    finally:
        conn.close()


def test_deal_scan_results_add(clean_db):
    """Test adding scan results."""
    insert_test_product("TEST_SCAN001", "Test Milk")

    conn = get_db_connection()
    try:
        scan_time = datetime.now().isoformat()
        scan_date = datetime.now().date().isoformat()

        conn.execute(
            """
            INSERT INTO deal_scan_results
            (product_id, description, regular_price, sale_price,
             savings_amount, scan_date, scan_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("TEST_SCAN001", "Test Milk", 4.99, 3.99, 1.00, scan_date, scan_time),
        )
        conn.commit()

        # Verify
        cursor = conn.execute(
            "SELECT * FROM deal_scan_results WHERE product_id = ?",
            ("TEST_SCAN001",),
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["regular_price"] == 4.99
        assert result["sale_price"] == 3.99
        assert result["savings_amount"] == 1.00
    finally:
        conn.close()


def test_deal_scan_results_cleanup(clean_db):
    """Test that old scan results are cleaned up."""
    insert_test_product("TEST_SCAN002", "Test Bread")

    conn = get_db_connection()
    try:
        # Insert old result (8 days ago)
        old_date = (datetime.now() - timedelta(days=8)).date().isoformat()
        conn.execute(
            """
            INSERT INTO deal_scan_results
            (product_id, description, regular_price, sale_price,
             savings_amount, scan_date, scan_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "TEST_SCAN002",
                "Test Bread",
                3.99,
                2.99,
                1.00,
                old_date,
                datetime.now().isoformat(),
            ),
        )
        conn.commit()

        # Clean old results (simulate background_scanner.py cleanup)
        conn.execute("DELETE FROM deal_scan_results WHERE scan_date < date('now', '-7 days')")
        conn.commit()

        # Verify old result is gone
        cursor = conn.execute(
            "SELECT COUNT(*) as cnt FROM deal_scan_results WHERE product_id = ?",
            ("TEST_SCAN002",),
        )
        count = cursor.fetchone()["cnt"]
        assert count == 0
    finally:
        conn.close()


def test_watchlist_add(clean_db):
    """Test adding item to watchlist."""
    insert_test_product("TEST_WATCH001", "Test Yogurt")

    conn = get_db_connection()
    try:
        conn.execute(
            """
            INSERT INTO deal_watchlist
            (product_id, description, target_price, priority)
            VALUES (?, ?, ?, ?)
            """,
            ("TEST_WATCH001", "Test Yogurt", 2.99, 3),
        )
        conn.commit()

        # Verify
        cursor = conn.execute(
            "SELECT * FROM deal_watchlist WHERE product_id = ?",
            ("TEST_WATCH001",),
        )
        result = cursor.fetchone()
        assert result is not None
        assert result["description"] == "Test Yogurt"
        assert result["target_price"] == 2.99
        assert result["priority"] == 3
    finally:
        conn.close()
