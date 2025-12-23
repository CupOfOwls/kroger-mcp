"""
Repurchase prediction engine.

Predicts when items will need to be repurchased based on consumption patterns.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized
from .statistics import get_product_statistics


@dataclass
class RepurchasePrediction:
    """Represents a repurchase prediction for a product."""
    product_id: str
    description: Optional[str]
    category: str
    predicted_date: Optional[datetime]
    days_until: Optional[int]
    urgency: float  # 0-1, higher = more urgent
    urgency_label: str  # low, medium, high, critical
    confidence: float  # 0-1
    last_purchase_date: Optional[str]
    avg_days_between: Optional[float]


def get_urgency_label(urgency: float) -> str:
    """
    Convert numeric urgency to human-readable label.

    Args:
        urgency: Urgency score 0-1

    Returns:
        Label: 'low', 'medium', 'high', or 'critical'
    """
    if urgency >= 0.9:
        return 'critical'
    elif urgency >= 0.7:
        return 'high'
    elif urgency >= 0.4:
        return 'medium'
    else:
        return 'low'


def predict_repurchase_date(
    product_id: str,
    stats: Optional[Dict[str, Any]] = None
) -> RepurchasePrediction:
    """
    Predict when a product will need to be repurchased.

    Args:
        product_id: The product identifier
        stats: Optional pre-fetched statistics

    Returns:
        RepurchasePrediction with date, urgency, and confidence
    """
    ensure_initialized()

    # Get statistics if not provided
    if stats is None:
        stats = get_product_statistics(product_id)

    if not stats or stats.get('total_purchases', 0) < 2:
        return RepurchasePrediction(
            product_id=product_id,
            description=stats.get('description') if stats else None,
            category=stats.get('category_type', 'uncategorized') if stats else 'uncategorized',
            predicted_date=None,
            days_until=None,
            urgency=0.0,
            urgency_label='low',
            confidence=0.0,
            last_purchase_date=None,
            avg_days_between=None
        )

    avg_days = stats.get('avg_days_between_purchases')
    std_dev = stats.get('std_dev_days', 0) or 0
    last_date_str = stats.get('last_purchase_date')
    category = stats.get('category_type', 'uncategorized')
    description = stats.get('description')

    if not avg_days or not last_date_str:
        return RepurchasePrediction(
            product_id=product_id,
            description=description,
            category=category,
            predicted_date=None,
            days_until=None,
            urgency=0.0,
            urgency_label='low',
            confidence=0.0,
            last_purchase_date=last_date_str,
            avg_days_between=avg_days
        )

    # Parse last purchase date
    try:
        if 'T' in last_date_str:
            last_date = datetime.fromisoformat(
                last_date_str.replace('Z', '+00:00'))
        else:
            last_date = datetime.strptime(last_date_str, '%Y-%m-%d')
    except (ValueError, TypeError):
        return RepurchasePrediction(
            product_id=product_id,
            description=description,
            category=category,
            predicted_date=None,
            days_until=None,
            urgency=0.0,
            urgency_label='low',
            confidence=0.0,
            last_purchase_date=last_date_str,
            avg_days_between=avg_days
        )

    # Base prediction: last purchase + average interval
    base_prediction = last_date + timedelta(days=avg_days)

    # Subtract safety buffer based on std dev
    # Routine items: 1 std dev buffer (don't run out!)
    # Regular items: 0.5 std dev buffer
    # Treats: no buffer (less critical)
    if category == 'routine':
        buffer_multiplier = 1.0
    elif category == 'regular':
        buffer_multiplier = 0.5
    else:
        buffer_multiplier = 0.0

    buffer_days = std_dev * buffer_multiplier
    predicted_date = base_prediction - timedelta(days=buffer_days)

    # Calculate days until prediction
    now = datetime.now()
    days_until = (predicted_date - now).days

    # Calculate urgency (0-1)
    # Overdue = urgency 1.0
    # Due today = urgency 0.9
    # 14+ days away = urgency 0
    if days_until < 0:
        urgency = 1.0  # Overdue
    elif days_until == 0:
        urgency = 0.9  # Due today
    elif days_until <= 14:
        urgency = 1 - (days_until / 14)
    else:
        urgency = 0.0

    # Boost urgency for routine items
    if category == 'routine' and urgency > 0:
        urgency = min(1.0, urgency * 1.2)

    # Calculate confidence
    total_purchases = stats.get('total_purchases', 0)
    data_confidence = min(1.0, total_purchases / 10)

    # Consistency score (lower variance = higher confidence)
    if avg_days > 0:
        consistency = 1 - min(1.0, std_dev / avg_days)
    else:
        consistency = 0.0

    confidence = data_confidence * consistency

    return RepurchasePrediction(
        product_id=product_id,
        description=description,
        category=category,
        predicted_date=predicted_date,
        days_until=days_until,
        urgency=round(urgency, 2),
        urgency_label=get_urgency_label(urgency),
        confidence=round(confidence, 2),
        last_purchase_date=last_date_str,
        avg_days_between=round(avg_days, 1)
    )


def get_predictions_for_period(
    days_ahead: int = 14,
    category_filter: Optional[str] = None,
    min_confidence: float = 0.0,
    include_overdue: bool = True
) -> List[RepurchasePrediction]:
    """
    Get predictions for items that will need repurchase within a period.

    Args:
        days_ahead: Number of days to look ahead
        category_filter: Optional category filter ('routine', 'regular', 'treat')
        min_confidence: Minimum confidence threshold
        include_overdue: Whether to include overdue items

    Returns:
        List of RepurchasePrediction objects sorted by urgency
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get all products with statistics
        query = """
            SELECT ps.*, p.description, p.brand, p.category_type
            FROM product_statistics ps
            JOIN products p ON ps.product_id = p.product_id
            WHERE ps.total_purchases >= 2
        """
        params = []

        if category_filter:
            query += " AND p.category_type = ?"
            params.append(category_filter)

        cursor = conn.execute(query, params)
        products = [dict(row) for row in cursor.fetchall()]

        predictions = []
        for product in products:
            pred = predict_repurchase_date(product['product_id'], product)

            # Filter by confidence
            if pred.confidence < min_confidence:
                continue

            # Filter by date range
            if pred.days_until is None:
                continue

            if not include_overdue and pred.days_until < 0:
                continue

            if pred.days_until > days_ahead:
                continue

            predictions.append(pred)

        # Sort by urgency (highest first)
        predictions.sort(key=lambda p: p.urgency, reverse=True)

        return predictions
    finally:
        conn.close()


def get_overdue_items(
    category_filter: Optional[str] = None
) -> List[RepurchasePrediction]:
    """
    Get items that are overdue for repurchase.

    Args:
        category_filter: Optional category filter

    Returns:
        List of overdue items sorted by days overdue
    """
    predictions = get_predictions_for_period(
        days_ahead=0,
        category_filter=category_filter,
        include_overdue=True
    )

    return [p for p in predictions if p.days_until is not None and p.days_until < 0]


def get_shopping_suggestions(
    include_routine: bool = True,
    include_predicted: bool = True,
    include_seasonal: bool = True,
    days_ahead: int = 7,
    min_confidence: float = 0.5
) -> Dict[str, Any]:
    """
    Generate smart shopping suggestions.

    Args:
        include_routine: Include routine items due for repurchase
        include_predicted: Include predicted needs
        include_seasonal: Include upcoming seasonal items
        days_ahead: Days to look ahead
        min_confidence: Minimum prediction confidence

    Returns:
        Dict with categorized shopping suggestions
    """
    ensure_initialized()

    suggestions = {
        'overdue': [],
        'routine_items': [],
        'predicted_needs': [],
        'seasonal_items': [],
        'summary': {}
    }

    # Get overdue items (always include if any)
    overdue = get_overdue_items()
    suggestions['overdue'] = [
        {
            'product_id': p.product_id,
            'description': p.description,
            'category': p.category,
            'days_overdue': abs(p.days_until) if p.days_until else 0,
            'urgency': p.urgency,
            'urgency_label': p.urgency_label
        }
        for p in overdue
    ]

    if include_routine or include_predicted:
        predictions = get_predictions_for_period(
            days_ahead=days_ahead,
            min_confidence=min_confidence,
            include_overdue=False
        )

        for p in predictions:
            item = {
                'product_id': p.product_id,
                'description': p.description,
                'category': p.category,
                'predicted_date': p.predicted_date.isoformat() if p.predicted_date else None,
                'days_until': p.days_until,
                'urgency': p.urgency,
                'urgency_label': p.urgency_label,
                'confidence': p.confidence
            }

            if include_routine and p.category == 'routine':
                suggestions['routine_items'].append(item)
            elif include_predicted:
                suggestions['predicted_needs'].append(item)

    if include_seasonal:
        from .seasonal import get_upcoming_seasonal_items
        seasonal = get_upcoming_seasonal_items(days_ahead)
        suggestions['seasonal_items'] = seasonal

    # Summary
    total_items = (
        len(suggestions['overdue']) +
        len(suggestions['routine_items']) +
        len(suggestions['predicted_needs']) +
        len(suggestions['seasonal_items'])
    )

    high_urgency = (
        len([i for i in suggestions['overdue']]) +
        len([i for i in suggestions['routine_items']
             if i.get('urgency', 0) >= 0.7]) +
        len([i for i in suggestions['predicted_needs']
             if i.get('urgency', 0) >= 0.7])
    )

    suggestions['summary'] = {
        'total_items': total_items,
        'overdue_count': len(suggestions['overdue']),
        'high_urgency_count': high_urgency,
        'routine_count': len(suggestions['routine_items']),
        'predicted_count': len(suggestions['predicted_needs']),
        'seasonal_count': len(suggestions['seasonal_items'])
    }

    return suggestions
