"""
Manual test script for the smart shopping recommendations tool.

Run this to verify the tool works end-to-end with actual database data.
"""

from src.kroger_mcp.analytics.recommendations import get_comprehensive_recommendations
import json


def test_basic_recommendations():
    """Test basic recommendations with default parameters."""
    print("=" * 80)
    print("TEST 1: Basic Recommendations (default params)")
    print("=" * 80)

    result = get_comprehensive_recommendations(
        days_ahead=14,
        max_results=10
    )

    print(f"\nSuccess: {result['success']}")
    print(f"\nSummary:")
    print(json.dumps(result['summary'], indent=2))

    print(f"\nUrgent Needs ({len(result['urgent_needs'])}):")
    for item in result['urgent_needs'][:3]:
        print(f"  - {item['description']} (score: {item['score']})")
        print(f"    Reason: {item['reason_summary']}")

    print(f"\nHigh Value Deals ({len(result['high_value_deals'])}):")
    for item in result['high_value_deals'][:3]:
        print(f"  - {item['description']} (score: {item['score']})")
        print(f"    Reason: {item['reason_summary']}")


def test_urgent_only():
    """Test filtering for urgent items only."""
    print("\n" + "=" * 80)
    print("TEST 2: Urgent Items Only (min_score=80)")
    print("=" * 80)

    result = get_comprehensive_recommendations(
        min_score=80,
        max_results=20
    )

    print(f"\nTotal recommendations: {result['summary']['total_recommendations']}")
    print(f"All items should have score >= 80")

    for item in result['urgent_needs'][:5]:
        print(f"  - {item['description']} (score: {item['score']})")
        assert item['score'] >= 80, f"Item has score {item['score']} < 80!"

    print("✓ All items meet min_score requirement")


def test_favorites_only():
    """Test filtering for favorites only."""
    print("\n" + "=" * 80)
    print("TEST 3: Favorites Only")
    print("=" * 80)

    result = get_comprehensive_recommendations(
        include_favorites_only=True,
        max_results=15
    )

    print(f"\nTotal recommendations: {result['summary']['total_recommendations']}")
    print(f"Items in favorites: {result['summary']['items_in_favorites']}")

    # Verify all items are in favorites
    all_items = (
        result['urgent_needs'] +
        result['high_value_deals'] +
        result['good_timing'] +
        result['nice_to_have']
    )

    for item in all_items[:5]:
        in_fav = item['relevance_factors'].get('in_favorites', False)
        print(f"  - {item['description']} (in_favorites: {in_fav})")
        assert in_fav, f"Item {item['description']} not in favorites!"

    print("✓ All items are in favorites")


def test_deals_focus():
    """Test focusing on deals."""
    print("\n" + "=" * 80)
    print("TEST 4: Focus on Deals")
    print("=" * 80)

    result = get_comprehensive_recommendations(
        include_deals=True,
        include_low_pantry=False,
        min_score=50,  # High-value items
        max_results=20
    )

    print(f"\nTotal recommendations: {result['summary']['total_recommendations']}")
    print(f"Items on sale: {result['summary']['items_on_sale']}")
    print(f"Estimated savings: ${result['summary']['estimated_total_savings']:.2f}")

    print("\nTop deals:")
    for item in result['high_value_deals'][:5]:
        deal = item['deal_factors']
        if deal.get('on_sale'):
            print(f"  - {item['description']}")
            print(f"    Save {deal.get('savings_percent', 0):.0f}% (score: {item['score']})")


def test_comprehensive_output():
    """Test full output structure."""
    print("\n" + "=" * 80)
    print("TEST 5: Comprehensive Output Structure")
    print("=" * 80)

    result = get_comprehensive_recommendations(max_results=5)

    # Check structure
    assert 'success' in result
    assert 'urgent_needs' in result
    assert 'high_value_deals' in result
    assert 'good_timing' in result
    assert 'nice_to_have' in result
    assert 'summary' in result

    print("✓ All required keys present")

    # Check summary fields
    summary = result['summary']
    required_summary_fields = [
        'total_recommendations',
        'urgent_needs_count',
        'high_value_deals_count',
        'good_timing_count',
        'nice_to_have_count',
        'avg_score',
        'highest_score',
        'estimated_total_savings',
        'items_on_sale',
        'items_in_favorites',
        'items_low_pantry'
    ]

    for field in required_summary_fields:
        assert field in summary, f"Missing summary field: {field}"

    print("✓ All summary fields present")

    # Check item structure
    all_items = (
        result['urgent_needs'] +
        result['high_value_deals'] +
        result['good_timing'] +
        result['nice_to_have']
    )

    if all_items:
        item = all_items[0]
        required_item_fields = [
            'product_id',
            'description',
            'score',
            'priority_tier',
            'reason_summary',
            'urgency_factors',
            'deal_factors',
            'relevance_factors',
            'timing_factors',
            'purchase_stats'
        ]

        for field in required_item_fields:
            assert field in item, f"Missing item field: {field}"

        print("✓ All item fields present")
        print(f"\nSample item structure:")
        print(json.dumps(item, indent=2, default=str))


if __name__ == '__main__':
    try:
        print("\n" + "=" * 80)
        print("MANUAL TEST: Smart Shopping Recommendations")
        print("=" * 80)

        test_basic_recommendations()
        test_urgent_only()
        test_favorites_only()
        test_deals_focus()
        test_comprehensive_output()

        print("\n" + "=" * 80)
        print("✓ ALL MANUAL TESTS PASSED")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
