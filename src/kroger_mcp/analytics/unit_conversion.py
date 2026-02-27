"""
Unit conversion engine for pantry quantity tracking.

Supports standard cooking/grocery unit conversions so quantities from
recipes (e.g., "2 cups milk") can be compared against pantry stock
(e.g., "1 gallon milk").

Unit categories:
  - volume: tsp, tbsp, fl_oz, cup, pint, quart, gallon, ml, liter
  - weight: oz, lb, g, kg
  - count: each, count, piece, slice, can, package, bag, box, bunch, clove, head
  - special: pinch (volume approximation)

All conversions normalize to a base unit per category:
  - volume -> fluid ounces (fl_oz)
  - weight -> ounces (oz)
  - count  -> each (dimensionless)
"""

from typing import Optional, Tuple

# ── Volume: base unit = fluid ounce ──────────────────────────────────────────
VOLUME_TO_FL_OZ: dict[str, float] = {
    "tsp": 1 / 6,
    "teaspoon": 1 / 6,
    "teaspoons": 1 / 6,
    "tbsp": 0.5,
    "tablespoon": 0.5,
    "tablespoons": 0.5,
    "fl oz": 1.0,
    "fl_oz": 1.0,
    "fluid oz": 1.0,
    "fluid ounce": 1.0,
    "fluid ounces": 1.0,
    "oz": 1.0,           # contextually treated as fl oz when paired with liquids
    "ounce": 1.0,
    "ounces": 1.0,
    "cup": 8.0,
    "cups": 8.0,
    "c": 8.0,
    "pint": 16.0,
    "pints": 16.0,
    "pt": 16.0,
    "quart": 32.0,
    "quarts": 32.0,
    "qt": 32.0,
    "gallon": 128.0,
    "gallons": 128.0,
    "gal": 128.0,
    "ml": 0.033814,
    "milliliter": 0.033814,
    "milliliters": 0.033814,
    "l": 33.814,
    "liter": 33.814,
    "liters": 33.814,
    "litre": 33.814,
    "litres": 33.814,
}

# ── Weight: base unit = ounce ─────────────────────────────────────────────────
WEIGHT_TO_OZ: dict[str, float] = {
    "oz": 1.0,
    "ounce": 1.0,
    "ounces": 1.0,
    "lb": 16.0,
    "lbs": 16.0,
    "pound": 16.0,
    "pounds": 16.0,
    "g": 0.035274,
    "gram": 0.035274,
    "grams": 0.035274,
    "kg": 35.274,
    "kilogram": 35.274,
    "kilograms": 35.274,
}

# ── Count: base unit = 1 (each) ───────────────────────────────────────────────
COUNT_UNITS: set[str] = {
    "each", "ea",
    "count", "ct",
    "piece", "pieces",
    "slice", "slices",
    "can", "cans",
    "package", "packages", "pkg",
    "bag", "bags",
    "box", "boxes",
    "bunch", "bunches",
    "clove", "cloves",
    "head", "heads",
    "stalk", "stalks",
    "sprig", "sprigs",
    "strip", "strips",
    "sheet", "sheets",
    "roll", "rolls",
    "bottle", "bottles",
    "jar", "jars",
    "container", "containers",
    "loaf", "loaves",
    "dozen",  # = 12 each
}

# Count units with multipliers (relative to "each")
COUNT_MULTIPLIERS: dict[str, float] = {
    "dozen": 12.0,
}


def normalize_unit(unit: str) -> str:
    """Lowercase and strip whitespace from unit string."""
    return unit.strip().lower() if unit else ""


def get_unit_category(unit: str) -> Optional[str]:
    """
    Classify a unit into 'volume', 'weight', 'count', or None if unknown.

    Args:
        unit: Unit string (case-insensitive)

    Returns:
        'volume', 'weight', 'count', or None
    """
    u = normalize_unit(unit)
    if not u:
        return "count"  # unitless = count-based

    if u in VOLUME_TO_FL_OZ:
        return "volume"
    if u in WEIGHT_TO_OZ:
        return "weight"
    if u in COUNT_UNITS:
        return "count"
    return None


def to_base_unit(quantity: float, unit: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Convert a quantity to the canonical base unit for its category.

    Args:
        quantity: The amount
        unit: Unit string

    Returns:
        (converted_quantity, base_unit) or (None, None) if unit unknown.
        Base units: 'fl_oz' for volume, 'oz' for weight, 'each' for count.
    """
    u = normalize_unit(unit)

    if not u:
        # Unitless = count
        return quantity, "each"

    if u in VOLUME_TO_FL_OZ:
        return quantity * VOLUME_TO_FL_OZ[u], "fl_oz"

    if u in WEIGHT_TO_OZ:
        return quantity * WEIGHT_TO_OZ[u], "oz"

    if u in COUNT_UNITS:
        multiplier = COUNT_MULTIPLIERS.get(u, 1.0)
        return quantity * multiplier, "each"

    return None, None


def convert(
    quantity: float,
    from_unit: str,
    to_unit: str,
) -> Optional[float]:
    """
    Convert a quantity from one unit to another.

    Both units must be in the same category (volume↔volume, weight↔weight, etc.)

    Args:
        quantity: Amount to convert
        from_unit: Source unit
        to_unit: Target unit

    Returns:
        Converted quantity, or None if units are incompatible or unknown.
    """
    base_qty, base_unit = to_base_unit(quantity, from_unit)
    if base_qty is None:
        return None

    to_u = normalize_unit(to_unit)

    if base_unit == "fl_oz":
        factor = VOLUME_TO_FL_OZ.get(to_u)
        if factor is None:
            return None
        return base_qty / factor

    if base_unit == "oz":
        factor = WEIGHT_TO_OZ.get(to_u)
        if factor is None:
            return None
        return base_qty / factor

    if base_unit == "each":
        to_multiplier = COUNT_MULTIPLIERS.get(to_u, 1.0) if to_u in COUNT_UNITS else None
        if to_multiplier is None and to_u not in COUNT_UNITS and to_u != "":
            return None
        # "each" to any count unit
        return base_qty / (to_multiplier or 1.0)

    return None


def can_compare(unit_a: str, unit_b: str) -> bool:
    """
    Check whether two units can be compared/converted.

    Args:
        unit_a: First unit
        unit_b: Second unit

    Returns:
        True if units are in the same measurement category.
    """
    cat_a = get_unit_category(unit_a)
    cat_b = get_unit_category(unit_b)
    if cat_a is None or cat_b is None:
        return False
    return cat_a == cat_b


def subtract_quantity(
    stock_qty: float,
    stock_unit: str,
    use_qty: float,
    use_unit: str,
) -> Tuple[Optional[float], Optional[str]]:
    """
    Subtract a used amount from stock, handling unit conversion.

    For example: stock=1 gallon, use=2 cups → returns (0.875, 'gallon')

    Args:
        stock_qty: Current stock amount
        stock_unit: Unit of current stock
        use_qty: Amount being consumed
        use_unit: Unit of consumed amount

    Returns:
        (remaining_quantity, stock_unit) after subtraction,
        or (None, None) if units are incompatible.
        Remaining quantity is clamped to 0 (never negative).
    """
    s_unit = normalize_unit(stock_unit)
    u_unit = normalize_unit(use_unit)

    # Same unit - direct subtraction
    if s_unit == u_unit:
        return max(0.0, stock_qty - use_qty), stock_unit

    # Different units - convert use_qty to stock_unit
    converted = convert(use_qty, use_unit, stock_unit)
    if converted is None:
        return None, None

    return max(0.0, stock_qty - converted), stock_unit


def quantity_to_percent(
    current_qty: float,
    reference_qty: float,
) -> int:
    """
    Express current quantity as a percentage of a reference quantity.

    Used to compute level_percent from actual quantities.

    Args:
        current_qty: Current stock amount (base units)
        reference_qty: Reference "full" amount (e.g., one purchase unit)

    Returns:
        Clamped integer 0-100
    """
    if not reference_qty or reference_qty <= 0:
        return 100
    pct = (current_qty / reference_qty) * 100
    return max(0, min(100, round(pct)))


def format_quantity(quantity: float, unit: str) -> str:
    """
    Format a quantity for human-readable display.

    Examples:
        1.0, "gallon"  -> "1 gallon"
        0.5, "gallon"  -> "0.5 gallons"
        12.0, "each"   -> "12"
        2.5, "cup"     -> "2.5 cups"

    Args:
        quantity: Amount
        unit: Unit string

    Returns:
        Formatted string
    """
    u = normalize_unit(unit)
    qty_str = f"{quantity:.2f}".rstrip("0").rstrip(".")

    if not u or u == "each":
        return qty_str

    # Pluralize simple units when quantity != 1
    needs_plural = quantity != 1.0 and not u.endswith("s")
    display_unit = (u + "s") if needs_plural else u

    return f"{qty_str} {display_unit}"


def infer_unit_from_description(description: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Try to infer quantity and unit from a product description string.

    Parses patterns like:
      "Whole Milk, 1 Gallon"    -> (1.0, 'gallon')
      "Eggs, 12 Count"          -> (12.0, 'count')
      "Butter, 16 oz"           -> (16.0, 'oz')
      "Chicken Breast, 2.5 lbs" -> (2.5, 'lbs')

    Args:
        description: Product description

    Returns:
        (quantity, unit) tuple or (None, None) if not detectable
    """
    import re

    desc_lower = description.lower()

    # Pattern: number followed by unit
    pattern = r'(\d+(?:\.\d+)?)\s*(gallon|gal|gallon|oz|ounce|lb|lbs|pound|kg|gram|g|count|ct|each|liter|l|ml|fl oz|cup|pint|quart)s?\b'
    matches = re.findall(pattern, desc_lower)

    if matches:
        qty_str, unit_str = matches[-1]  # Use last match (usually size descriptor)
        try:
            return float(qty_str), unit_str
        except ValueError:
            pass

    return None, None
