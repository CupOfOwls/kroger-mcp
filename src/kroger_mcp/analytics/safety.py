"""
Product safety checking and management.

This module provides functions for:
- Checking products against the bad ingredients list
- Managing safe-listed and blocked products
- Managing user preferences for ingredient filtering
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Any, List, Optional, Set

from .database import get_db_cursor, ensure_initialized
from .ingredients import (
    check_product_safety,
    SafetyResult,
    Severity,
)


class SafetyStatus(str, Enum):
    """Overall safety status for a product."""
    SAFE = "safe"          # On safe list (explicitly approved)
    UNKNOWN = "unknown"    # No matches found, not on any list
    WATCH = "watch"        # Contains watch-level ingredients
    WARNING = "warning"    # Contains warning-level ingredients
    CRITICAL = "critical"  # Contains critical-level ingredients
    BLOCKED = "blocked"    # On blocked list (explicitly blocked)


class BlockMode(str, Enum):
    """How to handle flagged products."""
    SOFT = "soft"          # Warn but allow with confirmation
    HARD = "hard"          # Hide from search, block cart additions
    WARN_ONLY = "warn_only"  # Just show warnings, no blocking


@dataclass
class ProductSafetyStatus:
    """Complete safety status for a product."""
    product_id: str
    status: SafetyStatus
    is_safe_listed: bool
    is_blocked: bool
    blocked_reason: Optional[str]
    safety_result: Optional[SafetyResult]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = {
            "product_id": self.product_id,
            "safety_status": self.status.value,
            "is_safe_listed": self.is_safe_listed,
            "is_blocked": self.is_blocked,
        }
        if self.is_blocked and self.blocked_reason:
            result["blocked_reason"] = self.blocked_reason
        if self.safety_result and self.safety_result.has_concerns:
            result["flagged_ingredients"] = self.safety_result.to_dict()["flagged_ingredients"]
        else:
            result["flagged_ingredients"] = []
        return result


# ============== Settings Management ==============

def get_safety_settings() -> Dict[str, Any]:
    """Get current safety filter settings."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute("SELECT key, value FROM safety_settings")
        rows = cursor.fetchall()

    settings = {
        "filtering_enabled": True,
        "block_mode": BlockMode.SOFT.value,
    }

    for row in rows:
        key = row["key"]
        value = row["value"]
        if key == "filtering_enabled":
            settings["filtering_enabled"] = value == "1"
        elif key == "block_mode":
            settings["block_mode"] = value

    return settings


def update_safety_settings(
    filtering_enabled: Optional[bool] = None,
    block_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Update safety filter settings."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        now = datetime.now().isoformat()

        if filtering_enabled is not None:
            cursor.execute(
                """
                INSERT INTO safety_settings (key, value, updated_at)
                VALUES ('filtering_enabled', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
                """,
                ("1" if filtering_enabled else "0", now,
                 "1" if filtering_enabled else "0", now)
            )

        if block_mode is not None:
            # Validate block mode
            if block_mode not in [m.value for m in BlockMode]:
                raise ValueError(f"Invalid block_mode: {block_mode}")
            cursor.execute(
                """
                INSERT INTO safety_settings (key, value, updated_at)
                VALUES ('block_mode', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
                """,
                (block_mode, now, block_mode, now)
            )

    return get_safety_settings()


# ============== Safe Products Management ==============

def is_product_safe_listed(product_id: str) -> bool:
    """Check if a product is on the safe list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT 1 FROM safe_products WHERE product_id = ?",
            (product_id,)
        )
        return cursor.fetchone() is not None


def get_all_safe_product_ids() -> Set[str]:
    """Get all safe-listed product IDs for fast lookup."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute("SELECT product_id FROM safe_products")
        return {row["product_id"] for row in cursor.fetchall()}


def add_to_safe_list(
    product_id: str,
    description: Optional[str] = None,
    brand: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Add a product to the safe list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO safe_products (product_id, description, brand, added_reason)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                description = COALESCE(?, description),
                brand = COALESCE(?, brand),
                added_reason = COALESCE(?, added_reason),
                added_at = CURRENT_TIMESTAMP
            """,
            (product_id, description, brand, reason,
             description, brand, reason)
        )

        # Also remove from blocked list if present
        cursor.execute(
            "DELETE FROM blocked_products WHERE product_id = ?",
            (product_id,)
        )

    return {
        "success": True,
        "product_id": product_id,
        "message": f"Product {product_id} added to safe list"
    }


def remove_from_safe_list(product_id: str) -> Dict[str, Any]:
    """Remove a product from the safe list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            "DELETE FROM safe_products WHERE product_id = ?",
            (product_id,)
        )
        deleted = cursor.rowcount

    if deleted:
        return {
            "success": True,
            "product_id": product_id,
            "message": f"Product {product_id} removed from safe list"
        }
    return {
        "success": False,
        "product_id": product_id,
        "message": f"Product {product_id} was not on safe list"
    }


def get_safe_products() -> List[Dict[str, Any]]:
    """Get all products on the safe list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, description, brand, added_at, added_reason
            FROM safe_products
            ORDER BY added_at DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]


# ============== Blocked Products Management ==============

def is_product_blocked(product_id: str) -> tuple[bool, Optional[str]]:
    """Check if a product is on the blocked list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT blocked_reason FROM blocked_products WHERE product_id = ?",
            (product_id,)
        )
        row = cursor.fetchone()
        if row:
            return True, row["blocked_reason"]
        return False, None


def get_all_blocked_product_ids() -> Set[str]:
    """Get all blocked product IDs for fast lookup."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute("SELECT product_id FROM blocked_products")
        return {row["product_id"] for row in cursor.fetchall()}


def add_to_blocked_list(
    product_id: str,
    description: Optional[str] = None,
    reason: Optional[str] = None,
    auto_blocked: bool = False,
) -> Dict[str, Any]:
    """Add a product to the blocked list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO blocked_products (product_id, description, blocked_reason, auto_blocked)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(product_id) DO UPDATE SET
                description = COALESCE(?, description),
                blocked_reason = COALESCE(?, blocked_reason),
                blocked_at = CURRENT_TIMESTAMP
            """,
            (product_id, description, reason, 1 if auto_blocked else 0,
             description, reason)
        )

        # Also remove from safe list if present
        cursor.execute(
            "DELETE FROM safe_products WHERE product_id = ?",
            (product_id,)
        )

    return {
        "success": True,
        "product_id": product_id,
        "message": f"Product {product_id} added to blocked list"
    }


def remove_from_blocked_list(product_id: str) -> Dict[str, Any]:
    """Remove a product from the blocked list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            "DELETE FROM blocked_products WHERE product_id = ?",
            (product_id,)
        )
        deleted = cursor.rowcount

    if deleted:
        return {
            "success": True,
            "product_id": product_id,
            "message": f"Product {product_id} removed from blocked list"
        }
    return {
        "success": False,
        "product_id": product_id,
        "message": f"Product {product_id} was not on blocked list"
    }


def get_blocked_products() -> List[Dict[str, Any]]:
    """Get all products on the blocked list."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT product_id, description, blocked_at, blocked_reason, auto_blocked
            FROM blocked_products
            ORDER BY blocked_at DESC
            """
        )
        return [dict(row) for row in cursor.fetchall()]


# ============== Ingredient Preferences ==============

def get_disabled_ingredients() -> Set[str]:
    """Get set of ingredient keys that the user has disabled."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            "SELECT ingredient_key FROM ingredient_preferences WHERE enabled = 0"
        )
        return {row["ingredient_key"] for row in cursor.fetchall()}


def toggle_ingredient(ingredient_key: str, enabled: bool) -> Dict[str, Any]:
    """Enable or disable checking for a specific ingredient."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingredient_preferences (ingredient_key, enabled, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(ingredient_key) DO UPDATE SET
                enabled = ?,
                updated_at = CURRENT_TIMESTAMP
            """,
            (ingredient_key, 1 if enabled else 0, 1 if enabled else 0)
        )

    return {
        "success": True,
        "ingredient_key": ingredient_key,
        "enabled": enabled,
    }


def get_ingredient_preferences() -> List[Dict[str, Any]]:
    """Get all ingredient preferences."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute(
            """
            SELECT ingredient_key, enabled, severity, updated_at
            FROM ingredient_preferences
            ORDER BY ingredient_key
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def reset_ingredient_preferences() -> Dict[str, Any]:
    """Reset all ingredient preferences to defaults (all enabled)."""
    ensure_initialized()

    with get_db_cursor() as cursor:
        cursor.execute("DELETE FROM ingredient_preferences")
        deleted = cursor.rowcount

    return {
        "success": True,
        "message": f"Reset {deleted} ingredient preferences to defaults"
    }


# ============== Product Safety Checking ==============

def get_product_safety_status(
    product_id: str,
    description: str,
    brand: Optional[str] = None,
    categories: Optional[List[str]] = None,
) -> ProductSafetyStatus:
    """
    Get the complete safety status for a product.

    This checks:
    1. If product is on the safe list (bypasses all checks)
    2. If product is on the blocked list
    3. If product matches any bad ingredients

    Args:
        product_id: Kroger product ID
        description: Product description to scan
        brand: Product brand (not scanned)
        categories: Product categories

    Returns:
        ProductSafetyStatus with complete safety information
    """
    ensure_initialized()

    # Check safe list first
    if is_product_safe_listed(product_id):
        return ProductSafetyStatus(
            product_id=product_id,
            status=SafetyStatus.SAFE,
            is_safe_listed=True,
            is_blocked=False,
            blocked_reason=None,
            safety_result=None,
        )

    # Check blocked list
    is_blocked, blocked_reason = is_product_blocked(product_id)
    if is_blocked:
        return ProductSafetyStatus(
            product_id=product_id,
            status=SafetyStatus.BLOCKED,
            is_safe_listed=False,
            is_blocked=True,
            blocked_reason=blocked_reason,
            safety_result=None,
        )

    # Get disabled ingredients
    disabled = get_disabled_ingredients()

    # Check ingredients
    safety_result = check_product_safety(
        description=description,
        brand=brand,
        categories=categories,
        disabled_ingredients=disabled,
    )

    # Determine status based on highest severity
    if not safety_result.has_concerns:
        status = SafetyStatus.UNKNOWN
    elif safety_result.highest_severity == Severity.CRITICAL:
        status = SafetyStatus.CRITICAL
    elif safety_result.highest_severity == Severity.WARNING:
        status = SafetyStatus.WARNING
    else:
        status = SafetyStatus.WATCH

    return ProductSafetyStatus(
        product_id=product_id,
        status=status,
        is_safe_listed=False,
        is_blocked=False,
        blocked_reason=None,
        safety_result=safety_result,
    )


def check_products_safety_batch(
    products: List[Dict[str, Any]],
) -> List[ProductSafetyStatus]:
    """
    Check safety status for multiple products efficiently.

    Args:
        products: List of product dicts with 'product_id', 'description', 'brand'

    Returns:
        List of ProductSafetyStatus objects
    """
    ensure_initialized()

    # Pre-load safe and blocked lists for O(1) lookups
    safe_ids = get_all_safe_product_ids()
    blocked_ids = get_all_blocked_product_ids()
    disabled = get_disabled_ingredients()

    # Get blocked reasons
    blocked_reasons: Dict[str, str] = {}
    if blocked_ids:
        with get_db_cursor() as cursor:
            cursor.execute(
                "SELECT product_id, blocked_reason FROM blocked_products"
            )
            for row in cursor.fetchall():
                blocked_reasons[row["product_id"]] = row["blocked_reason"]

    results = []
    for product in products:
        product_id = product.get("product_id", "")
        description = product.get("description", "")
        brand = product.get("brand")

        # Check safe list
        if product_id in safe_ids:
            results.append(ProductSafetyStatus(
                product_id=product_id,
                status=SafetyStatus.SAFE,
                is_safe_listed=True,
                is_blocked=False,
                blocked_reason=None,
                safety_result=None,
            ))
            continue

        # Check blocked list
        if product_id in blocked_ids:
            results.append(ProductSafetyStatus(
                product_id=product_id,
                status=SafetyStatus.BLOCKED,
                is_safe_listed=False,
                is_blocked=True,
                blocked_reason=blocked_reasons.get(product_id),
                safety_result=None,
            ))
            continue

        # Check ingredients
        safety_result = check_product_safety(
            description=description,
            brand=brand,
            disabled_ingredients=disabled,
        )

        # Determine status
        if not safety_result.has_concerns:
            status = SafetyStatus.UNKNOWN
        elif safety_result.highest_severity == Severity.CRITICAL:
            status = SafetyStatus.CRITICAL
        elif safety_result.highest_severity == Severity.WARNING:
            status = SafetyStatus.WARNING
        else:
            status = SafetyStatus.WATCH

        results.append(ProductSafetyStatus(
            product_id=product_id,
            status=status,
            is_safe_listed=False,
            is_blocked=False,
            blocked_reason=None,
            safety_result=safety_result,
        ))

    return results


def is_filtering_enabled() -> bool:
    """Check if ingredient filtering is enabled."""
    settings = get_safety_settings()
    return settings.get("filtering_enabled", True)


def get_block_mode() -> BlockMode:
    """Get the current block mode."""
    settings = get_safety_settings()
    mode_str = settings.get("block_mode", "soft")
    return BlockMode(mode_str)
