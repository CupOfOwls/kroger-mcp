"""
Statistical analysis for purchase patterns and consumption rates.

Uses Exponential Weighted Moving Average (EWMA) for consumption rate calculations,
giving more weight to recent purchases.
"""

import statistics as stats
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized


@dataclass
class ConsumptionRate:
    """Represents the calculated consumption rate for a product."""
    days_between: Optional[float]
    std_dev: float
    confidence: float
    sample_size: int


def calculate_consumption_rate(
    purchase_events: List[Dict[str, Any]]
) -> ConsumptionRate:
    """
    Calculate consumption rate using exponential weighted moving average.

    Recent purchases are weighted more heavily than older ones.

    Args:
        purchase_events: List of purchase events sorted by date (oldest first)

    Returns:
        ConsumptionRate with average days between purchases, std dev, and confidence
    """
    if len(purchase_events) < 2:
        return ConsumptionRate(
            days_between=None,
            std_dev=0.0,
            confidence=0.0,
            sample_size=len(purchase_events)
        )

    # Calculate intervals between purchases
    intervals = []
    for i in range(1, len(purchase_events)):
        prev_date = _parse_date(purchase_events[i - 1].get('event_date', ''))
        curr_date = _parse_date(purchase_events[i].get('event_date', ''))

        if prev_date and curr_date:
            days = (curr_date - prev_date).days
            if days > 0:  # Only count positive intervals
                intervals.append(days)

    if not intervals:
        return ConsumptionRate(
            days_between=None,
            std_dev=0.0,
            confidence=0.0,
            sample_size=len(purchase_events)
        )

    # Exponential weighted moving average
    # Weights: newest = 1.0, each older = 0.5x previous
    weights = [0.5 ** i for i in range(len(intervals))]
    weights.reverse()  # Oldest first, so reverse to give newest highest weight

    ewma = sum(w * v for w, v in zip(weights, intervals)) / sum(weights)

    # Standard deviation
    std_dev = stats.stdev(intervals) if len(intervals) > 1 else 0.0

    # Confidence based on:
    # 1. Number of data points (more = higher confidence, max at 10)
    # 2. Consistency (lower std_dev relative to mean = higher confidence)
    data_confidence = min(1.0, len(intervals) / 10)
    if ewma > 0:
        consistency = 1 - min(1.0, std_dev / ewma)
    else:
        consistency = 0.0
    confidence = data_confidence * consistency

    return ConsumptionRate(
        days_between=ewma,
        std_dev=std_dev,
        confidence=confidence,
        sample_size=len(intervals)
    )


def _parse_date(date_str: str) -> Optional[datetime]:
    """Parse a date string to datetime."""
    if not date_str:
        return None
    try:
        # Handle both date-only and full timestamp formats
        if 'T' in date_str:
            return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        return datetime.strptime(date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return None


def update_product_stats(product_id: str) -> Dict[str, Any]:
    """
    Update statistics for a single product.

    Args:
        product_id: The product identifier

    Returns:
        Dict with updated statistics
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get all consumption-related events for this product (sorted by date)
        # Includes both actual orders and pantry depletion feedback
        cursor = conn.execute("""
            SELECT * FROM purchase_events
            WHERE product_id = ? AND event_type IN ('order_placed', 'pantry_depleted')
            ORDER BY event_date ASC
        """, (product_id,))
        events = [dict(row) for row in cursor.fetchall()]

        if not events:
            return {'product_id': product_id, 'total_purchases': 0}

        # Calculate basic stats
        total_purchases = len(events)
        total_quantity = sum(e.get('quantity', 1) for e in events)
        avg_quantity = total_quantity / total_purchases if total_purchases > 0 else 0

        # Calculate consumption rate
        consumption = calculate_consumption_rate(events)

        # Get first and last purchase dates
        first_date = events[0].get('event_date')
        last_date = events[-1].get('event_date')

        # Calculate purchase frequency score (higher = more frequent)
        # Score of 1.0 = daily, 0.1 = every 10 days, etc.
        if consumption.days_between and consumption.days_between > 0:
            frequency_score = 1.0 / consumption.days_between
        else:
            frequency_score = 0.0

        # Calculate seasonality score
        from .seasonal import calculate_seasonality_score
        seasonality = calculate_seasonality_score(events)

        # Detect category based on patterns
        from .categories import detect_category
        detected_cat = detect_category(
            avg_days=consumption.days_between,
            seasonality_score=seasonality,
            total_purchases=total_purchases
        )

        now = datetime.now().isoformat()

        # Upsert statistics
        conn.execute("""
            INSERT INTO product_statistics
            (product_id, total_purchases, total_quantity, avg_quantity_per_purchase,
             avg_days_between_purchases, std_dev_days, last_purchase_date,
             first_purchase_date, purchase_frequency_score, seasonality_score,
             detected_category, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                total_purchases = excluded.total_purchases,
                total_quantity = excluded.total_quantity,
                avg_quantity_per_purchase = excluded.avg_quantity_per_purchase,
                avg_days_between_purchases = excluded.avg_days_between_purchases,
                std_dev_days = excluded.std_dev_days,
                last_purchase_date = excluded.last_purchase_date,
                first_purchase_date = excluded.first_purchase_date,
                purchase_frequency_score = excluded.purchase_frequency_score,
                seasonality_score = excluded.seasonality_score,
                detected_category = excluded.detected_category,
                updated_at = excluded.updated_at
        """, (
            product_id,
            total_purchases,
            total_quantity,
            avg_quantity,
            consumption.days_between,
            consumption.std_dev,
            last_date,
            first_date,
            frequency_score,
            seasonality,
            detected_cat,
            now
        ))
        conn.commit()

        return {
            'product_id': product_id,
            'total_purchases': total_purchases,
            'total_quantity': total_quantity,
            'avg_quantity_per_purchase': avg_quantity,
            'avg_days_between_purchases': consumption.days_between,
            'std_dev_days': consumption.std_dev,
            'confidence': consumption.confidence,
            'last_purchase_date': last_date,
            'first_purchase_date': first_date,
            'purchase_frequency_score': frequency_score,
            'seasonality_score': seasonality,
            'detected_category': detected_cat
        }
    finally:
        conn.close()


def update_all_product_stats(product_ids: List[str]) -> Dict[str, Any]:
    """
    Update statistics for multiple products.

    Args:
        product_ids: List of product identifiers

    Returns:
        Dict with summary of updates
    """
    results = []
    for product_id in product_ids:
        result = update_product_stats(product_id)
        results.append(result)

    return {
        'updated_count': len(results),
        'products': results
    }


def get_product_statistics(product_id: str) -> Optional[Dict[str, Any]]:
    """
    Get cached statistics for a product.

    Args:
        product_id: The product identifier

    Returns:
        Dict with statistics or None if not found
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT ps.*, p.description, p.brand, p.category_type, p.category_override
            FROM product_statistics ps
            LEFT JOIN products p ON ps.product_id = p.product_id
            WHERE ps.product_id = ?
        """, (product_id,))
        row = cursor.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_product_statistics() -> List[Dict[str, Any]]:
    """
    Get statistics for all tracked products.

    Returns:
        List of statistics dictionaries
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT ps.*, p.description, p.brand, p.category_type, p.category_override
            FROM product_statistics ps
            LEFT JOIN products p ON ps.product_id = p.product_id
            ORDER BY ps.last_purchase_date DESC
        """)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
