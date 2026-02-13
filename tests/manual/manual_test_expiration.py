#!/usr/bin/env python3
"""
Manual end-to-end test for automatic expiration tracking.

Demonstrates the complete automatic workflow:
1. Restock items (simulating order placed)
2. Expiration dates calculated automatically
3. View pantry status with expiration info
4. Check unified attention tool
5. See recommendations with expiration urgency

NO USER INPUT REQUIRED - expiration is 100% automatic!
"""

from datetime import datetime, timedelta
from src.kroger_mcp.analytics.database import ensure_initialized, get_db_connection
from src.kroger_mcp.analytics.pantry import (
    restock_item,
    get_pantry_status,
    add_to_pantry
)
from src.kroger_mcp.analytics.recommendations import get_comprehensive_recommendations


def setup_test_data():
    """Setup test products with different expiration scenarios."""
    print("=== Setting up test data ===\n")

    conn = get_db_connection()

    # Clear existing test data
    conn.execute("DELETE FROM pantry_items WHERE product_id LIKE 'TEST%'")
    conn.execute("DELETE FROM product_statistics WHERE product_id LIKE 'TEST%'")
    conn.execute("DELETE FROM products WHERE product_id LIKE 'TEST%'")
    conn.commit()

    # Create test products with different categories
    test_products = [
        ('TEST_MILK', 'routine', 'Whole Milk Gallon', 7),
        ('TEST_EGGS', 'routine', 'Large Eggs Dozen', 21),
        ('TEST_BREAD', 'routine', 'Sliced Wheat Bread', 5),
        ('TEST_CHICKEN', 'routine', 'Frozen Chicken Breast', 180),
        ('TEST_BERRIES', 'routine', 'Fresh Strawberries', 3),
        ('TEST_CHEESE', 'routine', 'Cheddar Cheese Block', 14),
        ('TEST_CANDY', 'treat', 'Halloween Candy Mix', None),  # No expiration
    ]

    for product_id, category, description, expected_days in test_products:
        # Insert into products and product_statistics
        conn.execute("""
            INSERT INTO products (product_id, description)
            VALUES (?, ?)
        """, (product_id, description))

        conn.execute("""
            INSERT INTO product_statistics (product_id, detected_category, total_purchases, avg_days_between_purchases)
            VALUES (?, ?, 5, 7.0)
        """, (product_id, category))

    conn.commit()
    conn.close()

    print("✓ Test products created")


def test_automatic_expiration_calculation():
    """Test 1: Automatic expiration when restocking."""
    print("\n=== TEST 1: Automatic Expiration Calculation ===\n")
    print("Simulating 'mark order as placed' - expiration calculated automatically!\n")

    test_items = [
        ('TEST_MILK', 'Whole Milk Gallon', 7),
        ('TEST_EGGS', 'Large Eggs Dozen', 21),
        ('TEST_BREAD', 'Sliced Wheat Bread', 5),
        ('TEST_BERRIES', 'Fresh Strawberries', 3),
    ]

    for product_id, description, expected_days in test_items:
        result = restock_item(product_id, description=description, level=100)

        print(f"📦 {description}")
        print(f"   Expiration: {result['expiration_date']}")
        print(f"   Days until expiration: {result['days_to_expiration']}")
        print(f"   Auto-calculated: {result['auto_calculated']}")

        assert result['auto_calculated'] is True, "Should be automatic!"
        assert result['expiration_date'] is not None, "Should have expiration!"
        assert result['days_to_expiration'] == expected_days, f"Expected {expected_days} days"
        print(f"   ✓ Correct: {expected_days} day shelf life\n")


def test_frozen_items():
    """Test 2: Frozen items get long shelf life."""
    print("\n=== TEST 2: Frozen Items (Long Shelf Life) ===\n")

    result = restock_item('TEST_CHICKEN', description='Frozen Chicken Breast', level=100)

    print(f"❄️  Frozen Chicken Breast")
    print(f"   Expiration: {result['expiration_date']}")
    print(f"   Days until expiration: {result['days_to_expiration']}")
    print(f"   Auto-calculated: {result['auto_calculated']}")

    assert result['days_to_expiration'] == 180, "Frozen chicken should be 180 days"
    print(f"   ✓ Correct: 6 month (180 day) shelf life\n")


def test_treat_no_expiration():
    """Test 3: Treat items don't expire."""
    print("\n=== TEST 3: Treat Items (No Expiration) ===\n")

    result = restock_item('TEST_CANDY', description='Halloween Candy Mix', level=100)

    print(f"🍬 Halloween Candy Mix")
    print(f"   Expiration: {result['expiration_date']}")
    print(f"   Days until expiration: {result['days_to_expiration']}")
    print(f"   Auto-calculated: {result['auto_calculated']}")

    assert result['expiration_date'] is None, "Treats should not expire"
    print(f"   ✓ Correct: No expiration tracking\n")


def test_pantry_status_with_expiration():
    """Test 4: View pantry with expiration status."""
    print("\n=== TEST 4: Pantry Status with Expiration ===\n")

    items = get_pantry_status(apply_depletion=True)

    print(f"Found {len(items)} items in pantry:\n")

    for item in items[:6]:  # Show first 6
        exp_status = item.get('expiration_status', 'none')
        days = item.get('days_to_expiration')

        # Emoji based on status
        emoji_map = {
            'expired': '🔴',
            'critical': '🟠',
            'warning': '🟡',
            'ok': '🟢',
            'fresh': '🔵',
            'none': '⚪'
        }
        emoji = emoji_map.get(exp_status, '⚪')

        print(f"{emoji} {item['description']}")
        print(f"   Pantry level: {item['level_percent']}%")

        if days is not None:
            print(f"   Expires: {item['expiration_date']} ({days} days)")
        else:
            print(f"   Expires: Never (no expiration tracking)")

        print(f"   Status: {exp_status}")
        print()


def test_unified_attention_tool():
    """Test 5: Unified attention tool (what needs attention now)."""
    print("\n=== TEST 5: Unified Attention Tool ===\n")
    print("Simulating 'get_pantry_attention()' - one tool for everything!\n")

    # Manually set some items to need attention
    conn = get_db_connection()

    # Set berries to expire soon (2 days)
    future_date = (datetime.now() + timedelta(days=2)).date().isoformat()
    conn.execute("""
        UPDATE pantry_items
        SET expiration_date = ?, days_to_expiration = 2
        WHERE product_id = 'TEST_BERRIES'
    """, (future_date,))

    # Set milk to low inventory
    conn.execute("""
        UPDATE pantry_items
        SET level_percent = 15
        WHERE product_id = 'TEST_MILK'
    """)

    conn.commit()
    conn.close()

    # Get pantry status to check what needs attention
    items = get_pantry_status(apply_depletion=True)

    attention_items = []
    for item in items:
        needs_attention = False
        reasons = []

        # Check expiration
        exp_status = item.get('expiration_status', 'none')
        if exp_status in ['expired', 'critical', 'warning']:
            needs_attention = True
            days = item.get('days_to_expiration', 0)
            if exp_status == 'expired':
                reasons.append(f"EXPIRED {abs(days)} days ago")
            elif exp_status == 'critical':
                reasons.append(f"Expires in {days} days")
            else:
                reasons.append(f"Expiring soon ({days} days)")

        # Check pantry level
        level = item.get('level_percent', 100)
        if level <= 10:
            needs_attention = True
            reasons.append(f"Critical inventory ({level}%)")
        elif level <= 25:
            needs_attention = True
            reasons.append(f"Low inventory ({level}%)")

        if needs_attention:
            attention_items.append({
                'description': item['description'],
                'reasons': reasons
            })

    print("Items needing attention:\n")
    for item in attention_items:
        print(f"⚠️  {item['description']}")
        for reason in item['reasons']:
            print(f"   → {reason}")
        print()

    if not attention_items:
        print("✓ No items need attention right now!\n")


def test_recommendations_with_expiration():
    """Test 6: Recommendations include expiration urgency."""
    print("\n=== TEST 6: Recommendations with Expiration ===\n")

    # Get recommendations
    result = get_comprehensive_recommendations(
        days_ahead=14,
        include_low_pantry=True,
        include_deals=False,
        include_predictions=True,
        min_score=20,
        max_results=10
    )

    urgent = result.get('urgent_needs', [])

    if urgent:
        print(f"Found {len(urgent)} urgent recommendations:\n")

        for rec in urgent[:5]:  # Show top 5
            print(f"🔴 {rec['description']}")
            print(f"   Score: {rec['score']}/100")
            print(f"   Reason: {rec['reason_summary']}")

            # Show urgency factors
            urgency = rec.get('urgency_factors', {})
            if urgency.get('expiration_urgency'):
                exp_urgency = urgency['expiration_urgency']
                days = rec.get('urgency_factors', {}).get('days_to_expiration', 0)
                print(f"   Expiration: {exp_urgency} ({days} days)")

            if urgency.get('pantry_urgency'):
                pantry_urgency = urgency['pantry_urgency']
                print(f"   Pantry: {pantry_urgency}")

            print()
    else:
        print("No urgent recommendations at this time.\n")

    # Show summary
    summary = result.get('summary', {})
    print(f"Summary:")
    print(f"  Total recommendations: {summary.get('total_recommendations', 0)}")
    print(f"  Urgent needs: {summary.get('urgent_needs_count', 0)}")
    print(f"  Items low in pantry: {summary.get('items_low_pantry', 0)}")


def main():
    """Run all manual tests."""
    print("\n" + "="*70)
    print("AUTOMATIC EXPIRATION TRACKING - END-TO-END TEST")
    print("="*70)

    # Initialize database
    ensure_initialized()

    # Setup test data
    setup_test_data()

    # Run tests
    test_automatic_expiration_calculation()
    test_frozen_items()
    test_treat_no_expiration()
    test_pantry_status_with_expiration()
    test_unified_attention_tool()
    test_recommendations_with_expiration()

    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED!")
    print("="*70)
    print("\nKey Takeaway:")
    print("  → Expiration dates are 100% AUTOMATIC")
    print("  → No user input needed when marking orders as placed")
    print("  → System calculates based on product category + shelf life")
    print("  → One unified tool shows everything needing attention")
    print()


if __name__ == '__main__':
    main()
