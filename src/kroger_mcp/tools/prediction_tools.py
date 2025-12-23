"""
Prediction and analytics tools for the Kroger MCP server.

Provides MCP tools for:
- Purchase predictions and recommendations
- Item categorization
- Statistics and analytics
- Shopping suggestions
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastmcp import Context
from pydantic import Field


def register_tools(mcp):
    """Register prediction and analytics tools with the FastMCP server."""

    @mcp.tool()
    async def get_purchase_predictions(
        days_ahead: int = Field(
            default=14, ge=1, le=90,
            description="Number of days to look ahead for predictions"
        ),
        category: Optional[str] = Field(
            default=None,
            description="Filter by category: 'routine', 'regular', or 'treat'"
        ),
        min_confidence: float = Field(
            default=0.5, ge=0.0, le=1.0,
            description="Minimum prediction confidence (0-1)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get predictions for items that will need to be repurchased soon.

        Returns a list of items sorted by urgency, with predicted repurchase dates,
        confidence levels, and urgency scores (both numeric 0-1 and labels).

        Use this to help users stay ahead of their grocery needs and never run
        out of essential items.

        Args:
            days_ahead: How many days ahead to predict (1-90)
            category: Filter by 'routine', 'regular', or 'treat'
            min_confidence: Minimum prediction confidence threshold

        Returns:
            List of predictions with urgency and confidence scores
        """
        try:
            from ..analytics.predictions import get_predictions_for_period

            predictions = get_predictions_for_period(
                days_ahead=days_ahead,
                category_filter=category,
                min_confidence=min_confidence,
                include_overdue=True
            )

            return {
                "success": True,
                "predictions": [
                    {
                        "product_id": p.product_id,
                        "description": p.description,
                        "category": p.category,
                        "predicted_date": (p.predicted_date.isoformat()
                                           if p.predicted_date else None),
                        "days_until": p.days_until,
                        "urgency": p.urgency,
                        "urgency_label": p.urgency_label,
                        "confidence": p.confidence,
                        "last_purchased": p.last_purchase_date,
                        "avg_days_between": p.avg_days_between
                    }
                    for p in predictions
                ],
                "count": len(predictions),
                "urgent_count": sum(1 for p in predictions if p.urgency >= 0.7),
                "overdue_count": sum(
                    1 for p in predictions
                    if p.days_until is not None and p.days_until < 0
                ),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get predictions: {str(e)}"
            }

    @mcp.tool()
    async def get_item_statistics(
        product_id: str = Field(
            description="The product ID to get statistics for"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get detailed purchase statistics for a specific product.

        Returns comprehensive data including purchase frequency, average quantities,
        consumption rate, seasonality score, and detected category.

        Args:
            product_id: The product identifier

        Returns:
            Detailed statistics for the product
        """
        try:
            from ..analytics.statistics import get_product_statistics
            from ..analytics.predictions import predict_repurchase_date
            from ..analytics.purchase_tracker import get_purchase_events

            stats = get_product_statistics(product_id)

            if not stats:
                return {
                    "success": False,
                    "error": f"No statistics found for product {product_id}"
                }

            # Get prediction
            prediction = predict_repurchase_date(product_id, stats)

            # Get recent purchase history
            events = get_purchase_events(product_id, 'order_placed', limit=10)

            return {
                "success": True,
                "product_id": product_id,
                "description": stats.get('description'),
                "brand": stats.get('brand'),
                "category": stats.get('category_type'),
                "is_manual_category": bool(stats.get('category_override')),
                "statistics": {
                    "total_purchases": stats.get('total_purchases'),
                    "total_quantity": stats.get('total_quantity'),
                    "avg_quantity_per_purchase": round(
                        stats.get('avg_quantity_per_purchase') or 0, 2),
                    "avg_days_between_purchases": round(
                        stats.get('avg_days_between_purchases') or 0, 1),
                    "std_dev_days": round(stats.get('std_dev_days') or 0, 1),
                    "first_purchase": stats.get('first_purchase_date'),
                    "last_purchase": stats.get('last_purchase_date'),
                    "purchase_frequency_score": round(
                        stats.get('purchase_frequency_score') or 0, 3),
                    "seasonality_score": round(
                        stats.get('seasonality_score') or 0, 2)
                },
                "prediction": {
                    "next_purchase_date": (prediction.predicted_date.isoformat()
                                           if prediction.predicted_date else None),
                    "days_until": prediction.days_until,
                    "urgency": prediction.urgency,
                    "urgency_label": prediction.urgency_label,
                    "confidence": prediction.confidence
                },
                "recent_purchases": [
                    {
                        "date": e.get('event_date'),
                        "quantity": e.get('quantity'),
                        "modality": e.get('modality')
                    }
                    for e in events
                ]
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get statistics: {str(e)}"
            }

    @mcp.tool()
    async def categorize_item(
        product_id: str = Field(
            description="The product ID to categorize"
        ),
        category: str = Field(
            description="Category: 'routine', 'regular', or 'treat'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Set or override the category for a product.

        Categories:
        - routine: Items purchased almost constantly (every 1-14 days)
          Examples: milk, bread, eggs, bananas
        - regular: Items purchased frequently/occasionally (every 15-60 days)
          Examples: cleaning supplies, seasonings, pasta
        - treat: Items tied to holidays or special occasions
          Examples: turkey (Thanksgiving), candy (Halloween)

        Once manually set, the category won't be auto-changed.

        Args:
            product_id: The product identifier
            category: One of 'routine', 'regular', or 'treat'

        Returns:
            Confirmation of the category change
        """
        valid_categories = ['routine', 'regular', 'treat']
        if category not in valid_categories:
            return {
                "success": False,
                "error": f"Invalid category. Must be one of: {valid_categories}"
            }

        try:
            from ..analytics.categories import set_product_category

            result = set_product_category(product_id, category, is_override=True)

            return {
                "success": True,
                "product_id": product_id,
                "category": category,
                "previous_category": result.previous_category,
                "was_auto_detected": not result.was_override,
                "message": f"Category set to '{category}' for product {product_id}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to set category: {str(e)}"
            }

    @mcp.tool()
    async def get_items_by_category(
        category: str = Field(
            description="Category to filter: 'routine', 'regular', 'treat', or 'uncategorized'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get all items in a specific category.

        Args:
            category: The category to filter by

        Returns:
            List of items in the specified category with their statistics
        """
        valid_categories = ['routine', 'regular', 'treat', 'uncategorized']
        if category not in valid_categories:
            return {
                "success": False,
                "error": f"Invalid category. Must be one of: {valid_categories}"
            }

        try:
            from ..analytics.categories import get_items_by_category

            items = get_items_by_category(category, include_stats=True)

            return {
                "success": True,
                "category": category,
                "items": [
                    {
                        "product_id": item.get('product_id'),
                        "description": item.get('description'),
                        "brand": item.get('brand'),
                        "total_purchases": item.get('total_purchases'),
                        "avg_days_between": round(
                            item.get('avg_days_between_purchases') or 0, 1),
                        "last_purchase": item.get('last_purchase_date'),
                        "seasonality_score": round(
                            item.get('seasonality_score') or 0, 2)
                    }
                    for item in items
                ],
                "count": len(items)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get items: {str(e)}"
            }

    @mcp.tool()
    async def get_purchase_history(
        product_id: str = Field(
            description="The product ID to get history for"
        ),
        limit: int = Field(
            default=20, ge=1, le=100,
            description="Maximum number of events to return"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get purchase history for a specific product.

        Returns a chronological list of when this item was purchased,
        including quantities and modalities.

        Args:
            product_id: The product identifier
            limit: Maximum number of events (1-100)

        Returns:
            List of purchase events for the product
        """
        try:
            from ..analytics.purchase_tracker import get_purchase_events

            events = get_purchase_events(
                product_id,
                event_type='order_placed',
                limit=limit
            )

            return {
                "success": True,
                "product_id": product_id,
                "events": [
                    {
                        "date": e.get('event_date'),
                        "timestamp": e.get('event_timestamp'),
                        "quantity": e.get('quantity'),
                        "modality": e.get('modality'),
                        "order_id": e.get('order_id')
                    }
                    for e in events
                ],
                "count": len(events)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get history: {str(e)}"
            }

    @mcp.tool()
    async def get_shopping_suggestions(
        include_routine: bool = Field(
            default=True,
            description="Include routine items due for repurchase"
        ),
        include_predicted: bool = Field(
            default=True,
            description="Include items predicted to run out soon"
        ),
        include_seasonal: bool = Field(
            default=True,
            description="Include upcoming seasonal/holiday items"
        ),
        days_ahead: int = Field(
            default=7, ge=1, le=30,
            description="Days to look ahead for predictions"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Generate a smart shopping list based on purchase patterns and predictions.

        This combines overdue items, routine needs, predicted requirements,
        and upcoming seasonal items into one organized list.

        Use this to help users create comprehensive shopping lists without
        forgetting important items.

        Args:
            include_routine: Include routine items needing repurchase
            include_predicted: Include predicted needs
            include_seasonal: Include seasonal/holiday items
            days_ahead: Number of days to look ahead

        Returns:
            Categorized shopping suggestions with urgency levels
        """
        try:
            from ..analytics.predictions import get_shopping_suggestions

            suggestions = get_shopping_suggestions(
                include_routine=include_routine,
                include_predicted=include_predicted,
                include_seasonal=include_seasonal,
                days_ahead=days_ahead,
                min_confidence=0.5
            )

            return {
                "success": True,
                **suggestions,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get suggestions: {str(e)}"
            }

    @mcp.tool()
    async def get_seasonal_items(
        days_ahead: int = Field(
            default=30, ge=1, le=90,
            description="Days ahead to look for seasonal items"
        ),
        holiday: Optional[str] = Field(
            default=None,
            description="Filter by holiday: thanksgiving, christmas, halloween, easter, july_4th"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get items associated with upcoming holidays or seasons.

        Identifies items that you typically buy around specific holidays
        based on your purchase history.

        Args:
            days_ahead: Number of days to look ahead (1-90)
            holiday: Optional filter for specific holiday

        Returns:
            List of seasonal items with their holiday associations
        """
        try:
            if holiday:
                from ..analytics.seasonal import get_holiday_items
                items = get_holiday_items(holiday)
                return {
                    "success": True,
                    "holiday": holiday,
                    "items": items,
                    "count": len(items)
                }
            else:
                from ..analytics.seasonal import get_upcoming_seasonal_items
                items = get_upcoming_seasonal_items(days_ahead)
                return {
                    "success": True,
                    "days_ahead": days_ahead,
                    "items": items,
                    "count": len(items)
                }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get seasonal items: {str(e)}"
            }

    @mcp.tool()
    async def migrate_purchase_data(
        force: bool = Field(
            default=False,
            description="Force migration even if already done (use with caution)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Migrate existing purchase data from JSON files to the analytics database.

        This is typically run automatically on first use, but can be triggered
        manually if needed. The migration imports:
        - Order history from kroger_order_history.json
        - Current cart from kroger_cart.json

        Args:
            force: If True, re-run migration (may duplicate data)

        Returns:
            Summary of migrated data
        """
        try:
            from ..analytics.migration import (
                migrate_json_to_sqlite,
                force_remigration,
                get_migration_status
            )

            if force:
                result = force_remigration()
            else:
                result = migrate_json_to_sqlite()

            status = get_migration_status()

            return {
                "success": result.get('success', False),
                "migration_result": result,
                "current_status": status
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Migration failed: {str(e)}"
            }

    @mcp.tool()
    async def get_category_summary(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get a summary of items by category.

        Returns counts of items in each category (routine, regular, treat)
        to help understand your purchase patterns.

        Returns:
            Category counts and totals
        """
        try:
            from ..analytics.categories import get_category_summary

            summary = get_category_summary()

            total = sum(summary.values())

            return {
                "success": True,
                "categories": summary,
                "total_products": total,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get summary: {str(e)}"
            }

    # ========== Pantry Inventory Tools ==========

    @mcp.tool()
    async def get_pantry(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        View all pantry items with current estimated inventory levels.

        Levels are automatically estimated based on consumption rate since
        last restock. Items are sorted by level (lowest first).

        Returns:
            List of pantry items with status (ok/low/out), level percentage,
            and days until empty
        """
        try:
            from ..analytics.pantry import get_pantry_status

            items = get_pantry_status(apply_depletion=True)

            return {
                "success": True,
                "items": items,
                "count": len(items),
                "low_count": sum(1 for i in items if i['status'] == 'low'),
                "out_count": sum(1 for i in items if i['status'] == 'out'),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get pantry: {str(e)}"
            }

    @mcp.tool()
    async def update_pantry_item(
        product_id: str = Field(
            description="Product ID of the pantry item"
        ),
        level: int = Field(
            ge=0, le=100,
            description="New inventory level (0-100%)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Manually set the inventory level for a pantry item.

        Use this to correct the estimate when it's off, e.g., "I'm actually
        almost out of milk" -> set to 10%.

        Args:
            product_id: The product to update
            level: New percentage level (0=out, 100=full)

        Returns:
            Updated item info
        """
        try:
            from ..analytics.pantry import update_pantry_level

            result = update_pantry_level(product_id, level)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to update pantry: {str(e)}"
            }

    @mcp.tool()
    async def restock_pantry_item(
        product_id: str = Field(
            description="Product ID to mark as restocked"
        ),
        level: int = Field(
            default=100, ge=0, le=100,
            description="Level to set (default 100%)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Mark a pantry item as restocked (typically to 100%).

        This is automatically called when orders are placed, but can be
        used manually when you restock from another source.

        Args:
            product_id: The product to restock
            level: Level to set (default 100%)

        Returns:
            Updated item info with new depletion rate
        """
        try:
            from ..analytics.pantry import restock_item

            result = restock_item(product_id, level)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to restock: {str(e)}"
            }

    @mcp.tool()
    async def get_low_inventory(
        threshold: int = Field(
            default=20, ge=0, le=100,
            description="Threshold percentage to consider 'low'"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get pantry items that are running low.

        Returns items below the specified threshold (default 20%).

        Args:
            threshold: Consider items below this level as low

        Returns:
            List of low inventory items sorted by level
        """
        try:
            from ..analytics.pantry import get_low_inventory_items

            items = get_low_inventory_items(threshold)

            return {
                "success": True,
                "threshold": threshold,
                "items": items,
                "count": len(items),
                "out_count": sum(1 for i in items if i['level_percent'] <= 0)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get low inventory: {str(e)}"
            }

    @mcp.tool()
    async def add_to_pantry(
        product_id: str = Field(
            description="Product ID to add to pantry tracking"
        ),
        description: Optional[str] = Field(
            default=None,
            description="Product description (fetched automatically if not provided)"
        ),
        level: int = Field(
            default=100, ge=0, le=100,
            description="Initial inventory level (default 100%)"
        ),
        low_threshold: int = Field(
            default=20, ge=0, le=100,
            description="Alert when level drops below this (default 20%)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Add an item to pantry tracking.

        The system will automatically estimate depletion based on your
        purchase history for this item.

        Args:
            product_id: The product to track
            description: Optional product description
            level: Initial level (default 100%)
            low_threshold: Warn when below this level (default 20%)

        Returns:
            Confirmation with depletion rate info
        """
        try:
            from ..analytics.pantry import add_to_pantry

            result = add_to_pantry(
                product_id=product_id,
                description=description,
                level=level,
                low_threshold=low_threshold,
                auto_deplete=True
            )
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add to pantry: {str(e)}"
            }

    @mcp.tool()
    async def remove_from_pantry(
        product_id: str = Field(
            description="Product ID to remove from pantry tracking"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Remove an item from pantry tracking.

        Args:
            product_id: The product to stop tracking

        Returns:
            Confirmation of removal
        """
        try:
            from ..analytics.pantry import remove_from_pantry

            result = remove_from_pantry(product_id)
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to remove from pantry: {str(e)}"
            }
