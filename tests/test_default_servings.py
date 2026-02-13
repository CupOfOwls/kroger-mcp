"""
Unit tests for default servings preference functionality.
"""

import pytest
import os
import json
from src.kroger_mcp.tools.shared import (
    get_default_servings,
    set_default_servings,
    PREFERENCES_FILE
)


@pytest.fixture(autouse=True)
def cleanup_preferences():
    """Clean up preferences file before and after each test."""
    if os.path.exists(PREFERENCES_FILE):
        os.remove(PREFERENCES_FILE)
    yield
    if os.path.exists(PREFERENCES_FILE):
        os.remove(PREFERENCES_FILE)


def test_get_default_servings_returns_4_by_default():
    """Test that default servings is 4 if not set."""
    servings = get_default_servings()
    assert servings == 4


def test_set_and_get_default_servings():
    """Test setting and retrieving default servings."""
    set_default_servings(2)
    assert get_default_servings() == 2

    set_default_servings(6)
    assert get_default_servings() == 6

    set_default_servings(1)
    assert get_default_servings() == 1


def test_set_default_servings_validation():
    """Test servings validation (must be 1-20)."""
    with pytest.raises(ValueError, match="Servings must be between 1 and 20"):
        set_default_servings(0)  # Too low

    with pytest.raises(ValueError, match="Servings must be between 1 and 20"):
        set_default_servings(21)  # Too high

    # Edge cases should work
    set_default_servings(1)  # Min
    assert get_default_servings() == 1

    set_default_servings(20)  # Max
    assert get_default_servings() == 20


def test_default_servings_persists():
    """Test that default servings persists across function calls."""
    set_default_servings(3)

    # Read from file to verify persistence
    with open(PREFERENCES_FILE, 'r') as f:
        data = json.load(f)

    assert data.get("default_servings_per_meal") == 3

    # Get should return persisted value
    assert get_default_servings() == 3


def test_default_servings_does_not_affect_other_preferences():
    """Test that setting default servings doesn't overwrite other prefs."""
    # Set a different preference first
    with open(PREFERENCES_FILE, 'w') as f:
        json.dump({"preferred_location_id": "12345"}, f)

    # Set default servings
    set_default_servings(2)

    # Both should be present
    with open(PREFERENCES_FILE, 'r') as f:
        data = json.load(f)

    assert data.get("default_servings_per_meal") == 2
    assert data.get("preferred_location_id") == "12345"
