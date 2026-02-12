"""
Ingredient management tools for dynamic ingredient filter customization.

Allows users to:
- Add custom ingredients beyond the 62 defaults
- Edit existing custom ingredients
- Override system ingredient settings
- Import/export ingredient lists
- Preview impact of changes
"""

import json
from typing import Dict, Any, Optional, List, Literal
from pydantic import Field
from fastmcp import Context

from ..analytics.database import get_db_connection
from ..analytics.ingredients import get_compiled_patterns, get_active_ingredients


def register_tools(mcp):
    """Register ingredient management tools with the FastMCP server."""

    # ==================== Core Management Tools ====================

    @mcp.tool()
    async def add_custom_ingredient(
        ingredient_name: str = Field(description="Name of the ingredient to add"),
        severity: Literal["critical", "warning", "watch"] = Field(
            description="Severity level: critical (strong evidence of harm), warning (moderate concern), watch (minimize for health)"
        ),
        category: Optional[str] = Field(
            default=None,
            description="Category: preservative, sweetener, emulsifier, artificial_color, flavoring, etc."
        ),
        reason: Optional[str] = Field(
            default=None,
            description="Why this ingredient should be avoided (e.g., 'linked to gut inflammation')"
        ),
        aliases: Optional[List[str]] = Field(
            default=None,
            description="Alternative names/spellings for this ingredient"
        ),
        notes: Optional[str] = Field(
            default=None,
            description="Personal notes about this ingredient"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Add a custom ingredient to your personal filter list.

        This allows you to flag ingredients beyond the default 62. Changes take
        effect immediately (no restart needed).

        Example:
            add_custom_ingredient(
                ingredient_name="maltitol",
                severity="warning",
                category="sugar_alcohol",
                reason="Causes digestive distress, laxative effect",
                aliases=["E965", "hydrogenated maltose"]
            )
        """
        if ctx:
            await ctx.info(f"Adding custom ingredient: {ingredient_name}")

        conn = get_db_connection()
        try:
            # Check if already exists
            cursor = conn.execute(
                "SELECT id FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                (ingredient_name,)
            )
            if cursor.fetchone():
                return {
                    "success": False,
                    "error": f"Ingredient '{ingredient_name}' already exists. Use edit_custom_ingredient to modify it."
                }

            # Insert new ingredient
            aliases_json = json.dumps(aliases) if aliases else None
            cursor = conn.execute(
                """
                INSERT INTO custom_ingredients
                    (ingredient_name, severity, category, reason, aliases, notes)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ingredient_name, severity, category, reason, aliases_json, notes)
            )
            conn.commit()

            # Force pattern cache refresh
            get_compiled_patterns(force_refresh=True)

            return {
                "success": True,
                "message": f"Added custom ingredient: {ingredient_name}",
                "ingredient_id": cursor.lastrowid,
                "details": {
                    "name": ingredient_name,
                    "severity": severity,
                    "category": category,
                    "reason": reason,
                    "aliases": aliases or [],
                }
            }

        except Exception as e:
            conn.rollback()
            return {
                "success": False,
                "error": f"Failed to add ingredient: {str(e)}"
            }
        finally:
            conn.close()

    @mcp.tool()
    async def edit_custom_ingredient(
        ingredient_name: str = Field(description="Name of the ingredient to edit"),
        new_severity: Optional[Literal["critical", "warning", "watch"]] = Field(
            default=None,
            description="New severity level (leave empty to keep current)"
        ),
        new_reason: Optional[str] = Field(
            default=None,
            description="New reason (leave empty to keep current)"
        ),
        add_aliases: Optional[List[str]] = Field(
            default=None,
            description="Additional aliases to add (will be merged with existing)"
        ),
        new_notes: Optional[str] = Field(
            default=None,
            description="New notes (leave empty to keep current)"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Edit an existing custom ingredient.

        Only modifies fields you specify. Other fields remain unchanged.

        Example:
            edit_custom_ingredient(
                ingredient_name="maltitol",
                new_severity="critical",
                add_aliases=["maltitol syrup"]
            )
        """
        if ctx:
            await ctx.info(f"Editing custom ingredient: {ingredient_name}")

        conn = get_db_connection()
        try:
            # Get current ingredient
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                (ingredient_name,)
            )
            row = cursor.fetchone()
            if not row:
                return {
                    "success": False,
                    "error": f"Custom ingredient '{ingredient_name}' not found. Use add_custom_ingredient to create it."
                }

            # Build update query
            updates = []
            params = []

            if new_severity:
                updates.append("severity = ?")
                params.append(new_severity)

            if new_reason:
                updates.append("reason = ?")
                params.append(new_reason)

            if new_notes:
                updates.append("notes = ?")
                params.append(new_notes)

            if add_aliases:
                current_aliases = json.loads(row["aliases"]) if row["aliases"] else []
                merged_aliases = list(set(current_aliases + add_aliases))
                updates.append("aliases = ?")
                params.append(json.dumps(merged_aliases))

            if not updates:
                return {
                    "success": False,
                    "error": "No changes specified"
                }

            updates.append("modified_at = CURRENT_TIMESTAMP")
            params.append(ingredient_name)

            # Execute update
            conn.execute(
                f"UPDATE custom_ingredients SET {', '.join(updates)} WHERE LOWER(ingredient_name) = LOWER(?)",
                params
            )
            conn.commit()

            # Force pattern cache refresh
            get_compiled_patterns(force_refresh=True)

            return {
                "success": True,
                "message": f"Updated custom ingredient: {ingredient_name}",
                "changes": {
                    "severity": new_severity,
                    "reason": new_reason,
                    "added_aliases": add_aliases,
                    "notes": new_notes
                }
            }

        except Exception as e:
            conn.rollback()
            return {
                "success": False,
                "error": f"Failed to edit ingredient: {str(e)}"
            }
        finally:
            conn.close()

    @mcp.tool()
    async def remove_custom_ingredient(
        ingredient_name: str = Field(description="Name of the ingredient to remove"),
        permanent: bool = Field(
            default=False,
            description="If True, permanently delete. If False, deactivate (can be reactivated later)"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Remove a custom ingredient from your filter.

        By default, ingredients are soft-deleted (is_active=0) so they can be
        restored later. Use permanent=True to permanently delete.

        Example:
            remove_custom_ingredient("maltitol")  # Soft delete
            remove_custom_ingredient("maltitol", permanent=True)  # Hard delete
        """
        if ctx:
            await ctx.info(f"Removing custom ingredient: {ingredient_name}")

        conn = get_db_connection()
        try:
            # Check if exists
            cursor = conn.execute(
                "SELECT id FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                (ingredient_name,)
            )
            if not cursor.fetchone():
                return {
                    "success": False,
                    "error": f"Custom ingredient '{ingredient_name}' not found"
                }

            if permanent:
                conn.execute(
                    "DELETE FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                    (ingredient_name,)
                )
                message = f"Permanently deleted custom ingredient: {ingredient_name}"
            else:
                conn.execute(
                    "UPDATE custom_ingredients SET is_active = 0, modified_at = CURRENT_TIMESTAMP WHERE LOWER(ingredient_name) = LOWER(?)",
                    (ingredient_name,)
                )
                message = f"Deactivated custom ingredient: {ingredient_name} (can be restored later)"

            conn.commit()

            # Force pattern cache refresh
            get_compiled_patterns(force_refresh=True)

            return {
                "success": True,
                "message": message,
                "permanent": permanent
            }

        except Exception as e:
            conn.rollback()
            return {
                "success": False,
                "error": f"Failed to remove ingredient: {str(e)}"
            }
        finally:
            conn.close()

    @mcp.tool()
    async def list_custom_ingredients(
        include_inactive: bool = Field(
            default=False,
            description="Include deactivated ingredients"
        ),
        filter_severity: Optional[Literal["critical", "warning", "watch"]] = Field(
            default=None,
            description="Filter by severity level"
        ),
        filter_category: Optional[str] = Field(
            default=None,
            description="Filter by category"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        List all custom ingredients you've added.

        Returns ingredients with all details. Can be filtered by severity, category,
        or active status.

        Example:
            list_custom_ingredients()  # All active
            list_custom_ingredients(filter_severity="critical")  # Critical only
            list_custom_ingredients(include_inactive=True)  # Including deactivated
        """
        if ctx:
            await ctx.info("Listing custom ingredients")

        conn = get_db_connection()
        try:
            # Build query
            query = "SELECT * FROM custom_ingredients WHERE 1=1"
            params = []

            if not include_inactive:
                query += " AND is_active = 1"

            if filter_severity:
                query += " AND severity = ?"
                params.append(filter_severity)

            if filter_category:
                query += " AND category = ?"
                params.append(filter_category)

            query += " ORDER BY severity, ingredient_name"

            cursor = conn.execute(query, params)
            rows = cursor.fetchall()

            ingredients = []
            for row in rows:
                ingredients.append({
                    "name": row["ingredient_name"],
                    "severity": row["severity"],
                    "category": row["category"],
                    "reason": row["reason"],
                    "aliases": json.loads(row["aliases"]) if row["aliases"] else [],
                    "source": row["source"],
                    "is_active": bool(row["is_active"]),
                    "created_at": row["created_at"],
                    "modified_at": row["modified_at"],
                    "notes": row["notes"]
                })

            # Group by severity
            by_severity = {
                "critical": [i for i in ingredients if i["severity"] == "critical"],
                "warning": [i for i in ingredients if i["severity"] == "warning"],
                "watch": [i for i in ingredients if i["severity"] == "watch"]
            }

            return {
                "success": True,
                "total_count": len(ingredients),
                "active_count": sum(1 for i in ingredients if i["is_active"]),
                "by_severity": {
                    "critical": len(by_severity["critical"]),
                    "warning": len(by_severity["warning"]),
                    "watch": len(by_severity["watch"])
                },
                "ingredients": ingredients
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to list ingredients: {str(e)}"
            }
        finally:
            conn.close()

    # ==================== Override System Ingredients ====================

    @mcp.tool()
    async def override_system_ingredient(
        ingredient_name: str = Field(description="Name of the system ingredient to override"),
        new_severity: Optional[Literal["critical", "warning", "watch"]] = Field(
            default=None,
            description="Override severity (leave empty to keep default)"
        ),
        new_reason: Optional[str] = Field(
            default=None,
            description="Override reason (leave empty to keep default)"
        ),
        add_aliases: Optional[List[str]] = Field(
            default=None,
            description="Add extra aliases to system ingredient"
        ),
        hide: bool = Field(
            default=False,
            description="Hide this ingredient from active filter"
        ),
        notes: Optional[str] = Field(
            default=None,
            description="Personal notes about this override"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Override settings for a default (system) ingredient.

        Use this to:
        - Change severity of default ingredients (e.g., lower MSG from critical to warning)
        - Hide ingredients you don't want to check for
        - Add aliases to catch more variations

        Example:
            override_system_ingredient(
                ingredient_name="MSG",
                new_severity="watch",
                notes="I tolerate MSG well"
            )
        """
        if ctx:
            await ctx.info(f"Overriding system ingredient: {ingredient_name}")

        # Verify it's a system ingredient
        from ..analytics.ingredients import BAD_INGREDIENTS
        system_names = {ing.name.lower() for ing in BAD_INGREDIENTS}
        if ingredient_name.lower() not in system_names:
            return {
                "success": False,
                "error": f"'{ingredient_name}' is not a system ingredient. Use add_custom_ingredient for custom ingredients."
            }

        conn = get_db_connection()
        try:
            # Check if override exists
            cursor = conn.execute(
                "SELECT id FROM ingredient_overrides WHERE LOWER(ingredient_name) = LOWER(?)",
                (ingredient_name,)
            )
            existing = cursor.fetchone()

            aliases_json = json.dumps(add_aliases) if add_aliases else None

            if existing:
                # Update existing override
                updates = []
                params = []

                if new_severity:
                    updates.append("override_severity = ?")
                    params.append(new_severity)

                if new_reason:
                    updates.append("override_reason = ?")
                    params.append(new_reason)

                if add_aliases:
                    # Merge with existing aliases
                    cursor = conn.execute(
                        "SELECT additional_aliases FROM ingredient_overrides WHERE id = ?",
                        (existing["id"],)
                    )
                    current = cursor.fetchone()["additional_aliases"]
                    current_list = json.loads(current) if current else []
                    merged = list(set(current_list + add_aliases))
                    updates.append("additional_aliases = ?")
                    params.append(json.dumps(merged))

                if hide:
                    updates.append("is_hidden = 1")

                if notes:
                    updates.append("notes = ?")
                    params.append(notes)

                updates.append("modified_at = CURRENT_TIMESTAMP")
                params.append(ingredient_name)

                if updates:
                    conn.execute(
                        f"UPDATE ingredient_overrides SET {', '.join(updates)} WHERE LOWER(ingredient_name) = LOWER(?)",
                        params
                    )
            else:
                # Create new override
                conn.execute(
                    """
                    INSERT INTO ingredient_overrides
                        (ingredient_name, override_severity, override_reason, additional_aliases, is_hidden, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ingredient_name, new_severity, new_reason, aliases_json, 1 if hide else 0, notes)
                )

            conn.commit()

            # Force pattern cache refresh
            get_compiled_patterns(force_refresh=True)

            return {
                "success": True,
                "message": f"Overrode system ingredient: {ingredient_name}",
                "changes": {
                    "severity": new_severity,
                    "reason": new_reason,
                    "aliases": add_aliases,
                    "hidden": hide,
                    "notes": notes
                }
            }

        except Exception as e:
            conn.rollback()
            return {
                "success": False,
                "error": f"Failed to override ingredient: {str(e)}"
            }
        finally:
            conn.close()

    @mcp.tool()
    async def reset_ingredient_to_default(
        ingredient_name: str = Field(description="Name of the system ingredient to reset"),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Reset a system ingredient to its default settings.

        Removes any overrides you've applied. The ingredient will revert to its
        original severity, reason, and aliases.

        Example:
            reset_ingredient_to_default("MSG")
        """
        if ctx:
            await ctx.info(f"Resetting ingredient to default: {ingredient_name}")

        conn = get_db_connection()
        try:
            cursor = conn.execute(
                "DELETE FROM ingredient_overrides WHERE LOWER(ingredient_name) = LOWER(?)",
                (ingredient_name,)
            )

            if cursor.rowcount == 0:
                return {
                    "success": False,
                    "error": f"No override found for '{ingredient_name}'"
                }

            conn.commit()

            # Force pattern cache refresh
            get_compiled_patterns(force_refresh=True)

            return {
                "success": True,
                "message": f"Reset ingredient to default: {ingredient_name}"
            }

        except Exception as e:
            conn.rollback()
            return {
                "success": False,
                "error": f"Failed to reset ingredient: {str(e)}"
            }
        finally:
            conn.close()

    @mcp.tool()
    async def get_ingredient_info(
        ingredient_name: str = Field(description="Name of the ingredient to get info for"),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Get detailed information about an ingredient (custom or system).

        Shows current settings, including any overrides applied.

        Example:
            get_ingredient_info("MSG")
        """
        if ctx:
            await ctx.info(f"Getting info for ingredient: {ingredient_name}")

        # Check if it's a system ingredient
        from ..analytics.ingredients import BAD_INGREDIENTS
        system_ing = None
        for ing in BAD_INGREDIENTS:
            if ing.name.lower() == ingredient_name.lower():
                system_ing = ing
                break

        conn = get_db_connection()
        try:
            result = {}

            if system_ing:
                # System ingredient
                result["source"] = "system"
                result["default_settings"] = {
                    "name": system_ing.name,
                    "severity": system_ing.severity.value,
                    "category": system_ing.category,
                    "reason": system_ing.reason,
                    "aliases": list(system_ing.aliases),
                    "key": system_ing.key
                }

                # Check for overrides
                cursor = conn.execute(
                    "SELECT * FROM ingredient_overrides WHERE LOWER(ingredient_name) = LOWER(?)",
                    (ingredient_name,)
                )
                override = cursor.fetchone()

                if override:
                    result["has_override"] = True
                    result["current_settings"] = {
                        "name": system_ing.name,
                        "severity": override["override_severity"] or system_ing.severity.value,
                        "category": system_ing.category,
                        "reason": override["override_reason"] or system_ing.reason,
                        "aliases": list(system_ing.aliases) + (json.loads(override["additional_aliases"]) if override["additional_aliases"] else []),
                        "is_hidden": bool(override["is_hidden"]),
                        "notes": override["notes"]
                    }
                else:
                    result["has_override"] = False
                    result["current_settings"] = result["default_settings"]

            else:
                # Check if custom ingredient
                cursor = conn.execute(
                    "SELECT * FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                    (ingredient_name,)
                )
                custom = cursor.fetchone()

                if custom:
                    result["source"] = "custom"
                    result["current_settings"] = {
                        "name": custom["ingredient_name"],
                        "severity": custom["severity"],
                        "category": custom["category"],
                        "reason": custom["reason"],
                        "aliases": json.loads(custom["aliases"]) if custom["aliases"] else [],
                        "is_active": bool(custom["is_active"]),
                        "created_at": custom["created_at"],
                        "modified_at": custom["modified_at"],
                        "notes": custom["notes"]
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Ingredient '{ingredient_name}' not found"
                    }

            result["success"] = True
            return result

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get ingredient info: {str(e)}"
            }
        finally:
            conn.close()

    # ==================== Import/Export & Preview ====================

    @mcp.tool()
    async def import_ingredient_list(
        import_data: str = Field(description="JSON string containing ingredients to import"),
        merge_strategy: Literal["replace", "merge", "skip_existing"] = Field(
            default="merge",
            description="How to handle conflicts: replace (overwrite), merge (add new only), skip_existing (don't import duplicates)"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Import custom ingredients from a JSON string.

        JSON format:
        {
          "ingredients": [
            {
              "name": "ingredient name",
              "severity": "critical",
              "category": "sweetener",
              "reason": "why avoid",
              "aliases": ["alias1", "alias2"]
            }
          ],
          "overrides": [
            {
              "name": "system ingredient",
              "new_severity": "watch"
            }
          ]
        }

        Example:
            import_ingredient_list('{"ingredients": [...]}', merge_strategy="merge")
        """
        if ctx:
            await ctx.info("Importing ingredient list")

        try:
            data = json.loads(import_data)
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON: {str(e)}"
            }

        conn = get_db_connection()
        imported_count = 0
        skipped_count = 0
        errors = []

        try:
            # Import custom ingredients
            if "ingredients" in data:
                for ing in data["ingredients"]:
                    try:
                        name = ing["name"]
                        severity = ing["severity"]

                        # Check if exists
                        cursor = conn.execute(
                            "SELECT id FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                            (name,)
                        )
                        exists = cursor.fetchone()

                        if exists:
                            if merge_strategy == "skip_existing":
                                skipped_count += 1
                                continue
                            elif merge_strategy == "replace":
                                conn.execute(
                                    "DELETE FROM custom_ingredients WHERE LOWER(ingredient_name) = LOWER(?)",
                                    (name,)
                                )

                        if not exists or merge_strategy == "replace":
                            aliases_json = json.dumps(ing.get("aliases", []))
                            conn.execute(
                                """
                                INSERT INTO custom_ingredients
                                    (ingredient_name, severity, category, reason, aliases, source)
                                VALUES (?, ?, ?, ?, ?, 'imported')
                                """,
                                (name, severity, ing.get("category"), ing.get("reason"), aliases_json)
                            )
                            imported_count += 1

                    except Exception as e:
                        errors.append(f"Failed to import '{ing.get('name', 'unknown')}': {str(e)}")

            # Import overrides
            if "overrides" in data:
                for override in data["overrides"]:
                    try:
                        name = override["name"]

                        # Check if override exists
                        cursor = conn.execute(
                            "SELECT id FROM ingredient_overrides WHERE LOWER(ingredient_name) = LOWER(?)",
                            (name,)
                        )
                        exists = cursor.fetchone()

                        if exists and merge_strategy == "skip_existing":
                            skipped_count += 1
                            continue

                        if exists and merge_strategy == "replace":
                            conn.execute(
                                "DELETE FROM ingredient_overrides WHERE LOWER(ingredient_name) = LOWER(?)",
                                (name,)
                            )

                        if not exists or merge_strategy == "replace":
                            aliases_json = json.dumps(override.get("add_aliases", [])) if override.get("add_aliases") else None
                            conn.execute(
                                """
                                INSERT INTO ingredient_overrides
                                    (ingredient_name, override_severity, override_reason, additional_aliases, is_hidden)
                                VALUES (?, ?, ?, ?, ?)
                                """,
                                (name, override.get("new_severity"), override.get("new_reason"),
                                 aliases_json, override.get("hide", 0))
                            )
                            imported_count += 1

                    except Exception as e:
                        errors.append(f"Failed to import override for '{override.get('name', 'unknown')}': {str(e)}")

            conn.commit()

            # Force pattern cache refresh
            get_compiled_patterns(force_refresh=True)

            return {
                "success": True,
                "message": f"Imported {imported_count} items, skipped {skipped_count}",
                "imported_count": imported_count,
                "skipped_count": skipped_count,
                "errors": errors if errors else None
            }

        except Exception as e:
            conn.rollback()
            return {
                "success": False,
                "error": f"Import failed: {str(e)}",
                "errors": errors
            }
        finally:
            conn.close()

    @mcp.tool()
    async def export_ingredient_list(
        include_system_overrides: bool = Field(
            default=True,
            description="Include overrides for system ingredients"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Export your custom ingredients to a JSON string.

        The exported data can be shared with others or used as a backup.
        Use import_ingredient_list() to restore.

        Example:
            export_ingredient_list(include_system_overrides=True)
        """
        if ctx:
            await ctx.info("Exporting ingredient list")

        conn = get_db_connection()
        try:
            # Export custom ingredients
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE is_active = 1 ORDER BY severity, ingredient_name"
            )
            custom_rows = cursor.fetchall()

            ingredients = []
            for row in custom_rows:
                ingredients.append({
                    "name": row["ingredient_name"],
                    "severity": row["severity"],
                    "category": row["category"],
                    "reason": row["reason"],
                    "aliases": json.loads(row["aliases"]) if row["aliases"] else []
                })

            # Export overrides if requested
            overrides = []
            if include_system_overrides:
                cursor = conn.execute(
                    "SELECT * FROM ingredient_overrides ORDER BY ingredient_name"
                )
                override_rows = cursor.fetchall()

                for row in override_rows:
                    override_data = {
                        "name": row["ingredient_name"]
                    }
                    if row["override_severity"]:
                        override_data["new_severity"] = row["override_severity"]
                    if row["override_reason"]:
                        override_data["new_reason"] = row["override_reason"]
                    if row["additional_aliases"]:
                        override_data["add_aliases"] = json.loads(row["additional_aliases"])
                    if row["is_hidden"]:
                        override_data["hide"] = True

                    overrides.append(override_data)

            export_data = {
                "ingredients": ingredients,
                "overrides": overrides,
                "export_date": __import__("datetime").datetime.now().isoformat(),
                "version": "1.0"
            }

            return {
                "success": True,
                "ingredient_count": len(ingredients),
                "override_count": len(overrides),
                "export_data": json.dumps(export_data, indent=2)
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Export failed: {str(e)}"
            }
        finally:
            conn.close()

    @mcp.tool()
    async def preview_ingredient_impact(
        ingredient_name: str = Field(description="Ingredient name to preview"),
        severity: Literal["critical", "warning", "watch"] = Field(
            description="Severity level to test"
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Preview the impact of adding or modifying an ingredient.

        Shows how many products in your purchase history would be flagged
        if you add this ingredient with the specified severity.

        Example:
            preview_ingredient_impact("maltitol", "warning")
        """
        if ctx:
            await ctx.info(f"Previewing impact of ingredient: {ingredient_name}")

        conn = get_db_connection()
        try:
            # Get recent purchase history
            cursor = conn.execute("""
                SELECT DISTINCT p.product_id, p.description, p.brand
                FROM products p
                JOIN purchase_events pe ON p.product_id = pe.product_id
                WHERE pe.event_date >= date('now', '-90 days')
                LIMIT 500
            """)
            products = cursor.fetchall()

            # Check how many would match
            matched_products = []
            pattern = __import__("re").compile(r'\b' + __import__("re").escape(ingredient_name) + r'\b', __import__("re").IGNORECASE)

            for product in products:
                text = f"{product['description']} {product['brand'] or ''}".lower()
                if pattern.search(text):
                    matched_products.append({
                        "product_id": product["product_id"],
                        "description": product["description"],
                        "brand": product["brand"]
                    })

            return {
                "success": True,
                "ingredient_name": ingredient_name,
                "severity": severity,
                "total_products_checked": len(products),
                "would_flag_count": len(matched_products),
                "percentage": round(len(matched_products) / len(products) * 100, 1) if products else 0,
                "sample_products": matched_products[:10]  # First 10 matches
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Preview failed: {str(e)}"
            }
        finally:
            conn.close()
