"""
Notion sync integration for recipe management.

Handles two-way synchronization between local kroger_recipes.json
and a Notion database. All Notion API calls are best-effort;
failures never block recipe operations.
"""

import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import urllib.parse


# Sync state file — maps recipe_id → notion_page_id
NOTION_SYNC_FILE = "kroger_notion_sync.json"

# Notion API constants
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


# ---------------------------------------------------------------------------
# Sync state helpers
# ---------------------------------------------------------------------------

def _load_sync_state() -> Dict[str, Any]:
    """Load the Notion sync state from disk."""
    try:
        if os.path.exists(NOTION_SYNC_FILE):
            with open(NOTION_SYNC_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "database_id": None,
        "api_key_hint": None,
        "last_synced": None,
        "last_pull": None,
        "recipes": {},
    }


def _save_sync_state(state: Dict[str, Any]) -> None:
    """Persist sync state to disk."""
    try:
        with open(NOTION_SYNC_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save Notion sync state: {e}")


# ---------------------------------------------------------------------------
# Notion API helpers
# ---------------------------------------------------------------------------

def _notion_request(
    method: str,
    path: str,
    api_key: str,
    body: Optional[Dict] = None,
) -> Dict[str, Any]:
    """
    Make a Notion API request. Raises on HTTP error.

    Args:
        method: HTTP method (GET, POST, PATCH)
        path: API path (e.g. '/databases')
        api_key: Notion integration secret
        body: Request body dict (JSON-serialized)

    Returns:
        Parsed JSON response dict
    """
    url = f"{NOTION_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            error_data = json.loads(error_body)
            raise RuntimeError(
                f"Notion API {e.code}: {error_data.get('message', error_body)}"
            )
        except (json.JSONDecodeError, KeyError):
            raise RuntimeError(f"Notion API {e.code}: {error_body}")


def _paginate_query(
    api_key: str,
    database_id: str,
    filter_body: Optional[Dict] = None,
) -> List[Dict]:
    """
    Query all pages from a Notion database, handling pagination.
    Returns list of page objects.
    """
    results = []
    start_cursor = None

    while True:
        body: Dict[str, Any] = {"page_size": 100}
        if filter_body:
            body["filter"] = filter_body
        if start_cursor:
            body["start_cursor"] = start_cursor

        resp = _notion_request(
            "POST", f"/databases/{database_id}/query", api_key, body
        )
        results.extend(resp.get("results", []))

        if not resp.get("has_more"):
            break
        start_cursor = resp.get("next_cursor")

    return results


# ---------------------------------------------------------------------------
# Property builders
# ---------------------------------------------------------------------------

def _build_properties(recipe: Dict[str, Any]) -> Dict[str, Any]:
    """Build Notion page properties from a recipe dict."""
    props: Dict[str, Any] = {}

    # Name (title property)
    props["Name"] = {
        "title": [{"text": {"content": recipe.get("name", "Untitled Recipe")}}]
    }

    # Tags (multi_select)
    tags = recipe.get("tags", [])
    props["Tags"] = {
        "multi_select": [{"name": str(t)} for t in tags if t]
    }

    # Servings (number)
    servings = recipe.get("servings")
    if servings is not None:
        props["Servings"] = {"number": servings}

    # Times Ordered (number)
    times_ordered = recipe.get("times_ordered", 0)
    props["Times Ordered"] = {"number": times_ordered}

    # Description (rich_text)
    description = recipe.get("description") or ""
    props["Description"] = {
        "rich_text": [{"text": {"content": description[:2000]}}]
    }

    # Last Ordered (date)
    last_ordered = recipe.get("last_ordered_at")
    if last_ordered:
        props["Last Ordered"] = {"date": {"start": last_ordered[:10]}}

    # Created (date)
    created_at = recipe.get("created_at")
    if created_at:
        props["Created"] = {"date": {"start": created_at[:10]}}

    # Recipe ID (rich_text — used for sync matching)
    props["Recipe ID"] = {
        "rich_text": [{"text": {"content": recipe.get("id", "")}}]
    }

    return props


def _build_page_blocks(recipe: Dict[str, Any]) -> List[Dict]:
    """Build Notion page body blocks for a recipe."""
    blocks: List[Dict] = []

    # Ingredients section
    ingredients = recipe.get("ingredients", [])
    if ingredients:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Ingredients"}}]
            },
        })
        for ing in ingredients:
            qty = ing.get("quantity", "")
            unit = ing.get("unit", "")
            ing_name = ing.get("name", "")
            parts = [str(x) for x in [qty, unit, ing_name] if x]
            text = " ".join(parts)

            substitutes = ing.get("substitutes", [])
            if substitutes:
                text += f" (or: {', '.join(substitutes)})"

            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": text[:2000]}}]
                },
            })

    # Instructions section
    steps = recipe.get("steps", [])
    instructions = recipe.get("instructions", "")

    if steps:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Instructions"}}]
            },
        })
        for step in steps:
            step_text = step.get("instruction", "") if isinstance(step, dict) else str(step)
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": step_text[:2000]}}]
                },
            })
    elif instructions:
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"type": "text", "text": {"content": "Instructions"}}]
            },
        })
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": instructions[:2000]}}]
            },
        })

    return blocks


# ---------------------------------------------------------------------------
# Database setup
# ---------------------------------------------------------------------------

def setup_database(workspace_id: str, api_key: str) -> str:
    """
    Create a Notion database for recipes.

    Args:
        workspace_id: Notion workspace/page ID to create database under
        api_key: Notion integration secret

    Returns:
        database_id of the created database

    Raises:
        RuntimeError: If database creation fails
    """
    body = {
        "parent": {"type": "page_id", "page_id": workspace_id},
        "title": [{"type": "text", "text": {"content": "Kroger Recipes"}}],
        "properties": {
            "Name": {"title": {}},
            "Tags": {"multi_select": {}},
            "Servings": {"number": {"format": "number"}},
            "Times Ordered": {"number": {"format": "number"}},
            "Description": {"rich_text": {}},
            "Last Ordered": {"date": {}},
            "Created": {"date": {}},
            "Recipe ID": {"rich_text": {}},
        },
    }

    resp = _notion_request("POST", "/databases", api_key, body)
    database_id = resp["id"]

    # Persist to sync state
    state = _load_sync_state()
    state["database_id"] = database_id
    state["api_key_hint"] = api_key[:8] + "..." + api_key[-4:]
    state["last_synced"] = datetime.now().isoformat()
    _save_sync_state(state)

    return database_id


# ---------------------------------------------------------------------------
# Push / create / update
# ---------------------------------------------------------------------------

def push_recipe(recipe: Dict[str, Any], api_key: str, database_id: str) -> str:
    """
    Create or update a Notion page for a recipe.

    Args:
        recipe: Recipe dict from kroger_recipes.json
        api_key: Notion integration secret
        database_id: Target Notion database ID

    Returns:
        Notion page_id

    Raises:
        RuntimeError: If Notion API call fails
    """
    state = _load_sync_state()
    recipe_id = recipe.get("id", "")
    existing_entry = state.get("recipes", {}).get(recipe_id)
    properties = _build_properties(recipe)

    if existing_entry and existing_entry.get("notion_page_id"):
        # Update existing page properties
        page_id = existing_entry["notion_page_id"]
        _notion_request(
            "PATCH", f"/pages/{page_id}", api_key, {"properties": properties}
        )
        # Note: Notion API does not support replacing block children directly
        # without first deleting them. For simplicity, property updates only.
        # Full block refresh would require listing & deleting existing children first.
    else:
        # Create new page with properties + body blocks
        blocks = _build_page_blocks(recipe)
        body: Dict[str, Any] = {
            "parent": {"database_id": database_id},
            "properties": properties,
        }
        if blocks:
            body["children"] = blocks[:100]  # Notion API limit

        resp = _notion_request("POST", "/pages", api_key, body)
        page_id = resp["id"]

    # Update sync state
    if "recipes" not in state:
        state["recipes"] = {}
    state["recipes"][recipe_id] = {
        "notion_page_id": page_id,
        "synced_at": datetime.now().isoformat(),
        "notion_last_edited": datetime.now().isoformat(),
    }
    state["last_synced"] = datetime.now().isoformat()
    _save_sync_state(state)

    return page_id


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_recipe_page(recipe_id: str, api_key: str) -> bool:
    """
    Archive the Notion page for a recipe (Notion doesn't hard-delete via API).

    Args:
        recipe_id: Local recipe ID
        api_key: Notion integration secret

    Returns:
        True if archived, False if not found in sync state
    """
    state = _load_sync_state()
    entry = state.get("recipes", {}).get(recipe_id)
    if not entry or not entry.get("notion_page_id"):
        return False

    page_id = entry["notion_page_id"]
    _notion_request("PATCH", f"/pages/{page_id}", api_key, {"archived": True})

    # Remove from sync state
    del state["recipes"][recipe_id]
    _save_sync_state(state)
    return True


# ---------------------------------------------------------------------------
# Pull changes
# ---------------------------------------------------------------------------

def pull_changes(api_key: str, database_id: str) -> List[Dict[str, Any]]:
    """
    Fetch pages edited in Notion since last pull and return updated recipe dicts.

    Compares notion_last_edited_time against synced_at in sync state.
    Extracts Name, Tags, Description, Servings from Notion properties.

    Args:
        api_key: Notion integration secret
        database_id: Notion database ID

    Returns:
        List of dicts with recipe update info: {recipe_id, name, changes}
    """
    state = _load_sync_state()
    last_pull = state.get("last_pull")
    pages = _paginate_query(api_key, database_id)

    updated = []
    recipe_sync = state.get("recipes", {})

    # Build reverse map: page_id → recipe_id
    page_to_recipe = {
        v["notion_page_id"]: rid
        for rid, v in recipe_sync.items()
        if v.get("notion_page_id")
    }

    for page in pages:
        page_id = page.get("id", "").replace("-", "")
        # Notion returns ID with hyphens, normalize
        page_id_normalized = page.get("id", "")

        recipe_id = page_to_recipe.get(page_id_normalized)
        if not recipe_id:
            # Try to extract Recipe ID property
            recipe_id_prop = (
                page.get("properties", {})
                .get("Recipe ID", {})
                .get("rich_text", [{}])
            )
            if recipe_id_prop:
                recipe_id = recipe_id_prop[0].get("text", {}).get("content", "")

        if not recipe_id:
            continue

        notion_edited = page.get("last_edited_time", "")
        local_entry = recipe_sync.get(recipe_id, {})
        local_synced = local_entry.get("synced_at", "")

        # Only process pages edited after our last sync
        if last_pull and notion_edited and notion_edited <= local_synced:
            continue

        # Extract property changes from Notion page
        props = page.get("properties", {})
        changes: Dict[str, Any] = {}

        # Name
        name_prop = props.get("Name", {}).get("title", [{}])
        if name_prop:
            changes["name"] = name_prop[0].get("plain_text", "")

        # Tags
        tags_prop = props.get("Tags", {}).get("multi_select", [])
        changes["tags"] = [t["name"] for t in tags_prop if t.get("name")]

        # Description
        desc_prop = props.get("Description", {}).get("rich_text", [{}])
        if desc_prop:
            changes["description"] = desc_prop[0].get("plain_text", "")

        # Servings
        servings_prop = props.get("Servings", {}).get("number")
        if servings_prop is not None:
            changes["servings"] = servings_prop

        if changes:
            updated.append({
                "recipe_id": recipe_id,
                "notion_page_id": page_id_normalized,
                "notion_last_edited": notion_edited,
                "changes": changes,
            })

            # Update sync state timestamps
            if recipe_id in recipe_sync:
                recipe_sync[recipe_id]["notion_last_edited"] = notion_edited

    state["last_pull"] = datetime.now().isoformat()
    state["recipes"] = recipe_sync
    _save_sync_state(state)

    return updated


# ---------------------------------------------------------------------------
# Full sync
# ---------------------------------------------------------------------------

def sync_all(recipes: List[Dict[str, Any]], api_key: str, database_id: str) -> Dict[str, Any]:
    """
    Full resync: push all recipes to Notion.

    Args:
        recipes: List of recipe dicts
        api_key: Notion integration secret
        database_id: Notion database ID

    Returns:
        {synced: N, failed: N, skipped: N}
    """
    synced = 0
    failed = 0
    errors = []

    for recipe in recipes:
        try:
            push_recipe(recipe, api_key, database_id)
            synced += 1
        except Exception as e:
            failed += 1
            errors.append(f"{recipe.get('name', recipe.get('id', '?'))}: {str(e)}")

    return {
        "synced": synced,
        "failed": failed,
        "skipped": 0,
        "errors": errors[:10],  # Truncate long error lists
    }


# ---------------------------------------------------------------------------
# Tag operations
# ---------------------------------------------------------------------------

def update_recipe_tags(
    recipe_id: str,
    tags: List[str],
    api_key: str,
    database_id: str,
) -> bool:
    """
    Update the Tags property on a Notion page.

    Args:
        recipe_id: Local recipe ID
        tags: New tag list to set
        api_key: Notion integration secret
        database_id: Notion database ID (unused but kept for API consistency)

    Returns:
        True if updated, False if recipe not in sync state
    """
    state = _load_sync_state()
    entry = state.get("recipes", {}).get(recipe_id)
    if not entry or not entry.get("notion_page_id"):
        return False

    page_id = entry["notion_page_id"]
    _notion_request(
        "PATCH",
        f"/pages/{page_id}",
        api_key,
        {"properties": {"Tags": {"multi_select": [{"name": t} for t in tags]}}},
    )
    return True


def bulk_tag(
    recipe_ids: List[str],
    tag: str,
    api_key: str,
    database_id: str,
) -> Dict[str, Any]:
    """
    Add a tag to many recipes at once (on Notion pages).

    Args:
        recipe_ids: List of local recipe IDs
        tag: Tag to add
        api_key: Notion integration secret
        database_id: Notion database ID

    Returns:
        {updated: N, skipped: N, errors: [...]}
    """
    state = _load_sync_state()
    updated = 0
    skipped = 0
    errors = []

    for recipe_id in recipe_ids:
        entry = state.get("recipes", {}).get(recipe_id)
        if not entry or not entry.get("notion_page_id"):
            skipped += 1
            continue

        page_id = entry["notion_page_id"]
        try:
            # Fetch current tags first
            resp = _notion_request("GET", f"/pages/{page_id}", api_key)
            current_tags = [
                t["name"]
                for t in resp.get("properties", {})
                .get("Tags", {})
                .get("multi_select", [])
            ]
            if tag not in current_tags:
                current_tags.append(tag)

            _notion_request(
                "PATCH",
                f"/pages/{page_id}",
                api_key,
                {
                    "properties": {
                        "Tags": {
                            "multi_select": [{"name": t} for t in current_tags]
                        }
                    }
                },
            )
            updated += 1
        except Exception as e:
            errors.append(f"{recipe_id}: {str(e)}")

    return {"updated": updated, "skipped": skipped, "errors": errors[:10]}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def get_sync_status(api_key: str, database_id: str) -> Dict[str, Any]:
    """
    Return sync stats: total pages in Notion vs local sync state.

    Args:
        api_key: Notion integration secret
        database_id: Notion database ID

    Returns:
        {total_notion: N, total_synced: N, last_synced: str, last_pull: str}
    """
    state = _load_sync_state()
    local_synced = len(state.get("recipes", {}))

    total_notion = 0
    try:
        pages = _paginate_query(api_key, database_id)
        total_notion = len([p for p in pages if not p.get("archived")])
    except Exception as e:
        return {
            "success": False,
            "error": f"Could not query Notion database: {str(e)}",
            "local_synced": local_synced,
            "last_synced": state.get("last_synced"),
            "last_pull": state.get("last_pull"),
            "database_id": database_id,
        }

    return {
        "success": True,
        "total_in_notion": total_notion,
        "total_synced_locally": local_synced,
        "last_synced": state.get("last_synced"),
        "last_pull": state.get("last_pull"),
        "database_id": database_id,
    }
