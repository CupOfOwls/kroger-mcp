"""
Unit tests for shopping list functionality.
"""

import pytest
import os
import json
from src.kroger_mcp.tools.shopping_list_tools import (
    _load_shopping_list,
    _save_shopping_list,
    _consolidate_items,
    _generate_list_item_id,
    SHOPPING_LIST_FILE
)


@pytest.fixture(autouse=True)
def cleanup_shopping_list():
    """Clean up shopping list file before and after each test."""
    if os.path.exists(SHOPPING_LIST_FILE):
        os.remove(SHOPPING_LIST_FILE)
    yield
    if os.path.exists(SHOPPING_LIST_FILE):
        os.remove(SHOPPING_LIST_FILE)


def test_load_empty_shopping_list():
    """Test loading when no shopping list file exists."""
    data = _load_shopping_list()
    assert data == {"items": [], "last_updated": None}


def test_save_and_load_shopping_list():
    """Test saving and loading shopping list."""
    data = {
        "items": [
            {
                "id": "list_item_001",
                "product_id": "12345",
                "ingredient_name": "Eggs",
                "quantity": 2
            }
        ]
    }

    _save_shopping_list(data)

    loaded = _load_shopping_list()
    assert len(loaded["items"]) == 1
    assert loaded["items"][0]["ingredient_name"] == "Eggs"
    assert "last_updated" in loaded


def test_generate_list_item_id():
    """Test that generated IDs are unique."""
    id1 = _generate_list_item_id()
    id2 = _generate_list_item_id()

    assert id1 != id2
    assert id1.startswith("list_item_")
    assert id2.startswith("list_item_")


def test_consolidate_items_with_same_product():
    """Test consolidating items with the same product_id."""
    items = [
        {
            "id": "item1",
            "product_id": "12345",
            "ingredient_name": "Eggs",
            "quantity": 2,
            "sources": [{"recipe_id": "recipe1"}]
        },
        {
            "id": "item2",
            "product_id": "12345",
            "ingredient_name": "Eggs",
            "quantity": 4,
            "sources": [{"recipe_id": "recipe2"}]
        }
    ]

    consolidated = _consolidate_items(items)

    assert len(consolidated) == 1
    assert consolidated[0]["quantity"] == 6  # 2 + 4
    assert len(consolidated[0]["sources"]) == 2


def test_consolidate_items_with_different_products():
    """Test that items with different product_ids stay separate."""
    items = [
        {
            "id": "item1",
            "product_id": "12345",
            "ingredient_name": "Eggs",
            "quantity": 2
        },
        {
            "id": "item2",
            "product_id": "67890",
            "ingredient_name": "Milk",
            "quantity": 1
        }
    ]

    consolidated = _consolidate_items(items)

    assert len(consolidated) == 2


def test_consolidate_items_without_product_id():
    """Test that items without product_id stay separate."""
    items = [
        {
            "id": "item1",
            "ingredient_name": "Eggs",
            "quantity": 2
        },
        {
            "id": "item2",
            "ingredient_name": "Milk",
            "quantity": 1
        }
    ]

    consolidated = _consolidate_items(items)

    # Items without product_id should not be consolidated
    assert len(consolidated) == 2


def test_consolidate_preserves_latest_timestamp():
    """Test that consolidation updates timestamp."""
    items = [
        {
            "id": "item1",
            "product_id": "12345",
            "quantity": 2,
            "last_updated": "2024-01-01T10:00:00"
        },
        {
            "id": "item2",
            "product_id": "12345",
            "quantity": 3,
            "last_updated": "2024-01-01T11:00:00"
        }
    ]

    consolidated = _consolidate_items(items)

    assert len(consolidated) == 1
    assert "last_updated" in consolidated[0]
    # Should have a new timestamp from consolidation
