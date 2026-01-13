"""
Analytics reporting and data export.

Generates reports for spending, predictions, shopping patterns, and pantry status.
"""

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .database import get_db_connection, ensure_initialized


def generate_spending_report(
    days_back: int = 30,
    group_by: str = 'category'
) -> Dict[str, Any]:
    """
    Generate spending/purchase analytics report.

    Args:
        days_back: Number of days to analyze
        group_by: Grouping method ('category', 'week', 'product')

    Returns:
        Dict with spending breakdown and trends
    """
    ensure_initialized()

    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    conn = get_db_connection()
    try:
        # Get all orders in the period
        cursor = conn.execute("""
            SELECT pe.*, p.description, p.category_type
            FROM purchase_events pe
            LEFT JOIN products p ON pe.product_id = p.product_id
            WHERE pe.event_type = 'order_placed'
              AND pe.event_date >= ?
            ORDER BY pe.event_date
        """, (start_date,))
        events = [dict(row) for row in cursor.fetchall()]

        if not events:
            return {
                'period': f'Last {days_back} days',
                'total_items': 0,
                'message': 'No purchase data for this period'
            }

        # Basic stats
        total_items = len(events)
        total_quantity = sum(e.get('quantity', 1) for e in events)
        unique_products = len(set(e['product_id'] for e in events))

        # Group by category
        by_category = {}
        for e in events:
            cat = e.get('category_type') or 'uncategorized'
            if cat not in by_category:
                by_category[cat] = {'count': 0, 'quantity': 0, 'products': set()}
            by_category[cat]['count'] += 1
            by_category[cat]['quantity'] += e.get('quantity', 1)
            by_category[cat]['products'].add(e['product_id'])

        category_breakdown = [
            {
                'category': cat,
                'item_count': data['count'],
                'total_quantity': data['quantity'],
                'unique_products': len(data['products']),
                'percentage': round(data['count'] / total_items * 100, 1)
            }
            for cat, data in by_category.items()
        ]
        category_breakdown.sort(key=lambda x: x['item_count'], reverse=True)

        # Most frequent products
        product_counts = {}
        for e in events:
            pid = e['product_id']
            if pid not in product_counts:
                product_counts[pid] = {
                    'description': e.get('description'),
                    'count': 0,
                    'quantity': 0
                }
            product_counts[pid]['count'] += 1
            product_counts[pid]['quantity'] += e.get('quantity', 1)

        top_products = sorted(
            [
                {'product_id': pid, **data}
                for pid, data in product_counts.items()
            ],
            key=lambda x: x['count'],
            reverse=True
        )[:10]

        return {
            'period': f'Last {days_back} days',
            'start_date': start_date,
            'total_items': total_items,
            'total_quantity': total_quantity,
            'unique_products': unique_products,
            'by_category': category_breakdown,
            'top_products': top_products,
            'avg_items_per_day': round(total_items / days_back, 2)
        }
    finally:
        conn.close()


def generate_prediction_accuracy_report() -> Dict[str, Any]:
    """
    Analyze how accurate purchase predictions have been.

    Compares predicted dates to actual purchase dates.

    Returns:
        Dict with prediction accuracy metrics
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        # Get products with enough data
        cursor = conn.execute("""
            SELECT ps.*, p.description
            FROM product_statistics ps
            JOIN products p ON ps.product_id = p.product_id
            WHERE ps.total_purchases >= 3
        """)
        products = [dict(row) for row in cursor.fetchall()]

        if not products:
            return {
                'message': 'Not enough purchase history for accuracy analysis',
                'min_purchases_required': 3
            }

        # Analyze prediction accuracy
        accurate = []
        inaccurate = []
        unknown = []

        for p in products:
            accuracy = p.get('prediction_accuracy')
            trend = p.get('trend_direction', 'stable')
            confidence = 0

            # Calculate implied accuracy from std_dev / avg_days
            avg_days = p.get('avg_days_between_purchases')
            std_dev = p.get('std_dev_days', 0)

            if avg_days and avg_days > 0:
                consistency = 1 - min(1.0, std_dev / avg_days)
                if consistency >= 0.7:
                    accurate.append({
                        'product_id': p['product_id'],
                        'description': p.get('description'),
                        'consistency': round(consistency, 2),
                        'avg_days': round(avg_days, 1),
                        'std_dev': round(std_dev, 1),
                        'trend': trend
                    })
                elif consistency >= 0.4:
                    inaccurate.append({
                        'product_id': p['product_id'],
                        'description': p.get('description'),
                        'consistency': round(consistency, 2),
                        'avg_days': round(avg_days, 1),
                        'std_dev': round(std_dev, 1),
                        'trend': trend
                    })
                else:
                    unknown.append({
                        'product_id': p['product_id'],
                        'description': p.get('description'),
                        'consistency': round(consistency, 2),
                        'reason': 'High variability in purchase pattern'
                    })
            else:
                unknown.append({
                    'product_id': p['product_id'],
                    'description': p.get('description'),
                    'reason': 'Insufficient interval data'
                })

        total = len(accurate) + len(inaccurate) + len(unknown)

        return {
            'total_products_analyzed': total,
            'high_accuracy': {
                'count': len(accurate),
                'percentage': round(len(accurate) / total * 100, 1) if total > 0 else 0,
                'products': accurate[:10]  # Top 10
            },
            'moderate_accuracy': {
                'count': len(inaccurate),
                'percentage': round(len(inaccurate) / total * 100, 1) if total > 0 else 0,
                'products': inaccurate[:10]
            },
            'unpredictable': {
                'count': len(unknown),
                'percentage': round(len(unknown) / total * 100, 1) if total > 0 else 0,
                'products': unknown[:10]
            }
        }
    finally:
        conn.close()


def generate_patterns_report(days_back: int = 90) -> Dict[str, Any]:
    """
    Generate shopping behavior patterns report.

    Args:
        days_back: Number of days to analyze

    Returns:
        Dict with shopping patterns and insights
    """
    ensure_initialized()

    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y-%m-%d')

    conn = get_db_connection()
    try:
        # Get orders with dates
        cursor = conn.execute("""
            SELECT * FROM orders
            WHERE placed_at >= ?
            ORDER BY placed_at
        """, (start_date,))
        orders = [dict(row) for row in cursor.fetchall()]

        if not orders:
            return {
                'period': f'Last {days_back} days',
                'message': 'No orders in this period'
            }

        # Analyze by day of week
        day_counts = {i: 0 for i in range(7)}
        for order in orders:
            try:
                order_date = datetime.fromisoformat(order['placed_at'])
                day_counts[order_date.weekday()] += 1
            except (ValueError, TypeError):
                pass

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday',
                     'Friday', 'Saturday', 'Sunday']
        by_day = [
            {'day': day_names[i], 'orders': day_counts[i]}
            for i in range(7)
        ]

        # Find preferred day
        max_day = max(day_counts.items(), key=lambda x: x[1])
        preferred_day = day_names[max_day[0]] if max_day[1] > 0 else None

        # Modality analysis
        cursor = conn.execute("""
            SELECT modality, COUNT(*) as count
            FROM purchase_events
            WHERE event_type = 'order_placed'
              AND event_date >= ?
            GROUP BY modality
        """, (start_date,))
        modality_counts = {row['modality']: row['count'] for row in cursor.fetchall()}

        # Order frequency
        total_orders = len(orders)
        avg_days_between = days_back / total_orders if total_orders > 0 else None

        return {
            'period': f'Last {days_back} days',
            'total_orders': total_orders,
            'avg_days_between_orders': round(avg_days_between, 1) if avg_days_between else None,
            'by_day_of_week': by_day,
            'preferred_shopping_day': preferred_day,
            'by_modality': modality_counts,
            'preferred_modality': max(modality_counts.items(), key=lambda x: x[1])[0] if modality_counts else None
        }
    finally:
        conn.close()


def generate_pantry_report() -> Dict[str, Any]:
    """
    Generate pantry inventory status report.

    Returns:
        Dict with pantry status and recommendations
    """
    ensure_initialized()

    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT pi.*, p.category_type
            FROM pantry_items pi
            LEFT JOIN products p ON pi.product_id = p.product_id
            ORDER BY pi.level_percent ASC
        """)
        items = [dict(row) for row in cursor.fetchall()]

        if not items:
            return {
                'message': 'No items being tracked in pantry',
                'total_items': 0
            }

        # Categorize by level
        critical = [i for i in items if i['level_percent'] <= 10]
        low = [i for i in items if 10 < i['level_percent'] <= 30]
        moderate = [i for i in items if 30 < i['level_percent'] <= 60]
        good = [i for i in items if i['level_percent'] > 60]

        # Calculate days until shopping needed
        items_running_out = []
        for item in items:
            rate = item.get('daily_depletion_rate', 0)
            level = item.get('level_percent', 100)
            if rate > 0:
                days = level / rate
                items_running_out.append({
                    'product_id': item['product_id'],
                    'description': item.get('description'),
                    'level': level,
                    'days_until_empty': round(days, 1),
                    'category': item.get('category_type')
                })

        items_running_out.sort(key=lambda x: x['days_until_empty'])

        return {
            'total_items': len(items),
            'status_breakdown': {
                'critical': len(critical),
                'low': len(low),
                'moderate': len(moderate),
                'good': len(good)
            },
            'critical_items': [
                {'product_id': i['product_id'], 'description': i.get('description'),
                 'level': i['level_percent']}
                for i in critical
            ],
            'low_items': [
                {'product_id': i['product_id'], 'description': i.get('description'),
                 'level': i['level_percent']}
                for i in low
            ],
            'running_out_soon': items_running_out[:10],
            'needs_shopping': len(critical) + len(low) > 0
        }
    finally:
        conn.close()


def export_all_data(
    include_orders: bool = True,
    include_products: bool = True,
    include_pantry: bool = True,
    include_recipes: bool = True
) -> Dict[str, Any]:
    """
    Export all analytics data for backup or external analysis.

    Args:
        include_orders: Include order history
        include_products: Include product catalog and stats
        include_pantry: Include pantry inventory
        include_recipes: Include saved recipes

    Returns:
        Dict with all requested data
    """
    ensure_initialized()

    export = {
        'export_date': datetime.now().isoformat(),
        'version': '1.0'
    }

    conn = get_db_connection()
    try:
        if include_orders:
            cursor = conn.execute("SELECT * FROM orders ORDER BY placed_at DESC")
            orders = [dict(row) for row in cursor.fetchall()]

            cursor = conn.execute("""
                SELECT * FROM purchase_events
                ORDER BY event_date DESC
            """)
            events = [dict(row) for row in cursor.fetchall()]

            export['orders'] = {
                'count': len(orders),
                'data': orders
            }
            export['purchase_events'] = {
                'count': len(events),
                'data': events
            }

        if include_products:
            cursor = conn.execute("SELECT * FROM products")
            products = [dict(row) for row in cursor.fetchall()]

            cursor = conn.execute("SELECT * FROM product_statistics")
            stats = [dict(row) for row in cursor.fetchall()]

            export['products'] = {
                'count': len(products),
                'data': products
            }
            export['product_statistics'] = {
                'count': len(stats),
                'data': stats
            }

        if include_pantry:
            cursor = conn.execute("SELECT * FROM pantry_items")
            pantry = [dict(row) for row in cursor.fetchall()]

            export['pantry'] = {
                'count': len(pantry),
                'data': pantry
            }

        if include_recipes:
            cursor = conn.execute("SELECT * FROM recipes")
            recipes = [dict(row) for row in cursor.fetchall()]

            cursor = conn.execute("SELECT * FROM recipe_ingredients")
            ingredients = [dict(row) for row in cursor.fetchall()]

            export['recipes'] = {
                'count': len(recipes),
                'data': recipes
            }
            export['recipe_ingredients'] = {
                'count': len(ingredients),
                'data': ingredients
            }

        return export
    finally:
        conn.close()
