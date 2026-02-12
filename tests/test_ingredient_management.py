"""
Tests for dynamic ingredient management system.
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
    finally:
        conn.close()
    yield
    # Cleanup
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM custom_ingredients")
        conn.execute("DELETE FROM ingredient_overrides")
        conn.commit()
    finally:
        conn.close()


class TestCustomIngredients:
    """Test custom ingredient management"""

    def test_add_custom_ingredient(self, clean_db):
        """Test adding a custom ingredient"""
        conn = get_db_connection()
        try:
            cursor = conn.execute(
                """
                INSERT INTO custom_ingredients
                    (ingredient_name, severity, category, reason, aliases)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("maltitol", "warning", "sugar_alcohol", "Digestive distress", json.dumps(["E965"]))
            )
            conn.commit()

            # Verify it was added
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE ingredient_name = ?",
                ("maltitol",)
            )
            row = cursor.fetchone()

            assert row is not None
            assert row["ingredient_name"] == "maltitol"
            assert row["severity"] == "warning"
            assert row["category"] == "sugar_alcohol"
            assert row["is_active"] == 1

        finally:
            conn.close()

    def test_duplicate_ingredient_prevented(self, clean_db):
        """Test that duplicate ingredients are prevented"""
        conn = get_db_connection()
        try:
            # Add first ingredient
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity) VALUES (?, ?)",
                ("maltitol", "warning")
            )
            conn.commit()

            # Try to add duplicate
            with pytest.raises(Exception):  # Should raise UNIQUE constraint error
                conn.execute(
                    "INSERT INTO custom_ingredients (ingredient_name, severity) VALUES (?, ?)",
                    ("maltitol", "warning")
                )
                conn.commit()

        finally:
            conn.close()

    def test_edit_custom_ingredient(self, clean_db):
        """Test editing a custom ingredient"""
        conn = get_db_connection()
        try:
            # Add ingredient
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity, aliases) VALUES (?, ?, ?)",
                ("maltitol", "warning", json.dumps(["E965"]))
            )
            conn.commit()

            # Edit it
            conn.execute(
                "UPDATE custom_ingredients SET severity = ?, aliases = ? WHERE ingredient_name = ?",
                ("critical", json.dumps(["E965", "maltitol syrup"]), "maltitol")
            )
            conn.commit()

            # Verify changes
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE ingredient_name = ?",
                ("maltitol",)
            )
            row = cursor.fetchone()

            assert row["severity"] == "critical"
            aliases = json.loads(row["aliases"])
            assert "maltitol syrup" in aliases

        finally:
            conn.close()

    def test_remove_custom_ingredient_soft(self, clean_db):
        """Test soft delete of custom ingredient"""
        conn = get_db_connection()
        try:
            # Add ingredient
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity) VALUES (?, ?)",
                ("maltitol", "warning")
            )
            conn.commit()

            # Soft delete
            conn.execute(
                "UPDATE custom_ingredients SET is_active = 0 WHERE ingredient_name = ?",
                ("maltitol",)
            )
            conn.commit()

            # Verify it still exists but inactive
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE ingredient_name = ?",
                ("maltitol",)
            )
            row = cursor.fetchone()

            assert row is not None
            assert row["is_active"] == 0

        finally:
            conn.close()

    def test_remove_custom_ingredient_hard(self, clean_db):
        """Test permanent deletion of custom ingredient"""
        conn = get_db_connection()
        try:
            # Add ingredient
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity) VALUES (?, ?)",
                ("maltitol", "warning")
            )
            conn.commit()

            # Hard delete
            conn.execute(
                "DELETE FROM custom_ingredients WHERE ingredient_name = ?",
                ("maltitol",)
            )
            conn.commit()

            # Verify it's gone
            cursor = conn.execute(
                "SELECT * FROM custom_ingredients WHERE ingredient_name = ?",
                ("maltitol",)
            )
            row = cursor.fetchone()

            assert row is None

        finally:
            conn.close()


class TestIngredientOverrides:
    """Test system ingredient overrides"""

    def test_override_system_ingredient_severity(self, clean_db):
        """Test overriding severity of system ingredient"""
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO ingredient_overrides
                    (ingredient_name, override_severity)
                VALUES (?, ?)
                """,
                ("Aspartame", "watch")
            )
            conn.commit()

            # Verify override
            cursor = conn.execute(
                "SELECT * FROM ingredient_overrides WHERE ingredient_name = ?",
                ("Aspartame",)
            )
            row = cursor.fetchone()

            assert row is not None
            assert row["override_severity"] == "watch"

        finally:
            conn.close()

    def test_hide_system_ingredient(self, clean_db):
        """Test hiding a system ingredient"""
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO ingredient_overrides
                    (ingredient_name, is_hidden)
                VALUES (?, ?)
                """,
                ("Aspartame", 1)
            )
            conn.commit()

            # Verify it's hidden
            cursor = conn.execute(
                "SELECT * FROM ingredient_overrides WHERE ingredient_name = ?",
                ("Aspartame",)
            )
            row = cursor.fetchone()

            assert row["is_hidden"] == 1

        finally:
            conn.close()

    def test_reset_ingredient_to_default(self, clean_db):
        """Test resetting ingredient to defaults"""
        conn = get_db_connection()
        try:
            # Add override
            conn.execute(
                "INSERT INTO ingredient_overrides (ingredient_name, override_severity) VALUES (?, ?)",
                ("Aspartame", "watch")
            )
            conn.commit()

            # Reset (delete override)
            conn.execute(
                "DELETE FROM ingredient_overrides WHERE ingredient_name = ?",
                ("Aspartame",)
            )
            conn.commit()

            # Verify it's gone
            cursor = conn.execute(
                "SELECT * FROM ingredient_overrides WHERE ingredient_name = ?",
                ("Aspartame",)
            )
            row = cursor.fetchone()

            assert row is None

        finally:
            conn.close()


class TestGetActiveIngredients:
    """Test unified ingredient list retrieval"""

    def test_get_active_ingredients_system_only(self, clean_db):
        """Test getting only system ingredients"""
        ingredients = get_active_ingredients(include_custom=False)

        # Should have all 62 default ingredients
        assert len(ingredients) == 62
        assert all(ing["source"] == "system" for ing in ingredients)

    def test_get_active_ingredients_with_custom(self, clean_db):
        """Test getting system + custom ingredients"""
        # Add a custom ingredient
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity, category) VALUES (?, ?, ?)",
                ("maltitol", "warning", "sugar_alcohol")
            )
            conn.commit()
        finally:
            conn.close()

        ingredients = get_active_ingredients(include_custom=True)

        # Should have 62 system + 1 custom
        assert len(ingredients) == 63
        custom_ings = [ing for ing in ingredients if ing["source"] == "custom"]
        assert len(custom_ings) == 1
        assert custom_ings[0]["name"] == "maltitol"

    def test_get_active_ingredients_with_override(self, clean_db):
        """Test that overrides are applied"""
        # Add override
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO ingredient_overrides (ingredient_name, override_severity) VALUES (?, ?)",
                ("Aspartame", "watch")
            )
            conn.commit()
        finally:
            conn.close()

        ingredients = get_active_ingredients(include_custom=False)

        # Find aspartame
        aspartame = next((ing for ing in ingredients if ing["name"] == "Aspartame"), None)
        assert aspartame is not None
        assert aspartame["severity"] == "watch"  # Should be overridden from critical

    def test_get_active_ingredients_with_hidden(self, clean_db):
        """Test that hidden ingredients are excluded"""
        # Hide an ingredient
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO ingredient_overrides (ingredient_name, is_hidden) VALUES (?, ?)",
                ("Aspartame", 1)
            )
            conn.commit()
        finally:
            conn.close()

        ingredients = get_active_ingredients(include_custom=False)

        # Aspartame should not be in the list
        aspartame = next((ing for ing in ingredients if ing["name"] == "Aspartame"), None)
        assert aspartame is None

        # Should have 61 instead of 62
        assert len(ingredients) == 61


class TestPatternCompilation:
    """Test pattern compilation and caching"""

    def test_get_compiled_patterns(self, clean_db):
        """Test pattern compilation"""
        pattern_data = get_compiled_patterns(force_refresh=True)

        assert "patterns" in pattern_data
        assert "timestamp" in pattern_data
        assert "ingredient_count" in pattern_data
        assert pattern_data["ingredient_count"] == 62  # Default count

    def test_pattern_cache_refresh(self, clean_db):
        """Test that adding ingredient refreshes cache"""
        # Get initial patterns
        pattern_data1 = get_compiled_patterns(force_refresh=True)
        count1 = pattern_data1["ingredient_count"]

        # Add custom ingredient
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity) VALUES (?, ?)",
                ("maltitol", "warning")
            )
            conn.commit()
        finally:
            conn.close()

        # Force refresh
        pattern_data2 = get_compiled_patterns(force_refresh=True)
        count2 = pattern_data2["ingredient_count"]

        assert count2 == count1 + 1


class TestProductSafetyWithCustomIngredients:
    """Test end-to-end product safety checking with custom ingredients"""

    def test_check_product_with_custom_ingredient(self, clean_db):
        """Test that custom ingredients are detected in products"""
        # Add custom ingredient
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity, aliases) VALUES (?, ?, ?)",
                ("maltitol", "warning", json.dumps(["E965"]))
            )
            conn.commit()
        finally:
            conn.close()

        # Test product with maltitol
        result = check_product_safety(
            description="Sugar-free candy with maltitol",
            force_refresh_patterns=True
        )

        assert result.has_concerns
        assert result.highest_severity.value == "warning"
        assert any(m.ingredient_name == "maltitol" for m in result.matches)

    def test_check_product_with_override(self, clean_db):
        """Test that overridden severity is used"""
        # Override aspartame to watch
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO ingredient_overrides (ingredient_name, override_severity) VALUES (?, ?)",
                ("Aspartame", "watch")
            )
            conn.commit()
        finally:
            conn.close()

        # Test product with aspartame
        result = check_product_safety(
            description="Diet soda with aspartame",
            force_refresh_patterns=True
        )

        assert result.has_concerns
        # Should be watch, not critical
        assert result.highest_severity.value == "watch"

    def test_check_product_with_hidden_ingredient(self, clean_db):
        """Test that hidden ingredients don't flag products"""
        # Hide aspartame
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO ingredient_overrides (ingredient_name, is_hidden) VALUES (?, ?)",
                ("Aspartame", 1)
            )
            conn.commit()
        finally:
            conn.close()

        # Test product with aspartame
        result = check_product_safety(
            description="Diet soda with aspartame",
            force_refresh_patterns=True
        )

        # Should not flag aspartame
        assert not result.has_concerns


class TestImportExport:
    """Test import/export functionality"""

    def test_export_format(self, clean_db):
        """Test export produces valid JSON"""
        # Add some test data
        conn = get_db_connection()
        try:
            conn.execute(
                "INSERT INTO custom_ingredients (ingredient_name, severity, category) VALUES (?, ?, ?)",
                ("maltitol", "warning", "sugar_alcohol")
            )
            conn.execute(
                "INSERT INTO ingredient_overrides (ingredient_name, override_severity) VALUES (?, ?)",
                ("Aspartame", "watch")
            )
            conn.commit()

            # Export would be done by tool, but we can test the data structure
            cursor = conn.execute("SELECT * FROM custom_ingredients WHERE is_active = 1")
            custom_rows = cursor.fetchall()

            export_data = {
                "ingredients": [
                    {
                        "name": row["ingredient_name"],
                        "severity": row["severity"],
                        "category": row["category"]
                    }
                    for row in custom_rows
                ]
            }

            # Should be valid JSON
            json_str = json.dumps(export_data)
            parsed = json.loads(json_str)
            assert len(parsed["ingredients"]) == 1
            assert parsed["ingredients"][0]["name"] == "maltitol"

        finally:
            conn.close()


def test_database_indexes_exist():
    """Test that performance indexes were created"""
    conn = get_db_connection()
    try:
        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE 'idx_custom_ingredients%'
        """)
        indexes = [row[0] for row in cursor.fetchall()]

        assert "idx_custom_ingredients_name" in indexes
        assert "idx_custom_ingredients_severity" in indexes
        assert "idx_custom_ingredients_active" in indexes

        cursor = conn.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE 'idx_ingredient_overrides%'
        """)
        indexes = [row[0] for row in cursor.fetchall()]

        assert "idx_ingredient_overrides_name" in indexes
        assert "idx_ingredient_overrides_hidden" in indexes

    finally:
        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
