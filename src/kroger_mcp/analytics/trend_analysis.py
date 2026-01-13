"""
Trend analysis utilities for purchase patterns.

Provides trend detection, recency scoring, and enhanced confidence calculations.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple


def detect_trend(intervals: List[float], window: int = 5) -> Tuple[str, float]:
    """
    Detect trend in purchase intervals using simple linear regression.

    Args:
        intervals: List of days between purchases (oldest to newest)
        window: Number of recent intervals to analyze

    Returns:
        Tuple of (direction, strength):
        - direction: 'increasing', 'decreasing', or 'stable'
        - strength: 0-1 indicating how strong the trend is
    """
    if len(intervals) < 3:
        return ('stable', 0.0)

    # Use most recent intervals
    recent = intervals[-window:] if len(intervals) >= window else intervals

    n = len(recent)
    if n < 3:
        return ('stable', 0.0)

    # Simple linear regression: y = mx + b
    # x = index (0, 1, 2, ...), y = interval
    sum_x = sum(range(n))
    sum_y = sum(recent)
    sum_xy = sum(i * v for i, v in enumerate(recent))
    sum_x2 = sum(i * i for i in range(n))

    # Calculate slope
    denominator = n * sum_x2 - sum_x * sum_x
    if denominator == 0:
        return ('stable', 0.0)

    slope = (n * sum_xy - sum_x * sum_y) / denominator

    # Calculate mean for normalization
    mean = sum_y / n if n > 0 else 1

    # Normalize slope as percentage of mean
    if mean > 0:
        normalized_slope = slope / mean
    else:
        normalized_slope = 0

    # Determine direction and strength
    # Threshold: >5% change per interval is significant
    threshold = 0.05

    if normalized_slope > threshold:
        # Intervals increasing = buying less frequently
        direction = 'decreasing'  # Consumption decreasing
        strength = min(1.0, abs(normalized_slope) / 0.3)
    elif normalized_slope < -threshold:
        # Intervals decreasing = buying more frequently
        direction = 'increasing'  # Consumption increasing
        strength = min(1.0, abs(normalized_slope) / 0.3)
    else:
        direction = 'stable'
        strength = 0.0

    return (direction, round(strength, 2))


def calculate_recency_score(last_purchase_date: Optional[str]) -> float:
    """
    Calculate a recency score based on how recent the last purchase was.

    More recent = higher score = more confidence in pattern.

    Args:
        last_purchase_date: ISO format date string

    Returns:
        Score from 0-1 (1 = purchased today, 0 = >180 days ago)
    """
    if not last_purchase_date:
        return 0.0

    try:
        if 'T' in last_purchase_date:
            last_date = datetime.fromisoformat(
                last_purchase_date.replace('Z', '+00:00'))
        else:
            last_date = datetime.strptime(last_purchase_date, '%Y-%m-%d')
    except (ValueError, TypeError):
        return 0.0

    days_ago = (datetime.now() - last_date).days

    # Score decreases linearly over 180 days
    if days_ago <= 0:
        return 1.0
    elif days_ago >= 180:
        return 0.0
    else:
        return 1.0 - (days_ago / 180)


def calculate_quantity_consistency(quantities: List[int]) -> float:
    """
    Calculate how consistent purchase quantities are.

    Higher consistency = more predictable pattern.

    Args:
        quantities: List of purchase quantities

    Returns:
        Score from 0-1 (1 = always same quantity, 0 = highly variable)
    """
    if len(quantities) < 2:
        return 0.5  # Neutral

    mean = sum(quantities) / len(quantities)
    if mean == 0:
        return 0.5

    # Calculate coefficient of variation (std/mean)
    variance = sum((q - mean) ** 2 for q in quantities) / len(quantities)
    std_dev = variance ** 0.5

    cv = std_dev / mean

    # Convert to consistency score (lower CV = higher consistency)
    # CV of 0.5 is considered moderate variability
    consistency = max(0.0, 1.0 - cv)

    return round(consistency, 2)


def calculate_enhanced_confidence(
    sample_size: int,
    interval_consistency: float,
    recency_score: float,
    quantity_consistency: float,
    max_samples: int = 10
) -> float:
    """
    Calculate enhanced confidence score using multiple factors.

    Args:
        sample_size: Number of purchase intervals
        interval_consistency: How consistent intervals are (0-1)
        recency_score: How recent last purchase was (0-1)
        quantity_consistency: How consistent quantities are (0-1)
        max_samples: Sample size at which data confidence maxes out

    Returns:
        Confidence score from 0-1
    """
    # Data confidence (more samples = more confident)
    data_confidence = min(1.0, sample_size / max_samples)

    # Weight factors
    weights = {
        'data': 0.35,
        'interval': 0.30,
        'recency': 0.20,
        'quantity': 0.15
    }

    confidence = (
        weights['data'] * data_confidence +
        weights['interval'] * interval_consistency +
        weights['recency'] * recency_score +
        weights['quantity'] * quantity_consistency
    )

    return round(min(1.0, max(0.0, confidence)), 2)


def calculate_quantity_adjusted_rate(
    intervals: List[float],
    quantities: List[int]
) -> Optional[float]:
    """
    Calculate days-per-unit consumption rate.

    This accounts for varying purchase quantities.

    Args:
        intervals: Days between consecutive purchases
        quantities: Quantity purchased at each interval's end point

    Returns:
        Average days per unit consumed, or None if insufficient data
    """
    if len(intervals) < 1 or len(quantities) < 2:
        return None

    # Each interval corresponds to consuming the quantity purchased at start
    # intervals[i] = days between purchase[i] and purchase[i+1]
    # During intervals[i], we consumed quantities[i]

    days_per_unit = []
    for i, interval in enumerate(intervals):
        quantity = quantities[i] if i < len(quantities) else 1
        if quantity > 0 and interval > 0:
            days_per_unit.append(interval / quantity)

    if not days_per_unit:
        return None

    return round(sum(days_per_unit) / len(days_per_unit), 2)


def predict_with_trend_adjustment(
    base_prediction_days: float,
    trend_direction: str,
    trend_strength: float,
    adjustment_factor: float = 0.15
) -> float:
    """
    Adjust prediction based on detected trend.

    Args:
        base_prediction_days: Base prediction in days
        trend_direction: 'increasing', 'decreasing', or 'stable'
        trend_strength: 0-1 strength of trend
        adjustment_factor: Maximum adjustment as fraction of base

    Returns:
        Adjusted prediction in days
    """
    if trend_direction == 'stable' or trend_strength < 0.2:
        return base_prediction_days

    max_adjustment = base_prediction_days * adjustment_factor * trend_strength

    if trend_direction == 'increasing':
        # Consuming faster, predict sooner
        return base_prediction_days - max_adjustment
    else:
        # Consuming slower, predict later
        return base_prediction_days + max_adjustment
