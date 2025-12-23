"""
Seasonal and holiday pattern detection.

Identifies items that are purchased primarily around specific holidays
or times of year. Calculates shopping lead times so users are reminded
to buy holiday items 1-3 days BEFORE the actual holiday.
"""

import statistics as stats
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized

# Built-in holiday patterns with shopping lead times
HOLIDAY_PATTERNS = {
    'thanksgiving': {
        'months': [10, 11],
        'peak_weeks': [45, 46, 47],
        'keywords': ['turkey', 'stuffing', 'cranberry', 'pie', 'gravy'],
        'days_before': 2  # Shop 2 days before Thanksgiving
    },
    'christmas': {
        'months': [11, 12],
        'peak_weeks': [49, 50, 51, 52],
        'keywords': ['ham', 'eggnog', 'candy cane', 'gingerbread', 'fruitcake'],
        'days_before': 3  # Shop 3 days before (avoid Christmas Eve rush)
    },
    'halloween': {
        'months': [9, 10],
        'peak_weeks': [40, 41, 42, 43, 44],
        'keywords': ['candy', 'pumpkin', 'chocolate'],
        'days_before': 2  # Shop 2 days before Halloween
    },
    'easter': {
        'months': [3, 4],
        'peak_weeks': [12, 13, 14, 15, 16],
        'keywords': ['ham', 'egg', 'chocolate', 'lamb'],
        'days_before': 2  # Shop 2 days before Easter
    },
    'july_4th': {
        'months': [6, 7],
        'peak_weeks': [26, 27],
        'keywords': ['hotdog', 'hamburger', 'bun', 'chips', 'watermelon'],
        'days_before': 2  # Shop 2 days before July 4th
    }
}


def _calculate_easter(year: int) -> date:
    """
    Calculate Easter Sunday using the Anonymous Gregorian algorithm.

    This is a well-known algorithm for computing Easter dates.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month = (h + el - 7 * m + 114) // 31
    day = ((h + el - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def get_holiday_date(holiday: str, year: int) -> Optional[date]:
    """
    Calculate the actual date of a holiday for a given year.

    Args:
        holiday: Holiday name (thanksgiving, christmas, etc.)
        year: The year to calculate for

    Returns:
        The date of the holiday, or None if unknown
    """
    if holiday == 'thanksgiving':
        # 4th Thursday of November
        nov_1 = date(year, 11, 1)
        # Find first Thursday (weekday 3)
        days_until_thursday = (3 - nov_1.weekday()) % 7
        first_thursday = nov_1 + timedelta(days=days_until_thursday)
        # 4th Thursday is 3 weeks after the first
        return first_thursday + timedelta(weeks=3)
    elif holiday == 'christmas':
        return date(year, 12, 25)
    elif holiday == 'halloween':
        return date(year, 10, 31)
    elif holiday == 'easter':
        return _calculate_easter(year)
    elif holiday == 'july_4th':
        return date(year, 7, 4)
    return None


def get_upcoming_holidays(days_ahead: int = 30) -> List[Dict[str, Any]]:
    """
    Get upcoming holidays with their shopping dates.

    Args:
        days_ahead: Number of days to look ahead

    Returns:
        List of upcoming holidays with dates and shopping info
    """
    today = date.today()
    upcoming = []

    for holiday, patterns in HOLIDAY_PATTERNS.items():
        days_before = patterns.get('days_before', 2)

        # Check current year and next year
        for year in [today.year, today.year + 1]:
            holiday_date = get_holiday_date(holiday, year)
            if holiday_date is None:
                continue

            shop_by_date = holiday_date - timedelta(days=days_before)
            days_until_shopping = (shop_by_date - today).days

            # Include if shopping date is within our window
            if 0 <= days_until_shopping <= days_ahead:
                # Determine urgency
                if days_until_shopping <= 0:
                    urgency = 'critical'
                elif days_until_shopping <= 2:
                    urgency = 'high'
                elif days_until_shopping <= 5:
                    urgency = 'medium'
                else:
                    urgency = 'low'

                upcoming.append({
                    'holiday': holiday,
                    'holiday_date': holiday_date.isoformat(),
                    'shop_by_date': shop_by_date.isoformat(),
                    'days_until_shopping': days_until_shopping,
                    'days_until_holiday': (holiday_date - today).days,
                    'urgency': urgency,
                    'keywords': patterns['keywords']
                })

    # Sort by days until shopping (most urgent first)
    return sorted(upcoming, key=lambda x: x['days_until_shopping'])


def calculate_seasonality_score(
    purchase_events: List[Dict[str, Any]]
) -> float:
    """
    Calculate how seasonal a product is.

    Uses coefficient of variation of monthly purchase counts.
    Score of 0 = not seasonal, 1 = very seasonal.

    Args:
        purchase_events: List of purchase events

    Returns:
        Seasonality score between 0 and 1
    """
    if len(purchase_events) < 4:
        return 0.0

    # Count purchases by month
    monthly_counts: Dict[int, int] = defaultdict(int)
    for event in purchase_events:
        date_str = event.get('event_date', '')
        if date_str:
            try:
                if 'T' in date_str:
                    date = datetime.fromisoformat(
                        date_str.replace('Z', '+00:00'))
                else:
                    date = datetime.strptime(date_str, '%Y-%m-%d')
                monthly_counts[date.month] += 1
            except (ValueError, TypeError):
                continue

    # Fill in zeros for months with no purchases
    counts = [monthly_counts.get(m, 0) for m in range(1, 13)]

    # Calculate coefficient of variation
    mean_count = stats.mean(counts)
    if mean_count == 0:
        return 0.0

    std_dev = stats.stdev(counts) if len(counts) > 1 else 0.0
    cv = std_dev / mean_count

    # Normalize to 0-1 range (CV of 2+ is considered very seasonal)
    return min(1.0, cv / 2.0)


def detect_holiday_association(
    product_id: str,
    description: Optional[str] = None
) -> Optional[str]:
    """
    Detect if a product is associated with a specific holiday.

    Args:
        product_id: The product identifier
        description: Product description for keyword matching

    Returns:
        Holiday name or None
    """
    ensure_initialized()

    # Get purchase events for this product
    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT event_date FROM purchase_events
            WHERE product_id = ? AND event_type = 'order_placed'
        """, (product_id,))
        events = [dict(row) for row in cursor.fetchall()]

        # Check description for holiday keywords
        if description:
            desc_lower = description.lower()
            for holiday, patterns in HOLIDAY_PATTERNS.items():
                if any(kw in desc_lower for kw in patterns['keywords']):
                    return holiday

        # Check purchase patterns
        if len(events) < 2:
            return None

        # Count purchases by month
        monthly_counts: Dict[int, int] = defaultdict(int)
        for event in events:
            date_str = event.get('event_date', '')
            if date_str:
                try:
                    date = datetime.strptime(date_str[:10], '%Y-%m-%d')
                    monthly_counts[date.month] += 1
                except (ValueError, TypeError):
                    continue

        total = sum(monthly_counts.values())
        if total == 0:
            return None

        # Check if 80%+ purchases are in holiday months
        for holiday, patterns in HOLIDAY_PATTERNS.items():
            holiday_count = sum(
                monthly_counts.get(m, 0) for m in patterns['months']
            )
            if holiday_count / total >= 0.8:
                return holiday

        return None
    finally:
        conn.close()


def update_seasonal_patterns(product_id: str) -> Dict[str, Any]:
    """
    Update seasonal pattern data for a product.

    Args:
        product_id: The product identifier

    Returns:
        Summary of seasonal patterns
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get purchase events
        cursor = conn.execute("""
            SELECT event_date, quantity FROM purchase_events
            WHERE product_id = ? AND event_type = 'order_placed'
        """, (product_id,))
        events = [dict(row) for row in cursor.fetchall()]

        if not events:
            return {'product_id': product_id, 'patterns': []}

        # Aggregate by month
        monthly_data: Dict[int, Dict] = defaultdict(
            lambda: {'count': 0, 'quantity': 0}
        )

        for event in events:
            date_str = event.get('event_date', '')
            if date_str:
                try:
                    date = datetime.strptime(date_str[:10], '%Y-%m-%d')
                    monthly_data[date.month]['count'] += 1
                    monthly_data[date.month]['quantity'] += event.get(
                        'quantity', 1)
                except (ValueError, TypeError):
                    continue

        # Find peak periods
        counts = [monthly_data[m]['count'] for m in range(1, 13)]
        if counts:
            mean_count = stats.mean(counts)
            std_count = stats.stdev(counts) if len(counts) > 1 else 0

        # Get product description for keyword matching
        desc_cursor = conn.execute(
            "SELECT description FROM products WHERE product_id = ?",
            (product_id,)
        )
        desc_row = desc_cursor.fetchone()
        description = desc_row['description'] if desc_row else None

        # Detect holiday association
        holiday = detect_holiday_association(product_id, description)

        # Update seasonal patterns table
        patterns = []
        for month in range(1, 13):
            data = monthly_data[month]
            is_peak = data['count'] > (mean_count + std_count) if counts else False
            avg_qty = (data['quantity'] / data['count']
                       if data['count'] > 0 else 0)

            # Upsert pattern
            conn.execute("""
                INSERT INTO seasonal_patterns
                (product_id, month, purchase_count, avg_quantity, is_peak_period,
                 holiday_association)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id, month) DO UPDATE SET
                    purchase_count = excluded.purchase_count,
                    avg_quantity = excluded.avg_quantity,
                    is_peak_period = excluded.is_peak_period,
                    holiday_association = excluded.holiday_association
            """, (
                product_id,
                month,
                data['count'],
                avg_qty,
                1 if is_peak else 0,
                holiday if is_peak else None
            ))

            patterns.append({
                'month': month,
                'count': data['count'],
                'avg_quantity': avg_qty,
                'is_peak': is_peak
            })

        conn.commit()

        return {
            'product_id': product_id,
            'holiday_association': holiday,
            'patterns': patterns
        }
    finally:
        conn.close()


def get_upcoming_seasonal_items(
    days_ahead: int = 30
) -> List[Dict[str, Any]]:
    """
    Get items associated with upcoming holidays/seasons.

    Returns items with shopping dates calculated so users are reminded
    to purchase 1-3 days BEFORE the actual holiday.

    Args:
        days_ahead: Number of days to look ahead

    Returns:
        List of seasonal items with holiday dates and shopping urgency
    """
    ensure_initialized()

    # Get upcoming holidays with their shopping dates
    upcoming_holidays = get_upcoming_holidays(days_ahead + 7)

    # Build a map of holiday -> shopping info
    holiday_info = {}
    for h in upcoming_holidays:
        holiday_info[h['holiday']] = h

    # Get months in range for database query
    now = datetime.now()
    end_date = now + timedelta(days=days_ahead)
    target_months = set()
    current = now
    while current <= end_date:
        target_months.add(current.month)
        current += timedelta(days=1)

    conn = get_db_connection()
    try:
        # Find products with peak periods in target months
        placeholders = ','.join('?' * len(target_months))
        cursor = conn.execute(f"""
            SELECT DISTINCT sp.product_id, sp.holiday_association,
                   sp.month, sp.avg_quantity,
                   p.description, p.brand
            FROM seasonal_patterns sp
            JOIN products p ON sp.product_id = p.product_id
            WHERE sp.is_peak_period = 1
              AND sp.month IN ({placeholders})
            ORDER BY sp.month, p.description
        """, list(target_months))

        items = []
        for row in cursor.fetchall():
            holiday = row['holiday_association']
            item = {
                'product_id': row['product_id'],
                'description': row['description'],
                'brand': row['brand'],
                'holiday': holiday,
                'peak_month': row['month'],
                'typical_quantity': row['avg_quantity']
            }

            # Add shopping date info if this is an upcoming holiday
            if holiday and holiday in holiday_info:
                info = holiday_info[holiday]
                item['holiday_date'] = info['holiday_date']
                item['shop_by_date'] = info['shop_by_date']
                item['days_until_shopping'] = info['days_until_shopping']
                item['days_until_holiday'] = info['days_until_holiday']
                item['urgency'] = info['urgency']
            else:
                # No specific holiday, use month-based estimate
                item['holiday_date'] = None
                item['shop_by_date'] = None
                item['days_until_shopping'] = None
                item['urgency'] = 'low'

            items.append(item)

        # Sort by urgency (most urgent first)
        urgency_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        items.sort(key=lambda x: (
            urgency_order.get(x.get('urgency', 'low'), 4),
            x.get('days_until_shopping') or 999
        ))

        return items
    finally:
        conn.close()


def get_holiday_items(holiday: str) -> List[Dict[str, Any]]:
    """
    Get all items associated with a specific holiday.

    Args:
        holiday: Holiday name (thanksgiving, christmas, etc.)

    Returns:
        List of products associated with the holiday
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT DISTINCT sp.product_id, sp.avg_quantity,
                   p.description, p.brand
            FROM seasonal_patterns sp
            JOIN products p ON sp.product_id = p.product_id
            WHERE sp.holiday_association = ?
            ORDER BY p.description
        """, (holiday,))

        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
