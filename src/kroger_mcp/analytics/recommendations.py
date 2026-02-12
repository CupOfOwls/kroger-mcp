"""
Comprehensive shopping recommendation engine.

Integrates all available data sources for intelligent shopping suggestions:
- Pantry inventory urgency (running low, critical levels)
- Current deals and price history (savings opportunities)
- Purchase predictions (consumption-based timing)
- Favorite lists (user preferences)
- Purchase frequency (relevance scoring)
- Seasonal patterns (timing optimization)
"""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple
import statistics

from .database import get_db_connection, ensure_initialized
from .predictions import predict_repurchase_date
from .favorites import get_all_favorite_product_ids
from .deals import get_price_statistics


def calculate_recommendation_score(
    product_data: Dict[str, Any]
) -> Tuple[int, Dict[str, Any]]:
    """
    Calculate comprehensive recommendation score from multiple factors.

    Scoring Breakdown (0-100 points total):

    1. URGENCY FACTORS (0-40 points):
       - Pantry level ≤10%: 40 points (critical)
       - Pantry level ≤25%: 30 points (high)
       - Pantry level ≤40%: 20 points (medium)
       - Overdue predicted repurchase: +1 point per day overdue (max 15)

    2. DEAL QUALITY (0-25 points):
       - Savings ≥40%: 25 points (exceptional)
       - Savings ≥25%: 20 points (excellent)
       - Savings ≥15%: 15 points (very good)
       - Savings ≥10%: 10 points (good)
       - Current price ≤105% of 30-day low: +10 points (best price)

    3. RELEVANCE (0-25 points):
       - In favorite lists: +10 points
       - Purchase frequency score ≥0.8: +10 points (very high)
       - Purchase frequency score ≥0.5: +5 points (medium)
       - Last purchased ≤30 days ago: +5 points (recently purchased)

    4. TIMING (0-10 points):
       - Days until predicted purchase 0-7: 10 points (optimal window)
       - Days until predicted purchase 8-14: 5 points (good timing)
       - Upcoming seasonal item: +5 points

    Args:
        product_data: Dict with all product context data

    Returns:
        Tuple of (total_score: int, factors: Dict) where score is 0-100
    """
    score = 0
    factors = {
        "urgency": {},
        "deals": {},
        "relevance": {},
        "timing": {}
    }

    # 1. URGENCY FACTORS (0-40 points)
    urgency_score = 0
    pantry_level = product_data.get('pantry_level')

    if pantry_level is not None:
        if pantry_level <= 10:
            urgency_score += 40
            factors["urgency"]["pantry_urgency"] = "critical"
        elif pantry_level <= 25:
            urgency_score += 30
            factors["urgency"]["pantry_urgency"] = "high"
        elif pantry_level <= 40:
            urgency_score += 20
            factors["urgency"]["pantry_urgency"] = "medium"

        factors["urgency"]["pantry_level"] = pantry_level

    # Overdue repurchase urgency
    days_until = product_data.get('days_until_purchase')
    if days_until is not None and days_until < 0:
        overdue_days = abs(days_until)
        overdue_points = min(overdue_days, 15)  # Cap at 15 points
        urgency_score += overdue_points
        factors["urgency"]["overdue_days"] = overdue_days
        factors["urgency"]["overdue_points"] = overdue_points

    score += urgency_score
    factors["urgency"]["total_score"] = urgency_score

    # 2. DEAL QUALITY (0-25 points)
    deal_score = 0
    savings_percent = product_data.get('savings_percent', 0)
    on_sale = product_data.get('on_sale', False)

    if on_sale and savings_percent > 0:
        if savings_percent >= 40:
            deal_score += 25
            factors["deals"]["quality"] = "exceptional"
        elif savings_percent >= 25:
            deal_score += 20
            factors["deals"]["quality"] = "excellent"
        elif savings_percent >= 15:
            deal_score += 15
            factors["deals"]["quality"] = "very_good"
        elif savings_percent >= 10:
            deal_score += 10
            factors["deals"]["quality"] = "good"

        factors["deals"]["savings_percent"] = savings_percent
        factors["deals"]["on_sale"] = True

    # Best price bonus
    current_price = product_data.get('current_price')
    avg_price_30d = product_data.get('avg_price_30d')

    if current_price and avg_price_30d and current_price <= avg_price_30d * 1.05:
        deal_score += 10
        factors["deals"]["at_best_price"] = True
        factors["deals"]["best_price_bonus"] = 10

    score += deal_score
    factors["deals"]["total_score"] = deal_score

    # 3. RELEVANCE (0-25 points)
    relevance_score = 0

    # In favorites
    if product_data.get('in_favorites', False):
        relevance_score += 10
        factors["relevance"]["in_favorites"] = True

    # Purchase frequency
    frequency_score = product_data.get('purchase_frequency_score', 0)
    if frequency_score >= 0.8:
        relevance_score += 10
        factors["relevance"]["frequency_level"] = "very_high"
    elif frequency_score >= 0.5:
        relevance_score += 5
        factors["relevance"]["frequency_level"] = "medium"

    if frequency_score > 0:
        factors["relevance"]["purchase_frequency_score"] = frequency_score

    # Recently purchased
    last_purchase_days = product_data.get('last_purchase_days_ago')
    if last_purchase_days is not None and last_purchase_days <= 30:
        relevance_score += 5
        factors["relevance"]["recently_purchased"] = True
        factors["relevance"]["last_purchase_days_ago"] = last_purchase_days

    score += relevance_score
    factors["relevance"]["total_score"] = relevance_score

    # 4. TIMING (0-10 points)
    timing_score = 0

    if days_until is not None:
        if 0 <= days_until <= 7:
            timing_score += 10
            factors["timing"]["window"] = "optimal"
        elif 8 <= days_until <= 14:
            timing_score += 5
            factors["timing"]["window"] = "good"

        factors["timing"]["days_until_purchase"] = days_until

    # Seasonal bonus (placeholder for future implementation)
    if product_data.get('is_seasonal', False):
        timing_score += 5
        factors["timing"]["seasonal"] = True

    score += timing_score
    factors["timing"]["total_score"] = timing_score

    # Cap total score at 100
    score = min(score, 100)

    return score, factors


def get_priority_tier(score: int) -> str:
    """
    Map score to priority tier.

    Args:
        score: Recommendation score 0-100

    Returns:
        Priority tier name
    """
    if score >= 80:
        return "urgent"
    elif score >= 60:
        return "high_value"
    elif score >= 40:
        return "good_timing"
    elif score >= 20:
        return "nice_to_have"
    else:
        return "optional"


def get_comprehensive_recommendations(
    days_ahead: int = 14,
    include_low_pantry: bool = True,
    include_deals: bool = True,
    include_predictions: bool = True,
    include_favorites_only: bool = False,
    min_score: int = 20,
    max_results: int = 50,
    location_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Generate comprehensive shopping recommendations.

    Data Integration Flow:
    1. Query base product set with purchase stats
    2. LEFT JOIN pantry status
    3. LEFT JOIN price history for deals
    4. Calculate predictions for each product
    5. Check favorites membership
    6. Score and rank all products
    7. Group into priority tiers
    8. Return structured results

    Args:
        days_ahead: Look ahead window for predictions (1-60 days)
        include_low_pantry: Include items with low inventory levels
        include_deals: Prioritize items currently on sale
        include_predictions: Include consumption-based predictions
        include_favorites_only: Only recommend items in favorite lists
        min_score: Filter out items below this score (0-100)
        max_results: Maximum recommendations to return (1-100)
        location_id: Optional location filter for deals

    Returns:
        Dict with prioritized recommendations grouped by tier
    """
    ensure_initialized()

    # Get favorite product IDs for fast lookup
    favorite_ids = get_all_favorite_product_ids()

    conn = get_db_connection()
    try:
        # Build base query for products with purchase history
        query = """
            SELECT
                ps.product_id,
                p.description,
                p.brand,
                ps.total_purchases,
                ps.avg_days_between_purchases,
                ps.last_purchase_date,
                ps.detected_category,
                ps.purchase_frequency_score,
                pi.level_percent as pantry_level,
                pi.daily_depletion_rate
            FROM product_statistics ps
            LEFT JOIN products p ON ps.product_id = p.product_id
            LEFT JOIN pantry_items pi ON ps.product_id = pi.product_id
            WHERE ps.total_purchases >= 2
        """

        # Apply favorites filter if requested
        if include_favorites_only and favorite_ids:
            placeholders = ','.join('?' * len(favorite_ids))
            query += f" AND ps.product_id IN ({placeholders})"
            params = list(favorite_ids)
        else:
            params = []

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        recommendations = []

        for row in rows:
            product_id = row['product_id']

            # Build product data dict
            product_data = {
                'product_id': product_id,
                'description': row['description'],
                'brand': row['brand'],
                'total_purchases': row['total_purchases'],
                'avg_days_between': row['avg_days_between_purchases'],
                'last_purchase_date': row['last_purchase_date'],
                'category': row['detected_category'],
                'purchase_frequency_score': row['purchase_frequency_score'] or 0,
                'pantry_level': row['pantry_level'],
                'in_favorites': product_id in favorite_ids
            }

            # Calculate last purchase days ago
            if row['last_purchase_date']:
                try:
                    last_purchase = datetime.fromisoformat(row['last_purchase_date'])
                    days_ago = (datetime.now() - last_purchase).days
                    product_data['last_purchase_days_ago'] = days_ago
                except (ValueError, TypeError):
                    product_data['last_purchase_days_ago'] = None

            # Get purchase prediction
            if include_predictions:
                stats = {
                    'product_id': product_id,
                    'description': row['description'],
                    'total_purchases': row['total_purchases'],
                    'avg_days_between_purchases': row['avg_days_between_purchases'],
                    'last_purchase_date': row['last_purchase_date'],
                    'category_type': row['detected_category']
                }
                prediction = predict_repurchase_date(product_id, stats)
                product_data['predicted_date'] = prediction.predicted_date.isoformat() if prediction.predicted_date else None
                product_data['days_until_purchase'] = prediction.days_until
                product_data['prediction_confidence'] = prediction.confidence

            # Get price/deal data
            if include_deals:
                price_stats = get_price_statistics(product_id, location_id)
                if price_stats:
                    product_data['current_price'] = price_stats.get('current_price')
                    product_data['on_sale'] = price_stats.get('on_sale', False)
                    product_data['savings_percent'] = price_stats.get('savings_percent', 0)
                    product_data['savings_amount'] = price_stats.get('savings_amount', 0)
                    product_data['avg_price_30d'] = price_stats.get('avg_price_30d')
                    product_data['min_price_30d'] = price_stats.get('min_price_30d')

            # Calculate recommendation score
            score, factors = calculate_recommendation_score(product_data)

            # Filter by min_score
            if score < min_score:
                continue

            # Filter by pantry urgency if requested
            if include_low_pantry and not product_data.get('pantry_level'):
                # If we want low pantry items but this isn't tracked, skip
                if not include_deals and not include_predictions:
                    continue

            # Build recommendation item
            recommendation = {
                'product_id': product_id,
                'description': row['description'],
                'brand': row['brand'],
                'score': score,
                'priority_tier': get_priority_tier(score),
                'reason_summary': _build_reason_summary(factors, product_data),
                'urgency_factors': factors['urgency'],
                'deal_factors': factors['deals'],
                'relevance_factors': factors['relevance'],
                'timing_factors': factors['timing'],
                'pantry_status': None,
                'purchase_stats': {
                    'total_purchases': row['total_purchases'],
                    'avg_days_between': row['avg_days_between_purchases'],
                    'last_purchased': row['last_purchase_date']
                }
            }

            # Add pantry details if tracked
            if product_data.get('pantry_level') is not None:
                level = product_data['pantry_level']
                # Calculate status based on level
                if level <= 10:
                    status = 'critical'
                elif level <= 25:
                    status = 'low'
                elif level <= 50:
                    status = 'medium'
                else:
                    status = 'ok'

                recommendation['pantry_status'] = {
                    'tracked': True,
                    'level_percent': level,
                    'status': status,
                    'daily_depletion_rate': row['daily_depletion_rate']
                }

            # Add price details if available
            if include_deals and product_data.get('current_price'):
                recommendation['deal_factors']['current_price'] = product_data['current_price']
                recommendation['deal_factors']['avg_price_30d'] = product_data.get('avg_price_30d')

            # Add prediction details if available
            if include_predictions and product_data.get('predicted_date'):
                recommendation['timing_factors']['predicted_date'] = product_data['predicted_date']

            recommendations.append(recommendation)

        # Sort by score (descending)
        recommendations.sort(key=lambda x: x['score'], reverse=True)

        # Limit results
        recommendations = recommendations[:max_results]

        # Group by priority tier
        grouped = {
            'urgent_needs': [],
            'high_value_deals': [],
            'good_timing': [],
            'nice_to_have': []
        }

        for rec in recommendations:
            tier = rec['priority_tier']
            if tier == 'urgent':
                grouped['urgent_needs'].append(rec)
            elif tier == 'high_value':
                grouped['high_value_deals'].append(rec)
            elif tier == 'good_timing':
                grouped['good_timing'].append(rec)
            elif tier == 'nice_to_have':
                grouped['nice_to_have'].append(rec)

        # Calculate summary statistics
        total_savings = sum(
            rec.get('deal_factors', {}).get('savings_amount', 0)
            for rec in recommendations
        )

        items_on_sale = sum(
            1 for rec in recommendations
            if rec.get('deal_factors', {}).get('on_sale', False)
        )

        items_in_favorites = sum(
            1 for rec in recommendations
            if rec.get('relevance_factors', {}).get('in_favorites', False)
        )

        items_low_pantry = sum(
            1 for rec in recommendations
            if rec.get('pantry_status', {}) and rec['pantry_status'].get('level_percent', 100) <= 25
        )

        summary = {
            'total_recommendations': len(recommendations),
            'urgent_needs_count': len(grouped['urgent_needs']),
            'high_value_deals_count': len(grouped['high_value_deals']),
            'good_timing_count': len(grouped['good_timing']),
            'nice_to_have_count': len(grouped['nice_to_have']),
            'avg_score': round(statistics.mean([r['score'] for r in recommendations])) if recommendations else 0,
            'highest_score': max([r['score'] for r in recommendations]) if recommendations else 0,
            'estimated_total_savings': round(total_savings, 2),
            'items_on_sale': items_on_sale,
            'items_in_favorites': items_in_favorites,
            'items_low_pantry': items_low_pantry
        }

        return {
            'success': True,
            **grouped,
            'summary': summary
        }

    finally:
        conn.close()


def _build_reason_summary(factors: Dict[str, Any], product_data: Dict[str, Any]) -> str:
    """
    Build a human-readable summary of why this product is recommended.

    Args:
        factors: Scoring factors breakdown
        product_data: Product context data

    Returns:
        Concise reason summary string
    """
    reasons = []

    # Urgency reasons
    urgency = factors.get('urgency', {})
    if urgency.get('pantry_urgency') == 'critical':
        level = product_data.get('pantry_level', 0)
        reasons.append(f"Critical pantry level ({level}%)")
    elif urgency.get('pantry_urgency') in ['high', 'medium']:
        level = product_data.get('pantry_level', 0)
        reasons.append(f"Low pantry ({level}%)")

    if urgency.get('overdue_days'):
        days = urgency['overdue_days']
        reasons.append(f"Overdue by {days} days")

    # Deal reasons
    deals = factors.get('deals', {})
    if deals.get('on_sale'):
        savings = product_data.get('savings_percent', 0)
        reasons.append(f"{round(savings)}% off")

    if deals.get('at_best_price'):
        reasons.append("Best price")

    # Relevance reasons
    relevance = factors.get('relevance', {})
    if relevance.get('in_favorites'):
        reasons.append("In favorites")

    if relevance.get('frequency_level') == 'very_high':
        reasons.append("Frequently purchased")

    # Timing reasons
    timing = factors.get('timing', {})
    if timing.get('window') == 'optimal':
        reasons.append("Optimal timing")

    return " + ".join(reasons) if reasons else "Recommended"
