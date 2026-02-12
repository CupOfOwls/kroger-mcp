"""
Tests for the comprehensive recommendation engine.
"""

import pytest
from datetime import datetime, timedelta
from src.kroger_mcp.analytics.recommendations import (
    calculate_recommendation_score,
    get_priority_tier,
    get_comprehensive_recommendations,
    _build_reason_summary
)


class TestScoringAlgorithm:
    """Test the multi-factor scoring algorithm."""

    def test_scoring_critical_pantry(self):
        """Pantry <= 10% should give 40 urgency points."""
        data = {'pantry_level': 5}
        score, factors = calculate_recommendation_score(data)

        assert factors['urgency']['pantry_urgency'] == 'critical'
        assert factors['urgency']['total_score'] == 40
        assert score >= 40

    def test_scoring_high_pantry(self):
        """Pantry 11-25% should give 30 urgency points."""
        data = {'pantry_level': 20}
        score, factors = calculate_recommendation_score(data)

        assert factors['urgency']['pantry_urgency'] == 'high'
        assert factors['urgency']['total_score'] == 30
        assert score >= 30

    def test_scoring_medium_pantry(self):
        """Pantry 26-40% should give 20 urgency points."""
        data = {'pantry_level': 35}
        score, factors = calculate_recommendation_score(data)

        assert factors['urgency']['pantry_urgency'] == 'medium'
        assert factors['urgency']['total_score'] == 20
        assert score >= 20

    def test_scoring_overdue_repurchase(self):
        """Overdue items should add 1 point per day up to 15."""
        data = {'days_until_purchase': -10}
        score, factors = calculate_recommendation_score(data)

        assert factors['urgency']['overdue_days'] == 10
        assert factors['urgency']['overdue_points'] == 10
        assert score >= 10

    def test_scoring_overdue_capped(self):
        """Overdue points should cap at 15."""
        data = {'days_until_purchase': -30}
        score, factors = calculate_recommendation_score(data)

        assert factors['urgency']['overdue_points'] == 15

    def test_scoring_exceptional_deal(self):
        """40%+ savings should give 25 deal points."""
        data = {'on_sale': True, 'savings_percent': 45}
        score, factors = calculate_recommendation_score(data)

        assert factors['deals']['quality'] == 'exceptional'
        assert factors['deals']['total_score'] == 25
        assert score >= 25

    def test_scoring_excellent_deal(self):
        """25-39% savings should give 20 deal points."""
        data = {'on_sale': True, 'savings_percent': 30}
        score, factors = calculate_recommendation_score(data)

        assert factors['deals']['quality'] == 'excellent'
        assert factors['deals']['total_score'] == 20

    def test_scoring_very_good_deal(self):
        """15-24% savings should give 15 deal points."""
        data = {'on_sale': True, 'savings_percent': 18}
        score, factors = calculate_recommendation_score(data)

        assert factors['deals']['quality'] == 'very_good'
        assert factors['deals']['total_score'] == 15

    def test_scoring_good_deal(self):
        """10-14% savings should give 10 deal points."""
        data = {'on_sale': True, 'savings_percent': 12}
        score, factors = calculate_recommendation_score(data)

        assert factors['deals']['quality'] == 'good'
        assert factors['deals']['total_score'] == 10

    def test_scoring_best_price_bonus(self):
        """Price ≤105% of 30-day low should add 10 bonus points."""
        data = {
            'current_price': 3.00,
            'avg_price_30d': 3.20
        }
        score, factors = calculate_recommendation_score(data)

        assert factors['deals']['at_best_price'] == True
        assert factors['deals']['best_price_bonus'] == 10

    def test_scoring_favorites_bonus(self):
        """In favorites should add 10 relevance points."""
        data = {'in_favorites': True}
        score, factors = calculate_recommendation_score(data)

        assert factors['relevance']['in_favorites'] == True
        assert score >= 10

    def test_scoring_high_frequency(self):
        """Frequency score ≥0.8 should add 10 relevance points."""
        data = {'purchase_frequency_score': 0.85}
        score, factors = calculate_recommendation_score(data)

        assert factors['relevance']['frequency_level'] == 'very_high'
        assert score >= 10

    def test_scoring_medium_frequency(self):
        """Frequency score 0.5-0.79 should add 5 relevance points."""
        data = {'purchase_frequency_score': 0.65}
        score, factors = calculate_recommendation_score(data)

        assert factors['relevance']['frequency_level'] == 'medium'
        assert score >= 5

    def test_scoring_recently_purchased(self):
        """Last purchased ≤30 days should add 5 relevance points."""
        data = {'last_purchase_days_ago': 20}
        score, factors = calculate_recommendation_score(data)

        assert factors['relevance']['recently_purchased'] == True
        assert score >= 5

    def test_scoring_optimal_timing(self):
        """Days until purchase 0-7 should add 10 timing points."""
        data = {'days_until_purchase': 5}
        score, factors = calculate_recommendation_score(data)

        assert factors['timing']['window'] == 'optimal'
        assert factors['timing']['total_score'] == 10

    def test_scoring_good_timing(self):
        """Days until purchase 8-14 should add 5 timing points."""
        data = {'days_until_purchase': 10}
        score, factors = calculate_recommendation_score(data)

        assert factors['timing']['window'] == 'good'
        assert factors['timing']['total_score'] == 5

    def test_scoring_seasonal_bonus(self):
        """Seasonal items should add 5 timing points."""
        data = {'is_seasonal': True}
        score, factors = calculate_recommendation_score(data)

        assert factors['timing']['seasonal'] == True

    def test_scoring_maximum_score(self):
        """Maximum possible score should be 100."""
        data = {
            'pantry_level': 8,  # 40 points
            'days_until_purchase': -15,  # 15 points
            'on_sale': True,
            'savings_percent': 45,  # 25 points
            'current_price': 2.50,
            'avg_price_30d': 3.00,  # 10 points
            'in_favorites': True,  # 10 points
            'purchase_frequency_score': 0.9,  # 10 points
            'last_purchase_days_ago': 10,  # 5 points
            'is_seasonal': True  # 5 points
        }
        score, factors = calculate_recommendation_score(data)

        # Note: days_until_purchase of 5 would give 10 more points
        # So max would be with days_until_purchase: 5 instead of -15
        assert score <= 100


class TestPriorityTiers:
    """Test priority tier assignment."""

    def test_priority_tier_urgent(self):
        """Score 80-100 should map to 'urgent' tier."""
        assert get_priority_tier(85) == 'urgent'
        assert get_priority_tier(80) == 'urgent'
        assert get_priority_tier(100) == 'urgent'

    def test_priority_tier_high_value(self):
        """Score 60-79 should map to 'high_value' tier."""
        assert get_priority_tier(70) == 'high_value'
        assert get_priority_tier(60) == 'high_value'
        assert get_priority_tier(79) == 'high_value'

    def test_priority_tier_good_timing(self):
        """Score 40-59 should map to 'good_timing' tier."""
        assert get_priority_tier(50) == 'good_timing'
        assert get_priority_tier(40) == 'good_timing'
        assert get_priority_tier(59) == 'good_timing'

    def test_priority_tier_nice_to_have(self):
        """Score 20-39 should map to 'nice_to_have' tier."""
        assert get_priority_tier(30) == 'nice_to_have'
        assert get_priority_tier(20) == 'nice_to_have'
        assert get_priority_tier(39) == 'nice_to_have'

    def test_priority_tier_optional(self):
        """Score 0-19 should map to 'optional' tier."""
        assert get_priority_tier(10) == 'optional'
        assert get_priority_tier(0) == 'optional'
        assert get_priority_tier(19) == 'optional'


class TestReasonSummary:
    """Test reason summary generation."""

    def test_reason_critical_pantry(self):
        """Critical pantry should be in reason summary."""
        factors = {
            'urgency': {'pantry_urgency': 'critical'},
            'deals': {},
            'relevance': {},
            'timing': {}
        }
        product_data = {'pantry_level': 5}
        summary = _build_reason_summary(factors, product_data)

        assert 'Critical pantry level' in summary
        assert '5%' in summary

    def test_reason_overdue(self):
        """Overdue status should be in reason summary."""
        factors = {
            'urgency': {'overdue_days': 3},
            'deals': {},
            'relevance': {},
            'timing': {}
        }
        product_data = {}
        summary = _build_reason_summary(factors, product_data)

        assert 'Overdue by 3 days' in summary

    def test_reason_on_sale(self):
        """Sale status should be in reason summary."""
        factors = {
            'urgency': {},
            'deals': {'on_sale': True},
            'relevance': {},
            'timing': {}
        }
        product_data = {'savings_percent': 25}
        summary = _build_reason_summary(factors, product_data)

        assert '25% off' in summary

    def test_reason_favorites(self):
        """Favorites should be in reason summary."""
        factors = {
            'urgency': {},
            'deals': {},
            'relevance': {'in_favorites': True},
            'timing': {}
        }
        product_data = {}
        summary = _build_reason_summary(factors, product_data)

        assert 'In favorites' in summary

    def test_reason_multiple_factors(self):
        """Multiple factors should be joined with '+'."""
        factors = {
            'urgency': {'pantry_urgency': 'high'},
            'deals': {'on_sale': True},
            'relevance': {'in_favorites': True},
            'timing': {}
        }
        product_data = {'pantry_level': 20, 'savings_percent': 30}
        summary = _build_reason_summary(factors, product_data)

        assert '+' in summary
        assert 'Low pantry' in summary
        assert '30% off' in summary
        assert 'In favorites' in summary


class TestComprehensiveRecommendations:
    """Test the full recommendation engine (requires test database)."""

    @pytest.mark.integration
    def test_recommendations_structure(self):
        """Verify recommendations return expected structure."""
        result = get_comprehensive_recommendations(
            days_ahead=14,
            max_results=10
        )

        assert result['success'] == True
        assert 'urgent_needs' in result
        assert 'high_value_deals' in result
        assert 'good_timing' in result
        assert 'nice_to_have' in result
        assert 'summary' in result

    @pytest.mark.integration
    def test_recommendations_summary_stats(self):
        """Verify summary statistics are calculated."""
        result = get_comprehensive_recommendations()

        summary = result['summary']
        assert 'total_recommendations' in summary
        assert 'urgent_needs_count' in summary
        assert 'high_value_deals_count' in summary
        assert 'good_timing_count' in summary
        assert 'nice_to_have_count' in summary
        assert 'avg_score' in summary
        assert 'highest_score' in summary
        assert 'estimated_total_savings' in summary

    @pytest.mark.integration
    def test_recommendations_min_score_filter(self):
        """Should filter items below min_score."""
        result = get_comprehensive_recommendations(min_score=60)

        # All returned items should have score >= 60
        for tier in ['urgent_needs', 'high_value_deals', 'good_timing']:
            for item in result[tier]:
                assert item['score'] >= 60

    @pytest.mark.integration
    def test_recommendations_max_results_limit(self):
        """Should limit total results to max_results."""
        result = get_comprehensive_recommendations(max_results=20)

        total = (
            len(result['urgent_needs']) +
            len(result['high_value_deals']) +
            len(result['good_timing']) +
            len(result['nice_to_have'])
        )
        assert total <= 20

    @pytest.mark.integration
    def test_recommendations_favorites_only(self):
        """Should only return items in favorite lists."""
        result = get_comprehensive_recommendations(
            include_favorites_only=True,
            max_results=10
        )

        # All returned items should be in favorites
        for tier in ['urgent_needs', 'high_value_deals', 'good_timing', 'nice_to_have']:
            for item in result[tier]:
                assert item['relevance_factors'].get('in_favorites') == True


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
