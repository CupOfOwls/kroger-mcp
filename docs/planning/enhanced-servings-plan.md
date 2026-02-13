# Enhanced Implementation Plan: Default Servings + Shopping List Workflow

## Overview

This plan implements:
1. **Default servings preference** - User sets household size (e.g., "I cook for 2")
2. **Auto-scaling recipes** - Recipes automatically scale to user's default
3. **Shopping list** - Intermediate step between recipes and cart
4. **Session requirement** - Must scan pantry attention before adding to list/cart
5. **Workflow**: Pantry scan → Shopping list (auto-scaled) → Cart

## User Workflow

```
1. Set default servings: set_default_servings(2)
   → System remembers "I cook for 2 people"

2. Create/view recipes: save_recipe(...) or get_recipe(...)
   → Recipes auto-scale to 2 servings
   → Display shows: "Scaled to your household (2 servings)"

3. Scan pantry: get_pantry_attention()
   → REQUIRED before adding to shopping list or cart
   → Shows what's expiring, low, or overdue

4. Add to shopping list: add_recipe_to_shopping_list(recipe_id)
   → Auto-scaled to household default (2 servings)
   → Skips items in pantry above threshold
   → Stored for later

5. Review shopping list: get_shopping_list()
   → See all items from multiple recipes
   → Consolidated quantities
   → Servings info for each recipe

6. Add to cart: add_shopping_list_to_cart()
   → Transfers shopping list items to Kroger cart
   → Clears shopping list
   → Tracks in purchase history
```

## Critical Changes from Original Plan

### New Session Requirement
**BEFORE** adding to shopping list or cart, user MUST call `get_pantry_attention()` in the session.

This ensures:
- User reviews expiring items first
- User sees low inventory alerts
- User checks what they already have
- Prevents duplicate purchases

### Shopping List as Intermediate Storage
Shopping list stores:
- Recipe name and servings
- Individual ingredients (auto-scaled)
- Quantities (consolidated across recipes)
- Source tracking (which recipes need each item)

**Benefits:**
- Build list from multiple recipes
- Review before committing to cart
- Modify quantities before checkout
- Persistent across sessions

### Auto-Scaling Behavior
When user has default_servings = 2:
- **Create recipe without servings** → defaults to 2
- **View existing recipe (servings = 4)** → displays "Recipe: 4 servings, Your household: 2 servings"
- **Add to shopping list** → scales ingredients to 2 servings (user can override)
- **Meal planning** → assigns meals with 2 servings unless overridden

## Architecture

### 1. Data Storage

#### kroger_preferences.json
```json
{
  "preferred_location_id": "03400357",
  "default_servings_per_meal": 2,
  "prediction_config": { ... }
}
```

#### kroger_shopping_list.json (NEW)
```json
{
  "items": [
    {
      "id": "list_item_abc123",
      "product_id": "0001111041700",
      "ingredient_name": "Eggs",
      "quantity": 4,
      "unit": "large",
      "sources": [
        {
          "recipe_id": "recipe_xyz",
          "recipe_name": "Pasta Carbonara",
          "servings_used": 2,
          "original_quantity": 4
        }
      ],
      "added_at": "2024-01-15T10:30:00",
      "notes": null
    }
  ],
  "last_updated": "2024-01-15T10:30:00"
}
```

### 2. New Tools

#### Shopping List Management

```python
@mcp.tool()
async def add_recipe_to_shopping_list(
    recipe_id: str,
    servings: Optional[int] = None,  # Override household default
    skip_items: List[str] = [],
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Add recipe ingredients to shopping list (auto-scaled to household default).

    PREREQUISITE: Must call get_pantry_attention() first in this session.

    Args:
        recipe_id: Recipe to add
        servings: Override household default (None = use default)
        skip_items: Ingredient names to skip

    Returns:
        Items added to shopping list with auto-scaling info
    """
```

```python
@mcp.tool()
async def get_shopping_list(
    ctx: Context = None
) -> Dict[str, Any]:
    """
    View current shopping list with consolidated quantities.

    Returns:
        - items: List items with quantities and sources
        - total_items: Count
        - recipes_included: Which recipes contributed
        - servings_summary: Servings for each recipe
    """
```

```python
@mcp.tool()
async def remove_from_shopping_list(
    item_id: Optional[str] = None,  # Single mode
    item_ids: Optional[List[str]] = None,  # Batch mode
    clear_all: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Remove items from shopping list.
    """
```

```python
@mcp.tool()
async def update_shopping_list_item(
    item_id: str,
    quantity: Optional[int] = None,
    notes: Optional[str] = None,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Update quantity or notes for a shopping list item.
    """
```

```python
@mcp.tool()
async def add_shopping_list_to_cart(
    modality: str = "PICKUP",
    confirm: bool = False,
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Transfer shopping list items to Kroger cart.

    PREREQUISITE: Must call get_pantry_attention() first in this session.

    WORKFLOW (2-step):
    Step 1: Call with confirm=False (preview)
        - Shows what will be added to cart
        - Cross-references with pantry
        - DOES NOT modify cart or shopping list

    Step 2: Call with confirm=True after user approval
        - Adds items to Kroger cart
        - Clears shopping list
        - Returns summary

    Args:
        modality: PICKUP or DELIVERY
        confirm: False=preview, True=execute

    Returns:
        Preview or execution summary
    """
```

#### Servings Management

```python
@mcp.tool()
async def get_default_servings(
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Get your default servings per meal preference (household size).
    """
```

```python
@mcp.tool()
async def set_default_servings(
    servings: int = Field(..., ge=1, le=20),
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Set your default servings per meal (household size).

    This affects:
    - New recipes (default servings)
    - Shopping list scaling
    - Meal plan assignments
    """
```

### 3. Modified Tools

#### recipe_tools.py Updates

```python
@mcp.tool()
async def save_recipe(
    name: str,
    ingredients: List[Dict[str, Any]],
    servings: Optional[int] = None,  # NOW OPTIONAL - uses default
    ...
) -> Dict[str, Any]:
    """
    Save a recipe.

    If servings is None, uses your default_servings_per_meal preference.
    """
    # Implementation:
    if servings is None:
        from .shared import get_default_servings
        servings = get_default_servings()
        using_default = True
    else:
        using_default = False

    # Return includes:
    # - "servings": actual_servings
    # - "using_default_servings": bool
    # - "household_default": get_default_servings()
```

```python
@mcp.tool()
async def get_recipe(
    recipe_id: str,
    scale_to_household: bool = False,  # NEW PARAMETER
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Get recipe details.

    Args:
        recipe_id: Recipe to retrieve
        scale_to_household: If True, auto-scale to default servings

    Returns:
        Recipe with servings info and optional scaled quantities
    """
    # Implementation includes:
    # - "recipe": recipe data
    # - "household_default_servings": get_default_servings()
    # - "servings_match": bool (recipe servings == household default)
    # - If scale_to_household=True:
    #     - "scaled_ingredients": ingredients scaled to household default
    #     - "scale_factor": factor used
```

#### meal_planner_tools.py Updates

```python
@mcp.tool()
async def assign_meal(
    plan_id: str,
    recipe_id: str,
    date: str,
    slot: str,
    servings_override: Optional[int] = None,  # NOW uses household default
    ctx: Context = None
) -> Dict[str, Any]:
    """
    Assign recipe to meal slot.

    If servings_override is None, uses default_servings_per_meal.
    """
    # Implementation:
    if servings_override is None:
        from .shared import get_default_servings
        servings_override = get_default_servings()
        servings_source = "household_default"
    else:
        servings_source = "explicit_override"

    # Return includes:
    # - "servings": actual servings used
    # - "servings_source": "household_default" | "explicit_override"
```

### 4. Session Requirement Enforcement

#### Pattern (from cart_tools.py)

```python
from ..session_state import get_session_manager

def _check_attention_requirement(ctx: Context) -> Optional[Dict[str, Any]]:
    """
    Check if get_pantry_attention was called this session.

    Returns error dict if not called, None if requirement met.
    """
    session_id = _get_session_id(ctx)
    session_manager = get_session_manager()

    if not session_manager.was_tool_called(session_id, "get_pantry_attention"):
        return {
            "success": False,
            "error": "Session requirement not met",
            "error_code": "ATTENTION_REQUIRED",
            "message": (
                "You must call get_pantry_attention() before adding to shopping list. "
                "This ensures you review expiring items, low inventory, and what you "
                "already have before building your shopping list."
            ),
            "required_action": "Call get_pantry_attention() first"
        }

    return None  # Requirement met
```

#### Tools that require attention check:
1. `add_recipe_to_shopping_list()` - NEW
2. `add_shopping_list_to_cart()` - NEW
3. `add_to_cart()` - EXISTING (already has requirement)

#### Mark attention called in prediction_tools.py:

```python
@mcp.tool()
async def get_pantry_attention(...):
    """..."""
    from ..session_state import get_session_manager

    session_id = _get_session_id(ctx)
    session_manager = get_session_manager()

    # Mark that attention was called this session
    session_manager.mark_tool_called(session_id, "get_pantry_attention")

    # ... rest of implementation
```

## Implementation Steps

### Phase 1: Default Servings Preference (Foundation)

**Files to modify:**
1. `src/kroger_mcp/tools/shared.py`
   - Add `get_default_servings()` → returns 4 by default
   - Add `set_default_servings(servings)` → validates 1-20, saves to prefs

2. `src/kroger_mcp/tools/utility_tools.py`
   - Add `get_default_servings()` tool
   - Add `set_default_servings(servings)` tool
   - Update `get_user_profile()` to include default_servings

**Test:** User can set/get default servings preference

### Phase 2: Recipe Auto-Scaling

**Files to modify:**
1. `src/kroger_mcp/tools/recipe_tools.py`
   - Update `save_recipe()`: servings becomes optional, uses default
   - Update `get_recipe()`: add scale_to_household parameter
   - Update `preview_recipe_order()`: show servings info prominently
   - All responses include household_default for context

**Test:** Recipes auto-scale to household default

### Phase 3: Shopping List Data Structure

**Files to create:**
1. `src/kroger_mcp/tools/shopping_list_tools.py` (NEW)
   - `_load_shopping_list()` → reads JSON
   - `_save_shopping_list()` → writes JSON
   - `_consolidate_items()` → merges quantities from multiple recipes
   - `_generate_list_item_id()` → unique IDs

**Data file:**
- `kroger_shopping_list.json` (auto-created)

**Test:** Shopping list can store and retrieve items

### Phase 4: Shopping List Tools

**In `shopping_list_tools.py`:**
1. `add_recipe_to_shopping_list()` - with attention requirement check
2. `get_shopping_list()` - view current list
3. `remove_from_shopping_list()` - single/batch removal
4. `update_shopping_list_item()` - modify quantities
5. `add_shopping_list_to_cart()` - 2-step confirmation workflow

**Register in `server.py`:**
```python
from .tools.shopping_list_tools import register_tools as register_shopping_list_tools
register_shopping_list_tools(mcp)
```

**Test:** Can add recipes to list, view list, modify list, transfer to cart

### Phase 5: Session Requirement for Shopping List

**Files to modify:**
1. `src/kroger_mcp/tools/prediction_tools.py`
   - Update `get_pantry_attention()` to mark session

2. `src/kroger_mcp/tools/shopping_list_tools.py`
   - Add `_check_attention_requirement()` helper
   - Call check in `add_recipe_to_shopping_list()`
   - Call check in `add_shopping_list_to_cart()`

**Test:** Tools block without attention, allow after attention

### Phase 6: Meal Planner Integration

**Files to modify:**
1. `src/kroger_mcp/tools/meal_planner_tools.py`
   - Update `assign_meal()`: servings_override defaults to household
   - Update `preview_meal_plan_shopping()`: show servings info
   - Update `get_meal_plan()`: include servings for each meal

**Test:** Meal planning uses household default

### Phase 7: Server Instructions Update

**File to modify:**
1. `src/kroger_mcp/server.py`
   - Add shopping list workflow instructions
   - Add default servings preference documentation
   - Add session requirement explanation

## Testing Strategy

### Unit Tests

**tests/test_default_servings.py** (NEW)
```python
def test_get_default_servings_defaults_to_4()
def test_set_and_get_default_servings()
def test_set_default_servings_validation()
def test_recipe_uses_default_when_not_specified()
def test_meal_assignment_uses_default()
```

**tests/test_shopping_list.py** (NEW)
```python
def test_add_recipe_to_shopping_list()
def test_consolidate_quantities_from_multiple_recipes()
def test_remove_from_shopping_list()
def test_update_shopping_list_item()
def test_shopping_list_to_cart_workflow()
def test_shopping_list_blocks_without_attention()
```

**tests/test_auto_scaling.py** (NEW)
```python
def test_recipe_creation_auto_scales()
def test_recipe_display_shows_household_default()
def test_shopping_list_auto_scales_ingredients()
def test_scale_factor_calculation()
```

### Integration Tests

**Manual test workflow:**

1. **Setup:**
   ```
   set_default_servings(servings=2)
   → Verify: default_servings = 2
   ```

2. **Create auto-scaled recipe:**
   ```
   save_recipe(name="Test", ingredients=[...])  # No servings param
   → Verify: servings = 2, using_default_servings = True
   ```

3. **Session requirement:**
   ```
   add_recipe_to_shopping_list(recipe_id="...")
   → Verify: Error "ATTENTION_REQUIRED"

   get_pantry_attention()
   → Verify: Success, session marked

   add_recipe_to_shopping_list(recipe_id="...")
   → Verify: Success, items added to list
   ```

4. **Shopping list workflow:**
   ```
   add_recipe_to_shopping_list(recipe_id="recipe1")
   add_recipe_to_shopping_list(recipe_id="recipe2")
   get_shopping_list()
   → Verify: Consolidated quantities, multiple sources

   add_shopping_list_to_cart(confirm=False)
   → Verify: Preview with pantry cross-reference

   add_shopping_list_to_cart(confirm=True)
   → Verify: Items in cart, shopping list cleared
   ```

5. **Auto-scaling:**
   ```
   get_recipe(recipe_id="...", scale_to_household=True)
   → Verify: Ingredients scaled to household default
   ```

## Display Examples

### set_default_servings() Response
```json
{
  "success": true,
  "default_servings": 2,
  "previous_value": 4,
  "message": "Default servings updated from 4 to 2",
  "note": "This will affect new recipes and shopping list scaling. Existing recipes retain their servings."
}
```

### save_recipe() Response (auto-scaled)
```json
{
  "success": true,
  "recipe_id": "abc12345",
  "name": "Pasta Carbonara",
  "servings": 2,
  "using_default_servings": true,
  "household_default": 2,
  "message": "Recipe saved with 2 servings (your household default)"
}
```

### get_recipe() Response
```json
{
  "success": true,
  "recipe": {
    "id": "abc12345",
    "name": "Pasta Carbonara",
    "servings": 4,
    "ingredients": [...]
  },
  "household_default_servings": 2,
  "servings_match": false,
  "servings_note": "Recipe has 4 servings, your household default is 2",
  "suggestion": "Use scale_to_household=True to auto-scale to 2 servings"
}
```

### add_recipe_to_shopping_list() Response
```json
{
  "success": true,
  "recipe_id": "abc12345",
  "recipe_name": "Pasta Carbonara",
  "recipe_base_servings": 4,
  "servings_used": 2,
  "scale_factor": 0.5,
  "using_household_default": true,
  "items_added": 8,
  "items_skipped": 2,
  "skip_reasons": {
    "pantry_threshold": ["Eggs (pantry at 80%)"],
    "user_specified": []
  },
  "shopping_list_total_items": 15,
  "message": "Added 8 ingredients from 'Pasta Carbonara' (scaled to 2 servings)"
}
```

### get_shopping_list() Response
```json
{
  "success": true,
  "items": [
    {
      "id": "list_item_001",
      "product_id": "0001111041700",
      "ingredient_name": "Spaghetti",
      "quantity": 2,
      "unit": "boxes",
      "sources": [
        {
          "recipe_id": "abc123",
          "recipe_name": "Pasta Carbonara",
          "servings_used": 2,
          "original_quantity": 1
        },
        {
          "recipe_id": "def456",
          "recipe_name": "Marinara",
          "servings_used": 2,
          "original_quantity": 1
        }
      ],
      "notes": null
    }
  ],
  "total_items": 15,
  "recipes_included": [
    {
      "recipe_id": "abc123",
      "recipe_name": "Pasta Carbonara",
      "servings": 2
    },
    {
      "recipe_id": "def456",
      "recipe_name": "Marinara",
      "servings": 2
    }
  ],
  "servings_summary": {
    "household_default": 2,
    "total_servings_planned": 4,
    "total_meals": 2
  }
}
```

### add_shopping_list_to_cart() Preview
```json
{
  "success": true,
  "confirmation_required": true,
  "preview": {
    "items_to_add": 12,
    "items_to_skip": 3,
    "items": [
      {
        "product_id": "0001111041700",
        "ingredient_name": "Spaghetti",
        "quantity": 2,
        "action": "ADD",
        "reason": "Not in pantry",
        "from_recipes": ["Pasta Carbonara", "Marinara"]
      },
      {
        "product_id": "0001111089476",
        "ingredient_name": "Eggs",
        "quantity": 6,
        "action": "SKIP",
        "reason": "Pantry at 80%",
        "from_recipes": ["Pasta Carbonara"]
      }
    ]
  },
  "next_step": "Review the items above. Call this tool again with confirm=True to add to cart."
}
```

### add_shopping_list_to_cart() Confirmed
```json
{
  "success": true,
  "items_added_to_cart": 12,
  "items_skipped": 3,
  "shopping_list_cleared": true,
  "modality": "PICKUP",
  "message": "Added 12 items to cart. Shopping list has been cleared.",
  "reminder": "Review your cart in the Kroger app before checkout."
}
```

## Benefits Summary

1. **Personalized scaling** - Recipes auto-match household size
2. **Reduced waste** - Right-sized portions from the start
3. **Shopping list flexibility** - Build from multiple recipes before committing
4. **Consolidated quantities** - Automatically merge common ingredients
5. **Pantry awareness** - Must review inventory before shopping
6. **Workflow enforcement** - Session requirements prevent duplicate purchases
7. **Transparent servings** - Always shows household default vs recipe servings
8. **Override flexibility** - Can manually specify servings when needed
9. **Better planning** - See total servings across multiple recipes
10. **Persistent preferences** - Set once, applies everywhere

## Migration Notes

### Backward Compatibility

**Existing data:**
- All existing recipes keep their current servings
- No data migration required
- Default preference starts at 4 (current implicit default)

**Existing tools:**
- All parameters remain optional
- No breaking changes to tool signatures
- New parameters are optional with sensible defaults

**Existing workflows:**
- Current workflows continue to work unchanged
- New shopping list workflow is optional (can still use direct add_to_cart)
- Session requirement only applies to new shopping list tools

### Upgrade Path

1. **Immediate** - set_default_servings() available, but defaults to 4
2. **Gradual adoption** - Users can start using shopping list when ready
3. **No forced migration** - Direct add_to_cart still works
4. **Optional scaling** - scale_to_household parameter is opt-in

## Success Criteria

- [ ] User can set and retrieve default servings preference
- [ ] New recipes auto-scale to household default
- [ ] Shopping list stores items from multiple recipes
- [ ] Quantities consolidate correctly across recipes
- [ ] Session requirement blocks without get_pantry_attention
- [ ] Shopping list → cart workflow succeeds
- [ ] Auto-scaling uses correct scale factor
- [ ] Servings info displays prominently in all responses
- [ ] Meal planner uses household default
- [ ] All existing workflows continue working
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Server instructions updated
