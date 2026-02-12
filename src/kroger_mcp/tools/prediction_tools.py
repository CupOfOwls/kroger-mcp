"""
Prediction and analytics tools for the Kroger MCP server.

Provides MCP tools for:
- Purchase predictions and recommendations
- Item categorization
- Statistics and analytics
- Shopping suggestions
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

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
        product_id: str | List[str] = Field(
            description=(
                "Product ID or list of IDs (e.g., '001' or ['001', '002']). "
                "Max 20 products per batch request."
            )
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Get detailed purchase statistics for product(s). Supports batch operations.

        SINGLE MODE:
            get_item_statistics(product_id="0001111041700")

        BATCH MODE:
            get_item_statistics(product_id=["0001111041700", "0001111089476"])

        Returns comprehensive data including purchase frequency, average quantities,
        consumption rate, seasonality score, and detected category.

        Returns:
            Single mode: Statistics for one product
            Batch mode: {results: {product_id: statistics, ...}}
        """
        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 20:
            return {
                "success": False,
                "error": "Maximum 20 products per batch request"
            }

        try:
            from ..analytics.statistics import get_product_statistics
            from ..analytics.predictions import predict_repurchase_date
            from ..analytics.purchase_tracker import get_purchase_events

            def get_stats_for_product(pid: str) -> Dict[str, Any]:
                """Get statistics for a single product."""
                stats = get_product_statistics(pid)

                if not stats:
                    return {
                        "success": False,
                        "error": f"No statistics found for product {pid}"
                    }

                # Get prediction
                prediction = predict_repurchase_date(pid, stats)

                # Get recent purchase history
                events = get_purchase_events(pid, 'order_placed', limit=10)

                return {
                    "success": True,
                    "product_id": pid,
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
                        "next_purchase_date": (
                            prediction.predicted_date.isoformat()
                            if prediction.predicted_date else None
                        ),
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

            # Process all products
            results = {pid: get_stats_for_product(pid) for pid in ids}

            if is_batch:
                success_count = sum(1 for r in results.values() if r.get('success'))
                return {
                    "success": True,
                    "results": results,
                    "summary": {
                        "total": len(ids),
                        "successful": success_count,
                        "failed": len(ids) - success_count
                    }
                }
            else:
                # Single mode - return flat response
                return results[ids[0]]

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get statistics: {str(e)}"
            }

    @mcp.tool()
    async def categorize_item(
        product_id: str = Field(
            default=None,
            description="Single product ID to categorize"
        ),
        category: str = Field(
            default=None,
            description="Category: 'routine', 'regular', or 'treat'"
        ),
        items: Optional[List[Dict[str, Any]]] = Field(
            default=None,
            description="Batch mode: List of {product_id, category} dicts (max 50)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Set or override the category for product(s). Supports batch operations.

        SINGLE MODE:
            categorize_item(product_id="0001111041700", category="routine")

        BATCH MODE:
            categorize_item(items=[
                {"product_id": "001", "category": "routine"},
                {"product_id": "002", "category": "regular"}
            ])

        Categories:
        - routine: Items purchased almost constantly (every 1-14 days)
          Examples: milk, bread, eggs, bananas
        - regular: Items purchased frequently/occasionally (every 15-60 days)
          Examples: cleaning supplies, seasonings, pasta
        - treat: Items tied to holidays or special occasions
          Examples: turkey (Thanksgiving), candy (Halloween)

        Once manually set, the category won't be auto-changed.

        Args:
            product_id: Single product identifier (single mode)
            category: Category for single mode
            items: List of {product_id, category} for batch mode

        Returns:
            Single mode: Confirmation of the category change
            Batch mode: {results: {product_id: result, ...}, summary: {...}}
        """
        valid_categories = ['routine', 'regular', 'treat']

        # Determine mode and validate
        if items is not None:
            # Batch mode
            if len(items) > 50:
                return {
                    "success": False,
                    "error": "Maximum 50 products per batch request"
                }

            # Validate all items
            for item in items:
                if "product_id" not in item or "category" not in item:
                    return {
                        "success": False,
                        "error": "Each item must have 'product_id' and 'category' fields"
                    }
                if item["category"] not in valid_categories:
                    return {
                        "success": False,
                        "error": f"Invalid category '{item['category']}'. Must be one of: {valid_categories}"
                    }

            is_batch = True
        else:
            # Single mode
            if not product_id or not category:
                return {
                    "success": False,
                    "error": "Single mode requires both product_id and category parameters"
                }
            if category not in valid_categories:
                return {
                    "success": False,
                    "error": f"Invalid category. Must be one of: {valid_categories}"
                }

            items = [{"product_id": product_id, "category": category}]
            is_batch = False

        try:
            from ..analytics.categories import set_product_category

            results = {}
            for item in items:
                pid = item["product_id"]
                cat = item["category"]
                try:
                    result = set_product_category(pid, cat, is_override=True)
                    results[pid] = {
                        "success": True,
                        "product_id": pid,
                        "category": cat,
                        "previous_category": result.previous_category,
                        "was_auto_detected": not result.was_override,
                        "message": f"Category set to '{cat}' for product {pid}"
                    }
                except Exception as e:
                    results[pid] = {
                        "success": False,
                        "error": f"Failed to categorize {pid}: {str(e)}"
                    }

            if is_batch:
                success_count = sum(1 for r in results.values() if r.get('success'))
                return {
                    "success": True,
                    "results": results,
                    "summary": {
                        "total": len(items),
                        "successful": success_count,
                        "failed": len(items) - success_count
                    }
                }
            else:
                # Single mode - return flat response
                return results[items[0]["product_id"]]
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
        product_id: str | List[str] = Field(
            description=(
                "Product ID or list of IDs to update. "
                "Max 50 products per batch request."
            )
        ),
        level: int = Field(
            ge=0, le=100,
            description="New inventory level (0-100%, applied to all items in batch)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Manually set the inventory level for pantry item(s). Supports batch operations.

        SINGLE MODE:
            update_pantry_item(product_id="0001111041700", level=50)

        BATCH MODE:
            update_pantry_item(product_id=["001", "002", "003"], level=50)

        Use this to correct the estimate when it's off, e.g., "I'm actually
        almost out of milk" -> set to 10%.

        Args:
            product_id: Product ID or list of IDs to update
            level: New percentage level (0=out, 100=full)

        Returns:
            Single mode: Updated item info
            Batch mode: {results: {product_id: result, ...}, summary: {...}}
        """
        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 50:
            return {
                "success": False,
                "error": "Maximum 50 products per batch request"
            }

        try:
            from ..analytics.pantry import update_pantry_level

            results = {}
            for pid in ids:
                try:
                    result = update_pantry_level(pid, level)
                    results[pid] = result
                except Exception as e:
                    results[pid] = {
                        "success": False,
                        "error": f"Failed to update {pid}: {str(e)}"
                    }

            if is_batch:
                success_count = sum(1 for r in results.values() if r.get('success'))
                return {
                    "success": True,
                    "results": results,
                    "summary": {
                        "total": len(ids),
                        "successful": success_count,
                        "failed": len(ids) - success_count,
                        "level_set": level
                    }
                }
            else:
                # Single mode - return flat response
                return results[ids[0]]

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to update pantry: {str(e)}"
            }

    @mcp.tool()
    async def restock_pantry_item(
        product_id: str | List[str] = Field(
            description=(
                "Product ID or list of IDs to mark as restocked. "
                "Max 50 products per batch request."
            )
        ),
        level: int = Field(
            default=100, ge=0, le=100,
            description="Level to set (default 100%)"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Mark pantry item(s) as restocked. Supports batch operations.

        SINGLE MODE:
            restock_pantry_item(product_id="0001111041700", level=100)

        BATCH MODE:
            restock_pantry_item(product_id=["001", "002", "003"], level=100)

        This is automatically called when orders are placed, but can be
        used manually when you restock from another source.

        Args:
            product_id: Product ID or list of IDs to restock
            level: Level to set (default 100%)

        Returns:
            Single mode: Updated item info with new depletion rate
            Batch mode: {results: {product_id: result, ...}}
        """
        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 50:
            return {
                "success": False,
                "error": "Maximum 50 products per batch request"
            }

        try:
            from ..analytics.pantry import restock_item

            results = {}
            for pid in ids:
                try:
                    result = restock_item(pid, level)
                    results[pid] = result
                except Exception as e:
                    results[pid] = {
                        "success": False,
                        "error": f"Failed to restock {pid}: {str(e)}"
                    }

            if is_batch:
                success_count = sum(1 for r in results.values() if r.get('success'))
                return {
                    "success": True,
                    "results": results,
                    "summary": {
                        "total": len(ids),
                        "successful": success_count,
                        "failed": len(ids) - success_count,
                        "level_set": level
                    }
                }
            else:
                # Single mode - return flat response
                return results[ids[0]]

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
        product_id: str | List[str] = Field(
            description=(
                "Product ID or list of IDs to add to pantry tracking. "
                "Max 50 products per batch request."
            )
        ),
        description: Optional[str] = Field(
            default=None,
            description="Product description (applied to all items in batch, fetched automatically if not provided)"
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
        Add item(s) to pantry tracking. Supports batch operations.

        SINGLE MODE:
            add_to_pantry(product_id="0001111041700", level=100)

        BATCH MODE:
            add_to_pantry(product_id=["001", "002", "003"], level=100)

        The system will automatically estimate depletion based on your
        purchase history for this item.

        Args:
            product_id: Product ID or list of IDs to add
            description: Optional product description (applied to all)
            level: Initial level (default 100%)
            low_threshold: Warn when below this level (default 20%)

        Returns:
            Single mode: Confirmation with depletion rate info
            Batch mode: {results: {product_id: result, ...}, summary: {...}}
        """
        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 50:
            return {
                "success": False,
                "error": "Maximum 50 products per batch request"
            }

        try:
            from ..analytics.pantry import add_to_pantry

            results = {}
            for pid in ids:
                try:
                    result = add_to_pantry(
                        product_id=pid,
                        description=description,
                        level=level,
                        low_threshold=low_threshold,
                        auto_deplete=True
                    )
                    results[pid] = result
                except Exception as e:
                    results[pid] = {
                        "success": False,
                        "error": f"Failed to add {pid}: {str(e)}"
                    }

            if is_batch:
                success_count = sum(1 for r in results.values() if r.get('success'))
                return {
                    "success": True,
                    "results": results,
                    "summary": {
                        "total": len(ids),
                        "successful": success_count,
                        "failed": len(ids) - success_count,
                        "level": level,
                        "low_threshold": low_threshold
                    }
                }
            else:
                # Single mode - return flat response
                return results[ids[0]]

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add to pantry: {str(e)}"
            }

    @mcp.tool()
    async def remove_from_pantry(
        product_id: str | List[str] = Field(
            description=(
                "Product ID or list of IDs to remove from pantry tracking. "
                "Max 50 products per batch request."
            )
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Remove item(s) from pantry tracking. Supports batch operations.

        SINGLE MODE:
            remove_from_pantry(product_id="0001111041700")

        BATCH MODE:
            remove_from_pantry(product_id=["001", "002", "003"])

        Args:
            product_id: Product ID or list of IDs to stop tracking

        Returns:
            Single mode: Confirmation of removal
            Batch mode: {results: {product_id: result, ...}, summary: {...}}
        """
        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 50:
            return {
                "success": False,
                "error": "Maximum 50 products per batch request"
            }

        try:
            from ..analytics.pantry import remove_from_pantry

            results = {}
            for pid in ids:
                try:
                    result = remove_from_pantry(pid)
                    results[pid] = result
                except Exception as e:
                    results[pid] = {
                        "success": False,
                        "error": f"Failed to remove {pid}: {str(e)}"
                    }

            if is_batch:
                success_count = sum(1 for r in results.values() if r.get('success'))
                return {
                    "success": True,
                    "results": results,
                    "summary": {
                        "total": len(ids),
                        "successful": success_count,
                        "failed": len(ids) - success_count
                    }
                }
            else:
                # Single mode - return flat response
                return results[ids[0]]

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to remove from pantry: {str(e)}"
            }

    # ========== Configuration Tools ==========

    @mcp.tool()
    async def configure_predictions(
        ewma_alpha: Optional[float] = Field(
            default=None, ge=0.1, le=0.9,
            description="EWMA decay factor (0.1-0.9). Lower = more weight on recent"
        ),
        routine_buffer: Optional[float] = Field(
            default=None, ge=0.0, le=2.0,
            description="Safety buffer for routine items (std dev multiplier)"
        ),
        regular_buffer: Optional[float] = Field(
            default=None, ge=0.0, le=2.0,
            description="Safety buffer for regular items (std dev multiplier)"
        ),
        treat_buffer: Optional[float] = Field(
            default=None, ge=0.0, le=2.0,
            description="Safety buffer for treat items (std dev multiplier)"
        ),
        routine_max_days: Optional[int] = Field(
            default=None, ge=1, le=30,
            description="Max days between purchases for 'routine' category"
        ),
        regular_max_days: Optional[int] = Field(
            default=None, ge=15, le=120,
            description="Max days between purchases for 'regular' category"
        ),
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Configure prediction parameters and category thresholds.

        All parameters are optional - only specified values will be updated.
        Use this to tune predictions based on your preferences.

        Examples:
        - Set ewma_alpha=0.2 to give more weight to recent purchases
        - Set routine_buffer=1.5 for extra safety on essentials
        - Set routine_max_days=7 for stricter routine classification

        Args:
            ewma_alpha: EWMA decay factor (lower = more weight on recent)
            routine_buffer: Std dev multiplier for routine items
            regular_buffer: Std dev multiplier for regular items
            treat_buffer: Std dev multiplier for treat items
            routine_max_days: Category threshold for routine items
            regular_max_days: Category threshold for regular items

        Returns:
            Updated configuration
        """
        try:
            from ..analytics.config import update_config, get_config_summary

            # Build update kwargs from provided values
            kwargs = {}
            if ewma_alpha is not None:
                kwargs['ewma_alpha'] = ewma_alpha
            if routine_buffer is not None:
                kwargs['buffer_routine'] = routine_buffer
            if regular_buffer is not None:
                kwargs['buffer_regular'] = regular_buffer
            if treat_buffer is not None:
                kwargs['buffer_treat'] = treat_buffer
            if routine_max_days is not None:
                kwargs['routine_max_days'] = routine_max_days
            if regular_max_days is not None:
                kwargs['regular_max_days'] = regular_max_days

            if kwargs:
                result = update_config(**kwargs)
            else:
                result = {'success': True, 'message': 'No changes specified'}

            # Always return current config summary
            result['current_config'] = get_config_summary()
            return result

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to configure predictions: {str(e)}"
            }

    @mcp.tool()
    async def get_prediction_config(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        View current prediction configuration settings.

        Returns all configurable parameters with their current values
        and descriptions.

        Returns:
            Current configuration summary
        """
        try:
            from ..analytics.config import get_config_summary

            return {
                "success": True,
                "config": get_config_summary()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get config: {str(e)}"
            }

    @mcp.tool()
    async def reset_prediction_config(
        ctx: Context = None
    ) -> Dict[str, Any]:
        """
        Reset prediction configuration to defaults.

        This will reset all prediction parameters to their default values.

        Returns:
            Default configuration
        """
        try:
            from ..analytics.config import reset_config, get_config_summary

            reset_config()
            return {
                "success": True,
                "message": "Configuration reset to defaults",
                "config": get_config_summary()
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to reset config: {str(e)}"
            }
