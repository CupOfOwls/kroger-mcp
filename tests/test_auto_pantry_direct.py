#!/usr/bin/env python3
"""
Direct test of auto-pantry integration using internal functions.
Tests the _add_item_to_local_cart function that contains the auto-pantry logic.
"""

import sys
import os
import sqlite3
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from kroger_mcp.tools.cart_tools import _add_item_to_local_cart
from kroger_mcp.analytics.pantry import get_pantry_status, get_pantry_item
from kroger_mcp.analytics.database import ensure_initialized


def setup_test_environment():
    """Ensure fresh test database"""
    # Initialize database first
    ensure_initialized()
    print("✓ Database initialized")

    # Use the database from the current directory (where the project is)
    db_path = "kroger_analytics.db"

    # Clear pantry and cart for clean test
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Clear test products (only from tables that exist)
    try:
        cursor.execute("DELETE FROM pantry_items WHERE product_id LIKE 'TEST_%'")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("DELETE FROM cart WHERE product_id LIKE 'TEST_%'")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("DELETE FROM products WHERE product_id LIKE 'TEST_%'")
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()
    print("✓ Test environment prepared\n")


def test_add_item_to_cart_adds_to_pantry():
    """Test that _add_item_to_local_cart automatically adds to pantry"""
    print("=" * 60)
    print("TEST: Auto-Add to Pantry Integration")
    print("=" * 60)

    product_id = "TEST_PRODUCT_AUTO_001"

    # Get pantry state before
    pantry_before = get_pantry_status(apply_depletion=False)
    items_before = [item["product_id"] for item in pantry_before]
    print(f"Pantry before: {len(items_before)} items")

    # Add item to cart (this should auto-add to pantry)
    print(f"\nAdding {product_id} to cart...")

    try:
        _add_item_to_local_cart(
            product_id=product_id,
            quantity=1,
            modality="PICKUP",
            product_details={
                "description": "Test Product Auto",
                "brand": "Test Brand",
                "categories": ["Test"],
                "images": [],
                "aisle": None,
                "pricing": None
            }
        )
        print(f"✓ Cart add successful")
    except Exception as e:
        print(f"✗ Cart add failed: {e}")
        return False

    # Get pantry state after
    pantry_after = get_pantry_status(apply_depletion=False)
    items_after = [item["product_id"] for item in pantry_after]
    print(f"\nPantry after: {len(items_after)} items")

    # Check if our product was added to pantry
    if product_id in items_after:
        print(f"✓ Product {product_id} found in pantry")

        # Get details
        item = next(item for item in pantry_after
                   if item["product_id"] == product_id)

        print(f"\nPantry Entry Details:")
        print(f"  - Product ID: {item['product_id']}")
        print(f"  - Description: {item['description']}")
        print(f"  - Level: {item['level_percent']}%")
        print(f"  - Auto-deplete: {item['auto_deplete']}")
        print(f"  - Low threshold: {item['low_threshold']}%")
        print(f"  - Daily depletion rate: {item['daily_depletion_rate']}")

        # Verify defaults
        checks = []
        checks.append(("Level is 100%", item['level_percent'] == 100))
        checks.append(("Auto-deplete enabled", item['auto_deplete'] == 1))
        checks.append(("Low threshold is 20%", item['low_threshold'] == 20))

        print("\nDefault Values Verification:")
        all_passed = True
        for check_name, check_result in checks:
            status = "✓" if check_result else "✗"
            print(f"  {status} {check_name}")
            if not check_result:
                all_passed = False

        return all_passed
    else:
        print(f"✗ Product {product_id} NOT found in pantry")
        print(f"\nPantry contents: {items_after}")
        return False


def test_duplicate_protection():
    """Test that adding same item twice doesn't create duplicates"""
    print("\n" + "=" * 60)
    print("TEST: Duplicate Protection (Upsert Behavior)")
    print("=" * 60)

    product_id = "TEST_PRODUCT_DUPLICATE"

    # Add first time
    print(f"Adding {product_id} to cart (first time)...")
    try:
        _add_item_to_local_cart(
            product_id=product_id,
            quantity=1,
            modality="PICKUP",
            product_details={
                "description": "Test Duplicate",
                "brand": "Test",
                "categories": [],
                "images": [],
                "aisle": None,
                "pricing": None
            }
        )
    except Exception as e:
        print(f"✗ First add failed: {e}")
        return False

    # Get pantry count after first add
    pantry = get_pantry_status(apply_depletion=False)
    count_after_first = sum(1 for item in pantry
                           if item["product_id"] == product_id)

    print(f"✓ First add successful - pantry entries: {count_after_first}")

    # Add second time (same product)
    print(f"\nAdding {product_id} to cart (second time)...")
    try:
        _add_item_to_local_cart(
            product_id=product_id,
            quantity=2,
            modality="PICKUP",
            product_details={
                "description": "Test Duplicate Updated",
                "brand": "Test",
                "categories": [],
                "images": [],
                "aisle": None,
                "pricing": None
            }
        )
    except Exception as e:
        print(f"✗ Second add failed: {e}")
        return False

    # Check for duplicates
    pantry = get_pantry_status(apply_depletion=False)
    count_after_second = sum(1 for item in pantry
                            if item["product_id"] == product_id)

    print(f"✓ Second add successful - pantry entries: {count_after_second}")

    if count_after_second == 1:
        print(f"\n✓ PASS: Only ONE pantry entry (upsert working correctly)")
        return True
    else:
        print(f"\n✗ FAIL: Found {count_after_second} entries (expected 1)")
        return False


def test_code_has_exception_handling():
    """Verify exception handling is present in code"""
    print("\n" + "=" * 60)
    print("TEST: Exception Handling Verification")
    print("=" * 60)

    from kroger_mcp.tools import cart_tools
    import inspect

    source = inspect.getsource(cart_tools._add_item_to_local_cart)

    # Check for our auto-pantry code
    checks = [
        ("Contains add_to_pantry import", "from ..analytics.pantry import add_to_pantry" in source),
        ("Contains add_to_pantry call", "add_to_pantry(product_id=product_id)" in source),
        ("Wrapped in try/except", "try:" in source and "except Exception:" in source),
        ("Has silent failure", "pass  # Don't fail cart operations if pantry add fails" in source),
    ]

    all_passed = True
    for check_name, result in checks:
        status = "✓" if result else "✗"
        print(f"  {status} {check_name}")
        if not result:
            all_passed = False

    if all_passed:
        print("\n✓ PASS: All exception handling checks passed")
    else:
        print("\n✗ FAIL: Some exception handling checks failed")

    return all_passed


def run_all_tests():
    """Run all test scenarios"""
    print("\n")
    print("╔" + "═" * 58 + "╗")
    print("║" + " " * 10 + "AUTO-PANTRY INTEGRATION TESTS" + " " * 19 + "║")
    print("╚" + "═" * 58 + "╝")
    print()

    setup_test_environment()

    results = {
        "Auto-Add to Pantry": test_add_item_to_cart_adds_to_pantry(),
        "Duplicate Protection": test_duplicate_protection(),
        "Exception Handling": test_code_has_exception_handling(),
    }

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(results.values())
    total = len(results)

    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status} - {test_name}")

    print("-" * 60)
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Auto-pantry feature working correctly.")
        return True
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review.")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
