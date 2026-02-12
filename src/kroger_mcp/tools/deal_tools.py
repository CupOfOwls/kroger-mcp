"""
Deal discovery and price tracking tools for Kroger MCP server.
"""

from typing import Dict, Any, Optional, Literal, List
from pydantic import Field
from fastmcp import Context
from datetime import datetime, timedelta

from .shared import get_client_credentials_client, get_preferred_location_id
# Note: search_products and get_product_details are MCP tools and can't be imported
# We'll use the API client directly for deal searches
from ..analytics.deals import (
    get_price_statistics,
    score_deal_quality,
)
from ..analytics.database import get_db_cursor, get_db_connection
from ..analytics.favorites import get_all_favorite_product_ids
from ..analytics.pantry import get_low_inventory_items
from ..analytics.statistics import get_recent_purchases


# Category search mappings
CATEGORY_SEARCHES = {
    "dairy": ["milk", "cheese", "yogurt", "butter"],
    "meat": ["chicken", "beef", "pork", "turkey"],
    "produce": ["fruits", "vegetables", "salad"],
    "bakery": ["bread", "bagels", "rolls"],
    "frozen": ["frozen meals", "ice cream", "pizza"],
    "beverages": ["soda", "juice", "coffee", "tea"],
}


def register_tools(mcp):
    """Register deal-related tools with the FastMCP server"""

    @mcp.tool()
    async def find_deals(
        search_term: Optional[str] = Field(
            default=None,
            description="Search term (e.g., 'milk', 'bread'). If not provided, searches popular categories.",
        ),
        category: Optional[str] = Field(
            default=None,
            description="Category to search: 'dairy', 'meat', 'produce', 'bakery', 'frozen', 'beverages'",
        ),
        min_savings_percent: float = Field(
            default=10.0, description="Minimum discount percentage (default 10%)"
        ),
        sort_by: Literal["savings_percent", "savings_amount", "price"] = Field(
            default="savings_percent", description="Sort results by savings or price"
        ),
        limit: int = Field(default=20, description="Maximum number of deals to return"),
        location_id: Optional[str] = Field(
            default=None, description="Store location ID (uses preferred if not specified)"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Search for products currently on sale with significant discounts.

        This tool actively searches for deals by:
        1. Searching relevant products (by term or category)
        2. Filtering to only items on sale (promo price < regular price)
        3. Filtering by minimum savings percentage
        4. Sorting by best deals first
        5. Cross-referencing with your favorites and pantry

        Category Mappings:
        - 'dairy' → searches: milk, cheese, yogurt, butter
        - 'meat' → searches: chicken, beef, pork, turkey
        - 'produce' → searches: fruits, vegetables, salad
        - 'bakery' → searches: bread, bagels, rolls
        - 'frozen' → searches: frozen meals, ice cream, pizza
        - 'beverages' → searches: soda, juice, coffee, tea

        If no search_term or category provided, searches top 3 categories.

        Returns:
            List of deals with savings info, sorted by best deals first
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set. "
                    "Use set_preferred_location first.",
                }

        # Determine search queries
        search_queries = []
        if search_term:
            search_queries = [search_term]
        elif category and category.lower() in CATEGORY_SEARCHES:
            search_queries = CATEGORY_SEARCHES[category.lower()]
        else:
            # Default: search top 3 categories
            search_queries = ["milk", "bread", "chicken"]

        if ctx:
            await ctx.info(
                f"Searching for deals: {', '.join(search_queries)} (min {min_savings_percent}% off)"
            )

        # Get favorite IDs for cross-reference
        favorite_ids = set()
        try:
            favorite_ids = get_all_favorite_product_ids()
        except Exception:
            pass

        # Get pantry items for cross-reference
        pantry_items = {}
        try:
            low_items = get_low_inventory_items(threshold=50)
            pantry_items = {item["product_id"]: item for item in low_items}
        except Exception:
            pass

        # Search for products and collect deals
        all_deals = []
        categories_scanned = set()

        for query in search_queries:
            try:
                # Search products using API client directly
                client = get_client_credentials_client()
                search_response = client.search_products(
                    term=query,
                    location_id=location_id,
                    limit=50,
                )

                if not search_response or "data" not in search_response:
                    continue

                products = search_response.get("data", [])

                # Filter to deals only
                for product in products:
                    pricing = product.get("pricing", {})
                    if not pricing.get("on_sale"):
                        continue

                    # Calculate savings percent
                    regular = pricing.get("regular_price", 0)
                    sale = pricing.get("sale_price", 0)
                    if not regular or not sale or sale >= regular:
                        continue

                    savings_amount = regular - sale
                    savings_percent = (savings_amount / regular) * 100

                    if savings_percent < min_savings_percent:
                        continue

                    # Add to deals list
                    deal = {
                        "product_id": product.get("product_id"),
                        "description": product.get("description"),
                        "brand": product.get("brand"),
                        "regular_price": regular,
                        "sale_price": sale,
                        "savings_amount": round(savings_amount, 2),
                        "savings_percent": round(savings_percent, 1),
                        "is_favorite": product.get("product_id") in favorite_ids,
                        "is_in_pantry": product.get("product_id") in pantry_items,
                        "pantry_level": pantry_items.get(product.get("product_id"), {}).get(
                            "level_percent", 100
                        ),
                    }

                    # Get price history if available
                    try:
                        price_stats = get_price_statistics(
                            product.get("product_id"), days=30, location_id=location_id
                        )
                        if price_stats.get("has_data"):
                            deal["price_trend"] = price_stats.get("recommendation")
                            deal["recommendation"] = price_stats.get("recommendation_text")
                    except Exception:
                        pass

                    # Score deal quality
                    try:
                        quality = score_deal_quality(
                            {"pricing": pricing, **deal},
                            price_stats if "price_stats" in locals() else None,
                        )
                        deal["quality_score"] = quality["quality_score"]
                        deal["quality_label"] = quality["quality_label"]
                        deal["urgency"] = quality["urgency"]
                    except Exception:
                        pass

                    all_deals.append(deal)

                # Track categories scanned
                if product.get("categories"):
                    categories_scanned.update(product["categories"])

            except Exception as e:
                if ctx:
                    await ctx.warn(f"Error searching '{query}': {str(e)}")
                continue

        # Remove duplicates by product_id
        seen_ids = set()
        unique_deals = []
        for deal in all_deals:
            if deal["product_id"] not in seen_ids:
                seen_ids.add(deal["product_id"])
                unique_deals.append(deal)

        # Sort deals
        if sort_by == "savings_percent":
            unique_deals.sort(key=lambda x: x["savings_percent"], reverse=True)
        elif sort_by == "savings_amount":
            unique_deals.sort(key=lambda x: x["savings_amount"], reverse=True)
        elif sort_by == "price":
            unique_deals.sort(key=lambda x: x["sale_price"])

        # Limit results
        unique_deals = unique_deals[:limit]

        # Calculate summary
        total_savings = sum(d["savings_amount"] for d in unique_deals)
        avg_savings_percent = (
            sum(d["savings_percent"] for d in unique_deals) / len(unique_deals)
            if unique_deals
            else 0
        )

        return {
            "success": True,
            "deals": unique_deals,
            "summary": {
                "total_deals_found": len(unique_deals),
                "total_savings_available": round(total_savings, 2),
                "avg_savings_percent": round(avg_savings_percent, 1),
                "categories_scanned": list(categories_scanned)[:10],
                "search_queries": search_queries,
            },
        }

    @mcp.tool()
    async def add_to_watchlist(
        product_id: str | List[str] = Field(
            description=(
                "Product ID or list of IDs to watch for price drops. "
                "Max 30 products per batch request."
            )
        ),
        description: Optional[str] = Field(
            default=None, description="Product description (applied to all items in batch, fetched automatically if not provided)"
        ),
        target_price: Optional[float] = Field(
            default=None, description="Alert when price reaches this target (applied to all items in batch)"
        ),
        priority: int = Field(
            default=1,
            description="Priority: 1=low, 2=medium, 3=high (affects scan frequency, applied to all items)",
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Add product(s) to watchlist for price monitoring. Supports batch operations.

        SINGLE MODE:
            add_to_watchlist(product_id="0001111041700", priority=2)

        BATCH MODE:
            add_to_watchlist(product_id=["001", "002", "003"], priority=2)

        The system will periodically check these products' prices and alert
        you when they go on sale or reach your target price.

        Priority levels:
        - 1 (low): Checked weekly
        - 2 (medium): Checked every 2-3 days
        - 3 (high): Checked daily

        Returns:
            Single mode: Confirmation with current price and watchlist status
            Batch mode: {results: {product_id: result, ...}, summary: {...}}
        """
        # Normalize to list
        ids = [product_id] if isinstance(product_id, str) else product_id
        is_batch = len(ids) > 1

        if len(ids) > 30:
            return {
                "success": False,
                "error": "Maximum 30 products per batch request"
            }

        # Get location for price lookups
        location_id = get_preferred_location_id()

        priority_labels = {1: "low", 2: "medium", 3: "high"}

        try:
            results = {}
            for pid in ids:
                try:
                    current_price = None
                    current_on_sale = False
                    prod_description = description

                    # Get current price if location available
                    if location_id:
                        try:
                            client = get_client_credentials_client()
                            product_response = client.get_product(
                                product_id=pid, location_id=location_id
                            )
                            if product_response and "data" in product_response:
                                product_data = product_response.get("data", {})
                                pricing = product_data.get("pricing", {})
                                current_price = pricing.get("sale_price") or pricing.get("regular_price")
                                current_on_sale = pricing.get("on_sale", False)
                                if not prod_description:
                                    prod_description = product_data.get("description")
                        except Exception:
                            pass

                    # Add to watchlist
                    with get_db_cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO deal_watchlist
                            (product_id, description, target_price, priority, best_price_seen, best_price_date)
                            VALUES (?, ?, ?, ?, ?, ?)
                            ON CONFLICT(product_id) DO UPDATE SET
                                description = excluded.description,
                                target_price = excluded.target_price,
                                priority = excluded.priority
                            """,
                            (
                                pid,
                                prod_description,
                                target_price,
                                priority,
                                current_price,
                                datetime.now().isoformat() if current_price else None,
                            ),
                        )

                    results[pid] = {
                        "success": True,
                        "product_id": pid,
                        "description": prod_description,
                        "current_price": current_price,
                        "current_on_sale": current_on_sale,
                        "target_price": target_price,
                        "priority": priority_labels.get(priority, "unknown"),
                        "message": f"Added to watchlist with {priority_labels.get(priority, 'unknown')} priority",
                    }
                except Exception as e:
                    results[pid] = {
                        "success": False,
                        "error": f"Failed to add {pid} to watchlist: {str(e)}"
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
                        "priority": priority_labels.get(priority, "unknown")
                    }
                }
            else:
                # Single mode - return flat response
                return results[ids[0]]

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to add to watchlist: {str(e)}"
            }

    @mcp.tool()
    async def get_price_history(
        product_id: str = Field(description="Product ID to get price history for"),
        days: int = Field(default=30, description="Number of days of history to retrieve"),
        location_id: Optional[str] = Field(
            default=None, description="Store location (uses preferred if not specified)"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Get price history and trend analysis for a product.

        Returns:
            - Price timeline (daily observations)
            - Current price vs 30-day average
            - Lowest and highest prices seen
            - Sale frequency
            - Best time to buy recommendation
        """
        if not location_id:
            location_id = get_preferred_location_id()

        # Get price statistics
        stats = get_price_statistics(product_id, days=days, location_id=location_id)

        if not stats.get("has_data"):
            return {
                "success": False,
                "product_id": product_id,
                "error": "No price history available for this product",
            }

        # Get price timeline
        conn = get_db_connection()
        try:
            since_date = (datetime.now() - timedelta(days=days)).isoformat()
            location_filter = "AND location_id = ?" if location_id else ""
            params = [product_id, since_date]
            if location_id:
                params.append(location_id)

            cursor = conn.execute(
                f"""
                SELECT
                    DATE(observed_at) as date,
                    AVG(COALESCE(sale_price, regular_price)) as avg_price,
                    MAX(on_sale) as on_sale,
                    MAX(savings_percent) as max_savings
                FROM price_history
                WHERE product_id = ?
                AND observed_at > ?
                {location_filter}
                GROUP BY DATE(observed_at)
                ORDER BY date DESC
                """,
                params,
            )

            timeline = [
                {
                    "date": row["date"],
                    "price": round(row["avg_price"], 2),
                    "on_sale": bool(row["on_sale"]),
                    "savings_percent": round(row["max_savings"], 1) if row["max_savings"] else 0,
                }
                for row in cursor.fetchall()
            ]

        finally:
            conn.close()

        # Get product description
        description = None
        try:
            if location_id:
                client = get_client_credentials_client()
                product_response = client.get_product(
                    product_id=product_id, location_id=location_id
                )
                if product_response and "data" in product_response:
                    description = product_response.get("data", {}).get("description")
        except Exception:
            pass

        return {
            "success": True,
            "product_id": product_id,
            "description": description,
            "current_price": stats["current_price"],
            "current_on_sale": stats["current_on_sale"],
            "statistics": {
                "avg_price_30d": stats["avg_price_30d"],
                "lowest_price_30d": stats["lowest_price_30d"],
                "highest_price_30d": stats["highest_price_30d"],
                "times_on_sale": stats["times_on_sale"],
                "avg_savings_when_on_sale": stats["avg_savings_when_on_sale"],
                "current_vs_avg": f"{((stats['current_price'] - stats['avg_price_30d']) / stats['avg_price_30d'] * 100):+.1f}%",
                "trend": stats["trend"],
                "recommendation": stats["recommendation_text"],
            },
            "price_timeline": timeline[:30],  # Limit to 30 days
            "observations_count": stats["observations_count"],
        }

    @mcp.tool()
    async def scan_watchlist_for_deals(
        include_favorites: bool = Field(
            default=True, description="Include favorite list items in scan"
        ),
        include_pantry: bool = Field(
            default=True, description="Include pantry items in scan"
        ),
        include_recent_purchases: bool = Field(
            default=True, description="Include recently purchased items in scan"
        ),
        max_items: int = Field(
            default=50,
            description="Maximum items to scan (API limit consideration)",
        ),
        location_id: Optional[str] = Field(
            default=None, description="Store location (uses preferred if not specified)"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Scan your tracked items (favorites, pantry, recent purchases) for current deals.

        This creates a smart watchlist from:
        1. Explicit watchlist (added via add_to_watchlist)
        2. Favorite list items
        3. Low pantry items (<=25% quantity)
        4. Recent purchases (last 30 days)

        Then checks current prices for all these items and returns those
        currently on sale.

        API Cost: Makes product detail calls for each item (respects max_items limit)

        Returns:
            Deals on items you actually care about
        """
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set.",
                }

        if ctx:
            await ctx.info(f"Building watchlist from your tracked items...")

        # Build watchlist from multiple sources
        watchlist = []

        # 1. Explicit watchlist
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                """
                SELECT product_id, description, target_price, priority
                FROM deal_watchlist
                ORDER BY priority DESC, last_checked_at ASC
                """
            )
            for row in cursor.fetchall():
                watchlist.append(
                    {
                        "product_id": row["product_id"],
                        "description": row["description"],
                        "target_price": row["target_price"],
                        "source": "watchlist",
                        "priority": row["priority"],
                    }
                )
        finally:
            conn.close()

        # 2. Favorites
        if include_favorites:
            try:
                favorite_ids = get_all_favorite_product_ids()
                for product_id in favorite_ids:
                    if not any(w["product_id"] == product_id for w in watchlist):
                        watchlist.append(
                            {
                                "product_id": product_id,
                                "source": "favorites",
                                "priority": 2,
                            }
                        )
            except Exception:
                pass

        # 3. Low pantry items
        if include_pantry:
            try:
                low_items = get_low_inventory_items(threshold=25)
                for item in low_items:
                    product_id = item["product_id"]
                    if not any(w["product_id"] == product_id for w in watchlist):
                        watchlist.append(
                            {
                                "product_id": product_id,
                                "description": item.get("description"),
                                "source": "pantry",
                                "priority": 3,  # High priority for low pantry
                            }
                        )
            except Exception:
                pass

        # 4. Recent purchases
        if include_recent_purchases:
            try:
                recent = get_recent_purchases(days=30, limit=20)
                for purchase in recent:
                    product_id = purchase["product_id"]
                    if not any(w["product_id"] == product_id for w in watchlist):
                        watchlist.append(
                            {
                                "product_id": product_id,
                                "description": purchase.get("description"),
                                "source": "recent_purchase",
                                "priority": 1,
                            }
                        )
            except Exception:
                pass

        # Sort by priority and limit
        watchlist.sort(key=lambda x: x.get("priority", 0), reverse=True)
        watchlist = watchlist[:max_items]

        if ctx:
            await ctx.info(
                f"Scanning {len(watchlist)} items for deals (from {', '.join(set(w['source'] for w in watchlist))})..."
            )

        # Check prices for each item
        deals = []
        for item in watchlist:
            try:
                client = get_client_credentials_client()
                product_response = client.get_product(
                    product_id=item["product_id"], location_id=location_id
                )

                if not product_response or "data" not in product_response:
                    continue

                data = product_response.get("data", {})
                pricing = data.get("pricing", {})

                if not pricing.get("on_sale"):
                    continue

                # Check if target price met
                target_met = False
                if item.get("target_price"):
                    current_price = pricing.get("sale_price") or pricing.get("regular_price")
                    target_met = current_price <= item["target_price"]

                deal = {
                    "product_id": item["product_id"],
                    "description": data.get("description") or item.get("description"),
                    "brand": data.get("brand"),
                    "regular_price": pricing.get("regular_price"),
                    "sale_price": pricing.get("sale_price"),
                    "savings_amount": (
                        pricing.get("regular_price") - pricing.get("sale_price")
                        if pricing.get("regular_price") and pricing.get("sale_price")
                        else 0
                    ),
                    "savings_percent": round(
                        (
                            (pricing.get("regular_price") - pricing.get("sale_price"))
                            / pricing.get("regular_price")
                            * 100
                        )
                        if pricing.get("regular_price") and pricing.get("sale_price")
                        else 0,
                        1,
                    ),
                    "source": item["source"],
                    "target_price": item.get("target_price"),
                    "target_met": target_met,
                }

                deals.append(deal)

            except Exception as e:
                if ctx:
                    await ctx.warn(f"Error checking {item['product_id']}: {str(e)}")
                continue

        # Sort by savings percent
        deals.sort(key=lambda x: x["savings_percent"], reverse=True)

        total_savings = sum(d["savings_amount"] for d in deals)

        return {
            "success": True,
            "deals": deals,
            "summary": {
                "items_scanned": len(watchlist),
                "deals_found": len(deals),
                "total_savings_available": round(total_savings, 2),
                "sources": list(set(w["source"] for w in watchlist)),
            },
        }

    @mcp.tool()
    async def get_latest_deal_scan(
        mark_as_viewed: bool = Field(
            default=False,
            description="Mark scan results as viewed"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Get results from latest background deal scan.

        Shows deals found during Mon/Thu automated scans.
        Ready for your weekend shopping!

        Background scans run automatically via launchd on:
        - Monday at 9:00 AM
        - Thursday at 9:00 AM

        Returns:
            Latest scan results with deals, timing, and summary
        """
        conn = get_db_connection()
        try:
            # Get latest scan date
            cursor = conn.execute(
                """
                SELECT scan_date, scan_time, COUNT(*) as deal_count
                FROM deal_scan_results
                GROUP BY scan_date
                ORDER BY scan_date DESC
                LIMIT 1
                """
            )
            latest = cursor.fetchone()

            if not latest:
                return {
                    "success": True,
                    "message": "No scans found yet. First scan runs Monday 9 AM.",
                    "deals": [],
                    "summary": {
                        "scan_date": None,
                        "deal_count": 0,
                        "total_savings_available": 0,
                        "unviewed_deals": 0,
                    },
                }

            # Get deals from latest scan
            cursor = conn.execute(
                """
                SELECT product_id, description, regular_price, sale_price,
                       savings_amount, viewed
                FROM deal_scan_results
                WHERE scan_date = ?
                ORDER BY savings_amount DESC
                """,
                (latest["scan_date"],),
            )

            deals = [dict(row) for row in cursor.fetchall()]

            # Mark as viewed if requested
            if mark_as_viewed:
                conn.execute(
                    """
                    UPDATE deal_scan_results
                    SET viewed = 1
                    WHERE scan_date = ?
                    """,
                    (latest["scan_date"],),
                )
                conn.commit()

            return {
                "success": True,
                "scan_date": latest["scan_date"],
                "scan_time": latest["scan_time"],
                "deal_count": latest["deal_count"],
                "deals": deals,
                "summary": {
                    "total_savings_available": round(sum(d["savings_amount"] for d in deals), 2),
                    "unviewed_deals": sum(1 for d in deals if not d["viewed"]),
                    "message": f"Scanned on {latest['scan_date']}, found {latest['deal_count']} deals",
                },
            }

        finally:
            conn.close()
