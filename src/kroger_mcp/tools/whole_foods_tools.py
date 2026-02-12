"""
Whole foods catalog management tools for Kroger MCP server.

Tracks and identifies whole/natural foods using existing safety filter.
"""

from typing import Dict, Any, Optional, List
from pydantic import Field
from fastmcp import Context
from datetime import datetime

from .shared import get_client_credentials_client, get_preferred_location_id
from .product_tools import search_products, get_product_details
from ..analytics.database import get_db_cursor, get_db_connection
from ..analytics.ingredients import check_product_safety
from ..analytics.safety import get_disabled_ingredients


def is_whole_food_eligible(
    description: str,
    brand: Optional[str] = None,
    disabled_ingredients: Optional[set] = None
) -> Dict[str, Any]:
    """
    Check if product qualifies as whole food.

    Uses existing safety filter - product must:
    1. Pass safety check (no CRITICAL/WARNING ingredients)
    2. Have UNKNOWN or SAFE status
    3. Optional: Low WATCH ingredient count (<3)

    Returns:
        {
            "eligible": bool,
            "safety_status": str,
            "reason": str,
            "matches": list
        }
    """
    safety_result = check_product_safety(
        description=description,
        brand=brand,
        disabled_ingredients=disabled_ingredients
    )

    # Disqualify if critical or warning ingredients found
    if safety_result.highest_severity in ["critical", "warning"]:
        return {
            "eligible": False,
            "safety_status": safety_result.highest_severity.upper(),
            "reason": f"Contains {safety_result.highest_severity} ingredients",
            "matches": [
                {"ingredient": m.ingredient_name, "severity": m.severity}
                for m in safety_result.matches
            ]
        }

    # Accept SAFE (no concerns) or UNKNOWN (clean)
    if not safety_result.has_concerns:
        return {
            "eligible": True,
            "safety_status": "SAFE",
            "reason": "No concerning ingredients detected",
            "matches": []
        }

    # For WATCH status, check count
    watch_count = len([m for m in safety_result.matches if m.severity == "watch"])
    if watch_count <= 2:
        return {
            "eligible": True,
            "safety_status": "WATCH",
            "reason": f"Minimal processing markers ({watch_count} watch-level ingredients)",
            "matches": [
                {"ingredient": m.ingredient_name, "severity": m.severity}
                for m in safety_result.matches
            ]
        }

    return {
        "eligible": False,
        "safety_status": "WATCH",
        "reason": f"Too many processing markers ({watch_count} watch-level ingredients)",
        "matches": [
            {"ingredient": m.ingredient_name, "severity": m.severity}
            for m in safety_result.matches
        ]
    }


def register_tools(mcp):
    """Register whole foods tools with the FastMCP server"""

    @mcp.tool()
    async def add_to_whole_foods_catalog(
        product_id: str = Field(
            description="Product ID to add to whole foods catalog"
        ),
        description: Optional[str] = Field(
            default=None,
            description="Product description (optional)"
        ),
        verify_safety: bool = Field(
            default=True,
            description="Verify product passes safety checks before adding"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Add product to whole foods catalog.

        Optionally verifies product passes safety checks before adding.
        Uses existing 75+ ingredient safety filter to identify clean foods.

        Returns:
            Confirmation with safety status
        """
        # Get product details if description not provided
        if not description:
            location_id = get_preferred_location_id()
            if location_id:
                try:
                    product = await get_product_details(
                        product_id=product_id,
                        location_id=location_id,
                        ctx=ctx
                    )
                    if product.get("success"):
                        description = product.get("data", {}).get("description")
                except Exception:
                    pass

        # Verify safety if requested
        safety_status = "UNKNOWN"
        eligibility_result = None

        if verify_safety and description:
            disabled = get_disabled_ingredients()
            eligibility_result = is_whole_food_eligible(
                description=description,
                disabled_ingredients=disabled
            )

            if not eligibility_result["eligible"]:
                return {
                    "success": False,
                    "product_id": product_id,
                    "description": description,
                    "error": eligibility_result["reason"],
                    "safety_status": eligibility_result["safety_status"],
                    "matches": eligibility_result["matches"],
                }

            safety_status = eligibility_result["safety_status"]

        # Add to catalog
        with get_db_cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO whole_foods_catalog
                (product_id, description, added_by, safety_status, last_verified_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                    description = excluded.description,
                    safety_status = excluded.safety_status,
                    last_verified_at = excluded.last_verified_at
                """,
                (
                    product_id,
                    description,
                    "manual",
                    safety_status,
                    datetime.now().isoformat(),
                ),
            )

        return {
            "success": True,
            "product_id": product_id,
            "description": description,
            "safety_status": safety_status,
            "message": "Added to whole foods catalog",
            "eligibility": eligibility_result if eligibility_result else None,
        }

    @mcp.tool()
    async def get_whole_foods_catalog(
        include_unavailable: bool = Field(
            default=False,
            description="Include products marked as unavailable"
        ),
        limit: int = Field(
            default=100,
            description="Maximum number of products to return"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Get all products in whole foods catalog.

        Returns catalog with basic info. Use get_product_details for
        current prices and availability.

        Returns:
            List of whole foods with safety status
        """
        conn = get_db_connection()
        try:
            availability_filter = "" if include_unavailable else "WHERE is_currently_available = 1"

            cursor = conn.execute(
                f"""
                SELECT
                    product_id,
                    description,
                    brand,
                    added_at,
                    added_by,
                    safety_status,
                    processing_level,
                    notes,
                    last_verified_at,
                    is_currently_available
                FROM whole_foods_catalog
                {availability_filter}
                ORDER BY added_at DESC
                LIMIT ?
                """,
                (limit,),
            )

            products = [dict(row) for row in cursor.fetchall()]

            return {
                "success": True,
                "products": products,
                "total": len(products),
                "include_unavailable": include_unavailable,
            }

        finally:
            conn.close()

    @mcp.tool()
    async def scan_for_whole_foods(
        category: str = Field(
            description="Category to search: 'produce', 'dairy', 'meat', 'bakery', 'frozen'"
        ),
        location_id: Optional[str] = Field(
            default=None,
            description="Store location (uses preferred if not specified)"
        ),
        auto_add: bool = Field(
            default=False,
            description="Automatically add qualifying products to catalog"
        ),
        limit: int = Field(
            default=20,
            description="Maximum products to scan"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Search for products that qualify as whole foods.

        Searches by category, checks against safety filter,
        optionally auto-adds qualifying products to catalog.

        Returns:
            List of qualifying whole foods with safety analysis
        """
        # Use preferred location if none provided
        if not location_id:
            location_id = get_preferred_location_id()
            if not location_id:
                return {
                    "success": False,
                    "error": "No location_id provided and no preferred location set.",
                }

        # Category search terms
        category_searches = {
            "produce": "vegetables",
            "dairy": "milk",
            "meat": "chicken breast",
            "bakery": "bread",
            "frozen": "frozen vegetables",
        }

        search_term = category_searches.get(category.lower(), category)

        if ctx:
            await ctx.info(f"Scanning for whole foods in category: {category}")

        # Search for products
        search_result = await search_products(
            search_term=search_term,
            location_id=location_id,
            limit=limit,
            ctx=ctx,
        )

        if not search_result.get("success"):
            return {
                "success": False,
                "error": "Search failed",
                "details": search_result,
            }

        products = search_result.get("data", [])
        disabled = get_disabled_ingredients()

        # Check each product
        qualifying_products = []
        rejected_products = []

        for product in products:
            description = product.get("description")
            brand = product.get("brand")
            product_id = product.get("product_id")

            if not description:
                continue

            # Check eligibility
            eligibility = is_whole_food_eligible(
                description=description,
                brand=brand,
                disabled_ingredients=disabled
            )

            result = {
                "product_id": product_id,
                "description": description,
                "brand": brand,
                "eligible": eligibility["eligible"],
                "safety_status": eligibility["safety_status"],
                "reason": eligibility["reason"],
                "matches": eligibility["matches"],
            }

            if eligibility["eligible"]:
                qualifying_products.append(result)

                # Auto-add if requested
                if auto_add:
                    try:
                        with get_db_cursor() as cursor:
                            cursor.execute(
                                """
                                INSERT INTO whole_foods_catalog
                                (product_id, description, brand, added_by, safety_status, last_verified_at)
                                VALUES (?, ?, ?, ?, ?, ?)
                                ON CONFLICT(product_id) DO UPDATE SET
                                    safety_status = excluded.safety_status,
                                    last_verified_at = excluded.last_verified_at
                                """,
                                (
                                    product_id,
                                    description,
                                    brand,
                                    "auto_scan",
                                    eligibility["safety_status"],
                                    datetime.now().isoformat(),
                                ),
                            )
                    except Exception:
                        pass
            else:
                rejected_products.append(result)

        return {
            "success": True,
            "category": category,
            "qualifying_products": qualifying_products,
            "rejected_products": rejected_products if ctx else [],
            "summary": {
                "scanned": len(products),
                "qualifying": len(qualifying_products),
                "rejected": len(rejected_products),
                "auto_added": len(qualifying_products) if auto_add else 0,
            },
        }
