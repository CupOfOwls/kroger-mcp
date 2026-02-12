"""
Integration tests for dynamic ingredient management.

Tests end-to-end workflows including:
- Adding custom ingredients and seeing them flag products
- Overriding system ingredients and seeing severity changes
- Hiding ingredients and seeing warnings disappear
"""

import pytest
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kroger_mcp.analytics.database import get_db_connection, initialize_database
from kroger_mcp.analytics.ingredients import (
    get_active_ingredients,
    get_compiled_patterns,
    check_product_safety,
)


@pytest.fixture
def clean_db():
    """Initialize database and clean ingredient tables"""
    initialize_database()
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM custom_ingredients")
        conn.execute("DELETE FROM ingredient_overrides")
        conn.commit()

        # Force pattern cache refresh
        get_compiled_patterns(force_refresh=True)
    finally:
        conn.close()
    yield


class TestIngredientWorkflows:
    """Test complete workflows"""

    def test_add_custom_ingredient_flags_product(self, clean_db):
        """
        Workflow: Add custom ingredient → scan product → verify flagged
        """
        # Step 1: Product doesn't flag initially
        result1 = check_product_safety(
            description="Sugar-free gum with sorbitol",
            force_refresh_patterns=True
        )
        assert not result1.has_concerns or not any(
            m.ingredient_name == "sorbitol" for m in result1.matches
        )

        # Step 2: Add sorbitol as custom ingredient
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO custom_ingredients
                    (ingredient_name, severity, category, reason, aliases)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("sorbitol", "warning", "sugar_alcohol",
                 "Digestive issues in sensitive individuals",
                 json.dumps(["E420"]))
            )
            conn.commit()
        finally:
            conn.close()

        # Step 3: Scan same product again - should now flag
        result2 = check_product_safety(
            description="Sugar-free gum with sorbitol",
            force_refresh_patterns=True
        )

        assert result2.has_concerns
        assert result2.highest_severity.value == "warning"
        sorbitol_match = next(
            (m for m in result2.matches if m.ingredient_name == "sorbitol"),
            None
        )
        assert sorbitol_match is not None
        assert sorbitol_match.reason == "Digestive issues in sensitive individuals"

    def test_override_reduces_severity(self, clean_db):
        """
        Workflow: Product flagged as CRITICAL → override to WATCH → verify reduced severity
        """
        # Step 1: Product with aspartame flags as CRITICAL
        result1 = check_product_safety(
            description="Diet soda with aspartame",
            force_refresh_patterns=True
        )

        assert result1.has_concerns
        assert result1.highest_severity.value == "critical"

        # Step 2: Override aspartame to watch
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO ingredient_overrides
                    (ingredient_name, override_severity, notes)
                VALUES (?, ?, ?)
                """,
                ("Aspartame", "watch", "I tolerate it well")
            )
            conn.commit()
        finally:
            conn.close()

        # Step 3: Scan same product - should now be WATCH
        result2 = check_product_safety(
            description="Diet soda with aspartame",
            force_refresh_patterns=True
        )

        assert result2.has_concerns
        assert result2.highest_severity.value == "watch"
        aspartame_match = next(
            (m for m in result2.matches if m.ingredient_name == "Aspartame"),
            None
        )
        assert aspartame_match is not None
        assert aspartame_match.severity.value == "watch"

    def test_hide_ingredient_removes_warning(self, clean_db):
        """
        Workflow: Product flagged → hide ingredient → verify no longer flagged
        """
        # Step 1: Product with red 40 flags
        result1 = check_product_safety(
            description="Candy with red 40 dye",
            force_refresh_patterns=True
        )

        assert result1.has_concerns
        red40_match = next(
            (m for m in result1.matches if "red 40" in m.ingredient_name.lower()),
            None
        )
        assert red40_match is not None

        # Step 2: Hide Red 40
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO ingredient_overrides
                    (ingredient_name, is_hidden)
                VALUES (?, ?)
                """,
                ("Red 40 (Allura Red)", 1)
            )
            conn.commit()
        finally:
            conn.close()

        # Step 3: Scan same product - Red 40 should not flag
        result2 = check_product_safety(
            description="Candy with red 40 dye",
            force_refresh_patterns=True
        )

        # Red 40 should not be in matches
        red40_match2 = next(
            (m for m in result2.matches if "red 40" in m.ingredient_name.lower()),
            None
        )
        assert red40_match2 is None

    def test_import_export_roundtrip(self, clean_db):
        """
        Workflow: Add ingredients → export → delete → import → verify restored
        """
        conn = get_db_connection()

        # Step 1: Add custom ingredients
        try:
            conn.execute(
                """
                INSERT INTO custom_ingredients
                    (ingredient_name, severity, category, aliases)
                VALUES (?, ?, ?, ?)
                """,
                ("maltitol", "warning", "sugar_alcohol", json.dumps(["E965"]))
            )
            conn.execute(
                """
                INSERT INTO custom_ingredients
                    (ingredient_name, severity, category, aliases)
                VALUES (?, ?, ?, ?)
                """,
                ("sorbitol", "watch", "sugar_alcohol", json.dumps(["E420"]))
            )
            conn.commit()
        finally:
            conn.close()

        # Step 2: Export
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE is_active = 1"
            )
            rows = cursor.fetchall()

            export_data = {
                "ingredients": [
                    {
                        "name": row["ingredient_name"],
                        "severity": row["severity"],
                        "category": row["category"],
                        "aliases": json.loads(row["aliases"]) if row["aliases"] else []
                    }
                    for row in rows
                ]
            }
        finally:
            conn.close()

        assert len(export_data["ingredients"]) == 2

        # Step 3: Delete all custom ingredients
        conn = get_db_connection()
        try:
            conn.execute("DELETE FROM custom_ingredients")
            conn.commit()
        finally:
            conn.close()

        # Verify deleted
        ingredients = get_active_ingredients(include_custom=True)
        custom_count = len([i for i in ingredients if i["source"] == "custom"])
        assert custom_count == 0

        # Step 4: Import
        conn = get_db_connection()
        try:
            for ing in export_data["ingredients"]:
                conn.execute(
                    """
                    INSERT INTO custom_ingredients
                        (ingredient_name, severity, category, aliases, source)
                    VALUES (?, ?, ?, ?, 'imported')
                    """,
                    (ing["name"], ing["severity"], ing["category"],
                     json.dumps(ing["aliases"]))
                )
            conn.commit()
        finally:
            conn.close()

        # Step 5: Verify restored
        ingredients = get_active_ingredients(include_custom=True)
        custom_ings = [i for i in ingredients if i["source"] == "custom"]
        assert len(custom_ings) == 2

        names = {i["name"] for i in custom_ings}
        assert "maltitol" in names
        assert "sorbitol" in names

    def test_multiple_custom_ingredients_compound_severity(self, clean_db):
        """
        Workflow: Add multiple custom ingredients → product with both → verify both flagged
        """
        conn = get_db_connection()

        # Add two custom ingredients
        try:
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity, category) VALUES (?, ?, ?)",
                ("maltitol", "warning", "sugar_alcohol")
            )
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity, category) VALUES (?, ?, ?)",
                ("sorbitol", "watch", "sugar_alcohol")
            )
            conn.commit()
        finally:
            conn.close()

        # Product with both
        result = check_product_safety(
            description="Sugar-free candy with maltitol and sorbitol",
            force_refresh_patterns=True
        )

        assert result.has_concerns
        assert len(result.matches) == 2
        assert result.highest_severity.value == "warning"  # Higher of the two

        ingredient_names = {m.ingredient_name for m in result.matches}
        assert "maltitol" in ingredient_names
        assert "sorbitol" in ingredient_names

    def test_alias_matching_works(self, clean_db):
        """
        Workflow: Add ingredient with alias → product uses alias → verify detected
        """
        conn = get_db_connection()

        # Add ingredient with E-number alias
        try:
            conn.execute(
                """
                INSERT INTO custom_ingredients
                    (ingredient_name, severity, aliases)
                VALUES (?, ?, ?)
                """,
                ("maltitol", "warning", json.dumps(["E965", "hydrogenated glucose syrup"]))
            )
            conn.commit()
        finally:
            conn.close()

        # Product uses E-number
        result = check_product_safety(
            description="Sugar-free gum with E965",
            force_refresh_patterns=True
        )

        assert result.has_concerns
        match = next(
            (m for m in result.matches if m.ingredient_name == "maltitol"),
            None
        )
        assert match is not None
        assert match.matched_text.lower() == "e965"


def test_system_ingredient_count_unchanged(clean_db):
    """Verify system still has 62 default ingredients"""
    ingredients = get_active_ingredients(include_custom=False)
    system_count = len([i for i in ingredients if i["source"] == "system"])
    assert system_count == 62


def test_pattern_cache_invalidates_correctly(clean_db):
    """Verify pattern cache is refreshed when ingredients change"""
    # Get initial cache
    cache1 = get_compiled_patterns(force_refresh=True)
    count1 = cache1["ingredient_count"]
    timestamp1 = cache1["timestamp"]

    # Add ingredient
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO custom_ingredients (ingredient_name, severity) VALUES (?, ?)",
            ("test_ingredient", "watch")
        )
        conn.commit()
    finally:
        conn.close()

    # Force refresh
    cache2 = get_compiled_patterns(force_refresh=True)
    count2 = cache2["ingredient_count"]
    timestamp2 = cache2["timestamp"]

    assert count2 == count1 + 1
    assert timestamp2 > timestamp1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
