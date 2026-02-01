"""
Safety management tools for Kroger MCP server.

Provides tools for:
- Managing safe-listed and blocked products
- Viewing and configuring ingredient filter settings
- Checking product safety status
"""

from typing import Dict, Any, Optional, List
from pydantic import Field
from fastmcp import Context

from ..analytics import safety
from ..analytics.ingredients import (
    get_all_ingredients,
    get_ingredients_by_severity,
    get_ingredients_by_category,
    get_categories,
    Severity,
)


def register_tools(mcp):
    """Register safety-related tools with the FastMCP server."""

    # ==================== Settings Tools ====================

    @mcp.tool()
    async def get_safety_settings(ctx: Context = None) -> Dict[str, Any]:
        """
        Get current ingredient safety filter settings.

        Returns:
            - filtering_enabled: Whether ingredient filtering is active
            - block_mode: How flagged products are handled ('soft', 'hard', 'warn_only')
        """
        if ctx:
            await ctx.info("Getting safety filter settings")

        settings = safety.get_safety_settings()
        return {
            "success": True,
            **settings,
            "block_mode_options": {
                "soft": "Warn but allow with confirmation",
                "hard": "Hide from search, block cart additions",
                "warn_only": "Show warnings only, no blocking"
            }
        }

    @mcp.tool()
    async def configure_safety_settings(
        filtering_enabled: Optional[bool] = Field(
            default=None,
            description="Enable or disable ingredient filtering"
        ),
        block_mode: Optional[str] = Field(
            default=None,
            description="Block mode: 'soft', 'hard', or 'warn_only'"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Configure ingredient safety filter settings.

        Args:
            filtering_enabled: Set to False to disable all ingredient checks
            block_mode:
                - 'soft': Warn but allow with confirmation (default)
                - 'hard': Hide flagged products from search, block cart
                - 'warn_only': Just show warnings, no blocking

        Returns:
            Updated settings
        """
        if ctx:
            await ctx.info("Updating safety settings")

        try:
            settings = safety.update_safety_settings(
                filtering_enabled=filtering_enabled,
                block_mode=block_mode,
            )
            return {"success": True, **settings}
        except ValueError as e:
            return {"success": False, "error": str(e)}

    # ==================== Ingredient Management Tools ====================

    @mcp.tool()
    async def get_bad_ingredients_list(
        severity: Optional[str] = Field(
            default=None,
            description="Filter by severity: 'critical', 'warning', 'watch'"
        ),
        category: Optional[str] = Field(
            default=None,
            description="Filter by category (e.g., 'preservative', 'artificial_sweetener')"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Get the list of flagged bad ingredients.

        Each ingredient includes:
        - key: Unique identifier
        - name: Display name
        - aliases: Alternative names to search for
        - severity: critical, warning, or watch
        - reason: Why it's flagged
        - category: Type of additive

        Args:
            severity: Optional filter by severity level
            category: Optional filter by category

        Returns:
            List of bad ingredients with their details
        """
        if ctx:
            await ctx.info("Getting bad ingredients list")

        if severity:
            try:
                sev = Severity(severity)
                ingredients = get_ingredients_by_severity(sev)
            except ValueError:
                return {
                    "success": False,
                    "error": f"Invalid severity: {severity}. Use 'critical', 'warning', or 'watch'"
                }
        elif category:
            ingredients = get_ingredients_by_category(category)
        else:
            ingredients = get_all_ingredients()

        return {
            "success": True,
            "count": len(ingredients),
            "categories": get_categories(),
            "severity_levels": ["critical", "warning", "watch"],
            "ingredients": ingredients,
        }

    @mcp.tool()
    async def toggle_ingredient_check(
        ingredient_key: str = Field(
            description="Ingredient key (e.g., 'msg', 'aspartame', 'red_40')"
        ),
        enabled: bool = Field(
            description="True to enable checking, False to disable"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Enable or disable checking for a specific ingredient.

        Use get_bad_ingredients_list to see available ingredient keys.

        Args:
            ingredient_key: The ingredient's unique key
            enabled: Whether to check for this ingredient

        Returns:
            Confirmation of the change
        """
        if ctx:
            action = "Enabling" if enabled else "Disabling"
            await ctx.info(f"{action} ingredient check: {ingredient_key}")

        result = safety.toggle_ingredient(ingredient_key, enabled)
        return result

    @mcp.tool()
    async def get_ingredient_preferences(ctx: Context = None) -> Dict[str, Any]:
        """
        Get all user ingredient preferences (enabled/disabled status).

        Returns only ingredients where the user has changed the default.
        Ingredients not listed are enabled by default.

        Returns:
            List of ingredient preferences with enabled status
        """
        if ctx:
            await ctx.info("Getting ingredient preferences")

        prefs = safety.get_ingredient_preferences()
        disabled = [p for p in prefs if not p.get("enabled", True)]

        return {
            "success": True,
            "total_preferences": len(prefs),
            "disabled_count": len(disabled),
            "preferences": prefs,
            "note": "Ingredients not listed are enabled by default"
        }

    @mcp.tool()
    async def reset_ingredient_preferences(ctx: Context = None) -> Dict[str, Any]:
        """
        Reset all ingredient preferences to defaults (all enabled).

        This removes all custom ingredient preferences.

        Returns:
            Confirmation of reset
        """
        if ctx:
            await ctx.info("Resetting ingredient preferences to defaults")

        return safety.reset_ingredient_preferences()

    # ==================== Safe Products Management ====================

    @mcp.tool()
    async def approve_product(
        product_id: str = Field(description="Kroger product ID to approve"),
        description: Optional[str] = Field(
            default=None,
            description="Product description (for reference)"
        ),
        brand: Optional[str] = Field(
            default=None,
            description="Product brand (for reference)"
        ),
        reason: Optional[str] = Field(
            default=None,
            description="Reason for approval"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Add a product to the safe list.

        Safe-listed products bypass all ingredient checks and are
        prioritized in search results.

        Args:
            product_id: The Kroger product ID
            description: Optional product description
            brand: Optional brand name
            reason: Optional reason for approval

        Returns:
            Confirmation of the approval
        """
        if ctx:
            await ctx.info(f"Approving product {product_id}")

        return safety.add_to_safe_list(
            product_id=product_id,
            description=description,
            brand=brand,
            reason=reason,
        )

    @mcp.tool()
    async def unapprove_product(
        product_id: str = Field(description="Kroger product ID to remove from safe list"),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Remove a product from the safe list.

        The product will be checked against ingredient filters again.

        Args:
            product_id: The Kroger product ID

        Returns:
            Confirmation of removal
        """
        if ctx:
            await ctx.info(f"Removing product {product_id} from safe list")

        return safety.remove_from_safe_list(product_id)

    @mcp.tool()
    async def get_safe_products(ctx: Context = None) -> Dict[str, Any]:
        """
        Get all products on the safe list.

        Returns products that have been explicitly approved and will
        bypass all ingredient checks.

        Returns:
            List of safe-listed products with details
        """
        if ctx:
            await ctx.info("Getting safe products list")

        products = safety.get_safe_products()
        return {
            "success": True,
            "count": len(products),
            "products": products,
        }

    # ==================== Blocked Products Management ====================

    @mcp.tool()
    async def block_product(
        product_id: str = Field(description="Kroger product ID to block"),
        description: Optional[str] = Field(
            default=None,
            description="Product description (for reference)"
        ),
        reason: Optional[str] = Field(
            default=None,
            description="Reason for blocking"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Add a product to the blocked list.

        Blocked products require explicit confirmation to add to cart
        and may be hidden in search results (depending on block mode).

        Args:
            product_id: The Kroger product ID
            description: Optional product description
            reason: Reason for blocking

        Returns:
            Confirmation of the block
        """
        if ctx:
            await ctx.info(f"Blocking product {product_id}")

        return safety.add_to_blocked_list(
            product_id=product_id,
            description=description,
            reason=reason,
        )

    @mcp.tool()
    async def unblock_product(
        product_id: str = Field(description="Kroger product ID to unblock"),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Remove a product from the blocked list.

        Args:
            product_id: The Kroger product ID

        Returns:
            Confirmation of removal
        """
        if ctx:
            await ctx.info(f"Unblocking product {product_id}")

        return safety.remove_from_blocked_list(product_id)

    @mcp.tool()
    async def get_blocked_products(ctx: Context = None) -> Dict[str, Any]:
        """
        Get all products on the blocked list.

        Returns products that have been explicitly blocked.

        Returns:
            List of blocked products with details
        """
        if ctx:
            await ctx.info("Getting blocked products list")

        products = safety.get_blocked_products()
        return {
            "success": True,
            "count": len(products),
            "products": products,
        }

    # ==================== Safety Checking Tools ====================

    @mcp.tool()
    async def check_product_safety(
        product_id: str = Field(description="Kroger product ID to check"),
        description: str = Field(description="Product description to scan"),
        brand: Optional[str] = Field(
            default=None,
            description="Product brand"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Check a single product's safety status.

        Scans the product description for bad ingredients and checks
        safe/blocked lists.

        Args:
            product_id: The Kroger product ID
            description: Product description to scan for ingredients
            brand: Optional brand name

        Returns:
            Safety status including:
            - safety_status: 'safe', 'unknown', 'watch', 'warning', 'critical', 'blocked'
            - is_safe_listed: Whether on the safe list
            - is_blocked: Whether on the blocked list
            - flagged_ingredients: List of detected bad ingredients
        """
        if ctx:
            await ctx.info(f"Checking safety for product {product_id}")

        status = safety.get_product_safety_status(
            product_id=product_id,
            description=description,
            brand=brand,
        )
        return {
            "success": True,
            **status.to_dict(),
        }

    @mcp.tool()
    async def check_products_safety(
        products: List[Dict[str, Any]] = Field(
            description="List of products with product_id and description"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Check safety status for multiple products.

        Each product should have:
        - product_id: The Kroger product ID
        - description: Product description to scan

        Args:
            products: List of product dicts

        Returns:
            Safety status for each product
        """
        if ctx:
            await ctx.info(f"Checking safety for {len(products)} products")

        if len(products) > 50:
            return {
                "success": False,
                "error": "Maximum 50 products per request"
            }

        statuses = safety.check_products_safety_batch(products)
        return {
            "success": True,
            "count": len(statuses),
            "results": [s.to_dict() for s in statuses],
        }

    @mcp.tool()
    async def check_cart_safety(ctx: Context = None) -> Dict[str, Any]:
        """
        Scan the current cart for products with safety concerns.

        Checks all items currently in the local cart tracking
        against the ingredient filter.

        Returns:
            - safe_items: Products with no concerns
            - flagged_items: Products with ingredient concerns
            - blocked_items: Products on the blocked list
        """
        if ctx:
            await ctx.info("Scanning cart for safety concerns")

        # Import here to avoid circular imports
        from .cart_tools import _load_cart_data

        try:
            cart_data = _load_cart_data()
            cart_items = cart_data.get("current_cart", [])
        except Exception:
            cart_items = []

        if not cart_items:
            return {
                "success": True,
                "message": "Cart is empty",
                "safe_items": [],
                "flagged_items": [],
                "blocked_items": [],
            }

        # Build product list for batch check
        products = [
            {
                "product_id": item.get("product_id", ""),
                "description": item.get("description", ""),
                "brand": item.get("brand"),
            }
            for item in cart_items
        ]

        statuses = safety.check_products_safety_batch(products)

        safe_items = []
        flagged_items = []
        blocked_items = []

        for i, status in enumerate(statuses):
            item_info = {
                **products[i],
                **status.to_dict(),
            }

            if status.is_blocked:
                blocked_items.append(item_info)
            elif status.safety_result and status.safety_result.has_concerns:
                flagged_items.append(item_info)
            else:
                safe_items.append(item_info)

        return {
            "success": True,
            "total_items": len(cart_items),
            "safe_count": len(safe_items),
            "flagged_count": len(flagged_items),
            "blocked_count": len(blocked_items),
            "safe_items": safe_items,
            "flagged_items": flagged_items,
            "blocked_items": blocked_items,
        }
