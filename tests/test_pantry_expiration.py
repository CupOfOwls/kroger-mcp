"""
Unit tests for pantry expiration date tracking.

Tests automatic expiration calculation, manual overrides,
and integration with pantry inventory system.
"""

import pytest
from datetime import datetime, timedelta
import os
import sys

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.kroger_mcp.analytics.database import (
    get_db_connection,
    ensure_initialized,
    reset_initialization
)
from src.kroger_mcp.analytics.pantry import (
    get_shelf_life_days,
    calculate_expiration_date,
    calculate_days_to_expiration,
    get_expiration_status,
    restock_item,
    get_pantry_status,
    add_to_pantry
)


@pytest.fixture
def clean_db():
    """Reset database before each test."""
    reset_initialization()
    ensure_initialized()

    # Clear tables - disable foreign keys temporarily for cleanup
    conn = get_db_connection()
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DELETE FROM pantry_items")
        conn.execute("DELETE FROM purchase_events")
        conn.execute("DELETE FROM product_statistics")
        conn.execute("DELETE FROM products")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.commit()
    finally:
        conn.close()

    yield

    # Cleanup after test
    reset_initialization()


class TestShelfLifeLookup:
    """Test category/keyword matching for shelf life determination."""

    def test_routine_milk_7_days(self):
        """Milk should have 7 day shelf life."""
        days = get_shelf_life_days('routine', 'Whole Milk Gallon')
        assert days == 7

    def test_routine_eggs_21_days(self):
        """Eggs should have 21 day shelf life."""
        days = get_shelf_life_days('routine', 'Fresh Large Eggs Dozen')
        assert days == 21

    def test_routine_bread_5_days(self):
        """Bread should have 5 day shelf life."""
        days = get_shelf_life_days('routine', 'Sliced White Bread')
        assert days == 5

    def test_frozen_chicken_180_days(self):
        """Frozen chicken should have 180 day shelf life."""
        days = get_shelf_life_days('routine', 'Frozen Chicken Breast')
        assert days == 180

    def test_frozen_pizza_120_days(self):
        """Frozen pizza should have 120 day shelf life."""
        days = get_shelf_life_days('routine', 'Frozen Pizza Supreme')
        assert days == 120

    def test_frozen_vegetables_240_days(self):
        """Frozen vegetables should have 240 day shelf life."""
        # Must match exact pattern "frozen vegetable" (singular or plural nearby)
        days = get_shelf_life_days('routine', 'Frozen Vegetable Mix')
        assert days == 240

    def test_fresh_meat_days(self):
        """Fresh meat should have correct shelf life."""
        # Ground meat is 2 days (shorter than regular)
        days = get_shelf_life_days('routine', 'Fresh Ground Beef')
        assert days == 2

        # Regular chicken is 3 days
        days = get_shelf_life_days('routine', 'Fresh Chicken Breast')
        assert days == 3

    def test_berries_3_days(self):
        """Berries should have 3 day shelf life."""
        days = get_shelf_life_days('routine', 'Fresh Strawberries')
        assert days == 3

    def test_leafy_greens_5_days(self):
        """Leafy greens should have 5 day shelf life."""
        days = get_shelf_life_days('routine', 'Fresh Lettuce')
        assert days == 5

    def test_treat_category_none(self):
        """Treat category should return None (no expiration)."""
        days = get_shelf_life_days('treat', 'Halloween Candy Mix')
        assert days is None

    def test_no_keyword_match_uses_default(self):
        """Items with no keyword match should use category default."""
        days = get_shelf_life_days('routine', 'Some Unknown Product')
        assert days == 7  # routine default

        days = get_shelf_life_days('regular', 'Another Unknown Item')
        assert days == 30  # regular default

    def test_empty_description_returns_none(self):
        """Empty description should return None."""
        days = get_shelf_life_days('routine', '')
        assert days is None

    def test_none_category_returns_none(self):
        """None category should return None."""
        days = get_shelf_life_days(None, 'Milk')
        assert days is None


class TestAutoExpirationCalculation:
    """Test automatic expiration date calculation."""

    def test_calculate_milk_expiration(self):
        """Calculate expiration for milk (7 days)."""
        purchase_date = '2026-02-12'
        exp_date = calculate_expiration_date(purchase_date, 'routine', 'Whole Milk')
        assert exp_date == '2026-02-19'  # 7 days later

    def test_calculate_eggs_expiration(self):
        """Calculate expiration for eggs (21 days)."""
        purchase_date = '2026-02-12'
        exp_date = calculate_expiration_date(purchase_date, 'routine', 'Large Eggs')
        assert exp_date == '2026-03-05'  # 21 days later

    def test_calculate_bread_expiration(self):
        """Calculate expiration for bread (5 days)."""
        purchase_date = '2026-02-12'
        exp_date = calculate_expiration_date(purchase_date, 'routine', 'Sliced Bread')
        assert exp_date == '2026-02-17'  # 5 days later

    def test_frozen_chicken_expiration(self):
        """Calculate expiration for frozen chicken (180 days)."""
        purchase_date = '2026-02-12'
        exp_date = calculate_expiration_date(purchase_date, 'routine', 'Frozen Chicken')
        expected = (datetime(2026, 2, 12) + timedelta(days=180)).date().isoformat()
        assert exp_date == expected

    def test_treat_returns_none(self):
        """Treat category should return None."""
        purchase_date = '2026-02-12'
        exp_date = calculate_expiration_date(purchase_date, 'treat', 'Halloween Candy')
        assert exp_date is None

    def test_handles_timestamp_format(self):
        """Should handle full ISO timestamp format."""
        purchase_date = '2026-02-12T14:30:00'
        exp_date = calculate_expiration_date(purchase_date, 'routine', 'Milk')
        assert exp_date == '2026-02-19'

    def test_invalid_date_returns_none(self):
        """Invalid date format should return None."""
        exp_date = calculate_expiration_date('invalid-date', 'routine', 'Milk')
        assert exp_date is None


class TestExpirationCalculations:
    """Test days-to-expiration calculations."""

    def test_future_expiration_positive_days(self):
        """Future expiration should return positive days."""
        future_date = (datetime.now() + timedelta(days=7)).date().isoformat()
        days = calculate_days_to_expiration(future_date)
        assert days == 7

    def test_past_expiration_negative_days(self):
        """Past expiration should return negative days."""
        past_date = (datetime.now() - timedelta(days=3)).date().isoformat()
        days = calculate_days_to_expiration(past_date)
        assert days == -3

    def test_today_expiration_zero_days(self):
        """Today's expiration should return 0 days."""
        today = datetime.now().date().isoformat()
        days = calculate_days_to_expiration(today)
        assert days == 0

    def test_none_expiration_returns_none(self):
        """None expiration should return None."""
        days = calculate_days_to_expiration(None)
        assert days is None

    def test_invalid_format_returns_none(self):
        """Invalid date format should return None gracefully."""
        days = calculate_days_to_expiration('not-a-date')
        assert days is None


class TestExpirationStatus:
    """Test status categorization based on days."""

    def test_expired_status(self):
        """Negative days should return 'expired'."""
        status = get_expiration_status(-1)
        assert status == 'expired'

        status = get_expiration_status(-10)
        assert status == 'expired'

    def test_critical_status(self):
        """0-2 days should return 'critical'."""
        assert get_expiration_status(0) == 'critical'
        assert get_expiration_status(1) == 'critical'
        assert get_expiration_status(2) == 'critical'

    def test_warning_status(self):
        """3-6 days should return 'warning'."""
        assert get_expiration_status(3) == 'warning'
        assert get_expiration_status(4) == 'warning'
        assert get_expiration_status(5) == 'warning'
        assert get_expiration_status(6) == 'warning'

    def test_ok_status(self):
        """7-13 days should return 'ok'."""
        assert get_expiration_status(7) == 'ok'
        assert get_expiration_status(10) == 'ok'
        assert get_expiration_status(13) == 'ok'

    def test_fresh_status(self):
        """14+ days should return 'fresh'."""
        assert get_expiration_status(14) == 'fresh'
        assert get_expiration_status(30) == 'fresh'
        assert get_expiration_status(90) == 'fresh'

    def test_none_status(self):
        """None should return 'none'."""
        status = get_expiration_status(None)
        assert status == 'none'


class TestRestockWithExpiration:
    """Test restock_item() auto-calculates expiration."""

    def test_restock_auto_calculates_expiration(self, clean_db):
        """Restocking should automatically calculate expiration date."""
        # Setup: Create product first (required for foreign key), then statistics
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('MILK001', 'Whole Milk Gallon')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('MILK001', 'routine')
        """)
        conn.commit()
        conn.close()

        # Restock the item
        result = restock_item('MILK001', description='Whole Milk Gallon')

        # Should auto-calculate expiration
        assert result['success'] is True
        assert result['expiration_date'] is not None
        assert result['days_to_expiration'] == 7  # Milk = 7 days
        assert result['auto_calculated'] is True

    def test_restock_eggs_21_days(self, clean_db):
        """Eggs should get 21 day expiration."""
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('EGGS001', 'Large Eggs Dozen')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('EGGS001', 'routine')
        """)
        conn.commit()
        conn.close()

        result = restock_item('EGGS001', description='Large Eggs Dozen')

        assert result['expiration_date'] is not None
        assert result['days_to_expiration'] == 21
        assert result['auto_calculated'] is True

    def test_restock_frozen_chicken(self, clean_db):
        """Frozen chicken should get 180 day expiration."""
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('CHICKEN001', 'Frozen Chicken Breast')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('CHICKEN001', 'routine')
        """)
        conn.commit()
        conn.close()

        result = restock_item('CHICKEN001', description='Frozen Chicken Breast')

        assert result['expiration_date'] is not None
        assert result['days_to_expiration'] == 180
        assert result['auto_calculated'] is True

    def test_restock_treat_no_expiration(self, clean_db):
        """Treat items should not get expiration."""
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('CANDY001', 'Halloween Candy')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('CANDY001', 'treat')
        """)
        conn.commit()
        conn.close()

        result = restock_item('CANDY001', description='Halloween Candy')

        assert result['expiration_date'] is None
        assert result['days_to_expiration'] is None
        assert result['auto_calculated'] is False  # Nothing to calculate for treats

    def test_restock_updates_existing_expiration(self, clean_db):
        """Restocking should update expiration date."""
        # First restock
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('MILK002', 'Milk')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('MILK002', 'routine')
        """)
        conn.commit()
        conn.close()

        result1 = restock_item('MILK002', description='Milk')
        exp1 = result1['expiration_date']

        # Restock again (simulating new purchase)
        result2 = restock_item('MILK002', description='Milk')
        exp2 = result2['expiration_date']

        # Should have new expiration date
        assert exp2 is not None
        # Both should be valid dates
        assert exp1 is not None
        assert exp2 is not None


class TestPantryStatusWithExpiration:
    """Test get_pantry_status() includes expiration fields."""

    def test_pantry_status_includes_expiration(self, clean_db):
        """Pantry status should include expiration fields."""
        # Setup item with expiration
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('MILK003', 'Milk')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('MILK003', 'routine')
        """)
        conn.commit()
        conn.close()

        restock_item('MILK003', description='Milk')

        # Get pantry status
        items = get_pantry_status()

        assert len(items) == 1
        item = items[0]

        # Should have expiration fields
        assert 'expiration_date' in item
        assert 'days_to_expiration' in item
        assert 'expiration_status' in item

        # Values should be set
        assert item['expiration_date'] is not None
        assert item['days_to_expiration'] == 7
        assert item['expiration_status'] in ['critical', 'warning', 'ok', 'fresh']

    def test_pantry_status_lazy_recalculation(self, clean_db):
        """Days to expiration should be recalculated on each call."""
        # Setup item
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('MILK004', 'Milk')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('MILK004', 'routine')
        """)
        conn.commit()
        conn.close()

        restock_item('MILK004', description='Milk')

        # First call
        items1 = get_pantry_status()
        days1 = items1[0]['days_to_expiration']

        # Second call should recalculate (not use stored value)
        items2 = get_pantry_status()
        days2 = items2[0]['days_to_expiration']

        # Should be same (called immediately after)
        assert days1 == days2
        assert days1 == 7  # Milk = 7 days

    def test_pantry_status_handles_none_expiration(self, clean_db):
        """Should handle items without expiration gracefully."""
        # Setup treat item (no expiration)
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('CANDY002', 'Candy')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('CANDY002', 'treat')
        """)
        conn.commit()
        conn.close()

        restock_item('CANDY002', description='Candy')

        items = get_pantry_status()
        assert len(items) == 1

        item = items[0]
        assert item['expiration_date'] is None
        assert item['days_to_expiration'] is None
        assert item['expiration_status'] == 'none'


class TestManualExpirationOverride:
    """Test manual expiration date setting (would use MCP tool)."""

    def test_manual_set_expiration(self, clean_db):
        """Should allow manual override of expiration date."""
        # Setup pantry item
        add_to_pantry('MILK005', description='Milk', level=100)

        # Manually set expiration
        future_date = (datetime.now() + timedelta(days=3)).date().isoformat()

        conn = get_db_connection()
        from src.kroger_mcp.analytics.pantry import calculate_days_to_expiration
        days_to_exp = calculate_days_to_expiration(future_date)

        conn.execute("""
            UPDATE pantry_items
            SET expiration_date = ?, days_to_expiration = ?
            WHERE product_id = ?
        """, (future_date, days_to_exp, 'MILK005'))
        conn.commit()
        conn.close()

        # Verify
        items = get_pantry_status()
        item = items[0]

        assert item['expiration_date'] == future_date
        assert item['days_to_expiration'] == 3
        assert item['expiration_status'] == 'warning'

    def test_manual_clear_expiration(self, clean_db):
        """Should allow clearing expiration date."""
        # Setup item with expiration
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES ('MILK006', 'Milk')
        """)
        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category)
            VALUES ('MILK006', 'routine')
        """)
        conn.commit()
        conn.close()

        restock_item('MILK006', description='Milk')

        # Clear expiration
        conn = get_db_connection()
        conn.execute("""
            UPDATE pantry_items
            SET expiration_date = NULL, days_to_expiration = NULL
            WHERE product_id = ?
        """, ('MILK006',))
        conn.commit()
        conn.close()

        # Verify
        items = get_pantry_status()
        item = items[0]

        assert item['expiration_date'] is None
        assert item['days_to_expiration'] is None
        assert item['expiration_status'] == 'none'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
