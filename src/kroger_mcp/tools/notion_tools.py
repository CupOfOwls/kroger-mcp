"""
Notion sync tools for the Kroger MCP server.

Provides the 'notion' action-based tool for syncing recipes
to a Notion database with two-way sync support.
"""

import os
from typing import Any, Dict, List, Literal, Optional

from fastmcp import Context
from pydantic import Field

from ..analytics.notion_sync import (
    _load_sync_state,
    bulk_tag,
    delete_recipe_page,
    get_sync_status,
    pull_changes,
    push_recipe,
    setup_database,
    sync_all,
    update_recipe_tags,
)


def _get_api_key() -> Optional[str]:
    """Get the Notion API key from environment."""
    return os.getenv("NOTION_API_KEY")


def _get_workspace_id() -> Optional[str]:
    """Get the Notion workspace ID from environment."""
    return os.getenv("NOTION_WORKSPACE_ID")


def _load_all_recipes() -> List[Dict[str, Any]]:
    """Load all recipes from local JSON storage."""
    import json

    recipes_file = "kroger_recipes.json"
    try:
        if os.path.exists(recipes_file):
            with open(recipes_file, "r") as f:
                data = json.load(f)
                return data.get("recipes", [])
    except Exception:
        pass
    return []


def register_tools(mcp):
    """Register Notion sync tools with the FastMCP server."""

    @mcp.tool()
    async def notion(
        action: Literal[
            "setup",
            "sync_all",
            "pull_changes",
            "update_tags",
            "bulk_tag",
            "get_status",
            "view_recipe",
        ] = Field(
            description=(
                "Action to perform: "
                "'setup' - Create Notion database and perform initial sync of all recipes; "
                "'sync_all' - Re-push all local recipes to Notion (full resync); "
                "'pull_changes' - Import edits made in Notion back to local recipes; "
                "'update_tags' - Update tags on one recipe in Notion (requires recipe_id, tags); "
                "'bulk_tag' - Add a tag to many recipes at once (requires recipe_ids and tag); "
                "'get_status' - Show sync health: total recipes, synced count, last sync time; "
                "'view_recipe' - Get the Notion URL for a recipe (requires recipe_id)"
            )
        ),
        recipe_id: Optional[str] = Field(
            default=None,
            description="Recipe ID. Required for: update_tags, view_recipe",
        ),
        recipe_ids: Optional[List[str]] = Field(
            default=None,
            description="List of recipe IDs. Used by: bulk_tag",
        ),
        tags: Optional[List[str]] = Field(
            default=None,
            description="Tag list to set on the recipe. Required for: update_tags",
        ),
        tag: Optional[str] = Field(
            default=None,
            description="Single tag to add. Required for: bulk_tag",
        ),
        ctx: Context = None,
    ) -> Dict[str, Any]:
        """
        Sync recipes to/from a Notion database.

        Setup workflow (first time):
          1. Add NOTION_API_KEY and NOTION_WORKSPACE_ID to your .env file
          2. Call notion(action='setup') to create the database and sync all recipes
          3. All future recipe saves/updates/deletes auto-sync to Notion

        Actions:
        - setup: Creates the Notion database and does an initial full sync
        - sync_all: Re-push all recipes (useful after bulk local changes)
        - pull_changes: Import recipe edits from Notion (tags, description, servings)
        - update_tags: Replace tags on one recipe both locally and in Notion
        - bulk_tag: Add a tag to many recipes at once
        - get_status: Show sync health stats
        - view_recipe: Get the Notion page URL for a specific recipe
        """
        api_key = _get_api_key()
        if not api_key:
            return {
                "success": False,
                "error": (
                    "NOTION_API_KEY not set. Add it to your .env file:\n"
                    "  NOTION_API_KEY=your_notion_integration_secret"
                ),
            }

        match action:
            case "setup":
                workspace_id = _get_workspace_id()
                if not workspace_id:
                    return {
                        "success": False,
                        "error": (
                            "NOTION_WORKSPACE_ID not set. Add it to your .env file:\n"
                            "  NOTION_WORKSPACE_ID=your_workspace_page_id"
                        ),
                    }

                if ctx:
                    await ctx.info("Creating Notion database for recipes...")

                try:
                    database_id = setup_database(workspace_id, api_key)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to create Notion database: {str(e)}",
                        "hint": (
                            "Make sure your Notion integration has access to the workspace page. "
                            "In Notion: open the page → Share → Invite your integration."
                        ),
                    }

                if ctx:
                    await ctx.info("Syncing all existing recipes to Notion...")

                recipes = _load_all_recipes()
                stats = sync_all(recipes, api_key, database_id)

                database_url = f"https://notion.so/{database_id.replace('-', '')}"
                return {
                    "success": True,
                    "database_id": database_id,
                    "database_url": database_url,
                    "message": (
                        f"Notion database created and synced. "
                        f"{stats['synced']} recipes pushed, {stats['failed']} failed."
                    ),
                    "sync_stats": stats,
                    "next_steps": (
                        "All future recipe saves, updates, and deletes will auto-sync to Notion. "
                        "Use notion(action='pull_changes') to import edits made directly in Notion."
                    ),
                }

            case "sync_all":
                state = _load_sync_state()
                database_id = state.get("database_id")
                if not database_id:
                    return {
                        "success": False,
                        "error": "Notion not set up yet. Call notion(action='setup') first.",
                    }

                if ctx:
                    await ctx.info("Syncing all recipes to Notion...")

                recipes = _load_all_recipes()
                if not recipes:
                    return {
                        "success": True,
                        "message": "No local recipes to sync.",
                        "synced": 0,
                        "failed": 0,
                    }

                stats = sync_all(recipes, api_key, database_id)
                return {
                    "success": True,
                    "synced": stats["synced"],
                    "failed": stats["failed"],
                    "total_recipes": len(recipes),
                    "errors": stats.get("errors", []),
                    "message": f"Synced {stats['synced']} of {len(recipes)} recipes to Notion.",
                }

            case "pull_changes":
                state = _load_sync_state()
                database_id = state.get("database_id")
                if not database_id:
                    return {
                        "success": False,
                        "error": "Notion not set up yet. Call notion(action='setup') first.",
                    }

                if ctx:
                    await ctx.info("Fetching changes from Notion...")

                try:
                    updates = pull_changes(api_key, database_id)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to pull from Notion: {str(e)}",
                    }

                if not updates:
                    return {
                        "success": True,
                        "message": "No changes found in Notion since last pull.",
                        "updated_count": 0,
                        "updates": [],
                    }

                # Apply changes to local recipes
                import json

                recipes_file = "kroger_recipes.json"
                applied = []
                try:
                    with open(recipes_file, "r") as f:
                        data = json.load(f)

                    recipe_map = {r["id"]: r for r in data.get("recipes", [])}

                    for update in updates:
                        rid = update["recipe_id"]
                        if rid in recipe_map:
                            changes = update["changes"]
                            recipe = recipe_map[rid]
                            for field, value in changes.items():
                                recipe[field] = value
                            applied.append({
                                "recipe_id": rid,
                                "name": recipe.get("name"),
                                "fields_updated": list(changes.keys()),
                            })

                    from datetime import datetime
                    data["last_updated"] = datetime.now().isoformat()
                    with open(recipes_file, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to apply Notion changes locally: {str(e)}",
                    }

                return {
                    "success": True,
                    "updated_count": len(applied),
                    "updates": applied,
                    "message": f"Applied {len(applied)} update(s) from Notion.",
                }

            case "update_tags":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'update_tags'"}
                if tags is None:
                    return {"success": False, "error": "tags is required for 'update_tags'"}

                state = _load_sync_state()
                database_id = state.get("database_id")
                if not database_id:
                    return {
                        "success": False,
                        "error": "Notion not set up yet. Call notion(action='setup') first.",
                    }

                # Update Notion
                try:
                    updated = update_recipe_tags(recipe_id, tags, api_key, database_id)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to update tags in Notion: {str(e)}",
                    }

                if not updated:
                    return {
                        "success": False,
                        "error": f"Recipe '{recipe_id}' not found in Notion sync state. "
                                 "It may not have been synced yet. Call notion(action='sync_all') first.",
                    }

                # Also update local recipe
                import json

                recipes_file = "kroger_recipes.json"
                try:
                    with open(recipes_file, "r") as f:
                        data = json.load(f)
                    for r in data.get("recipes", []):
                        if r["id"] == recipe_id:
                            r["tags"] = tags
                            break
                    from datetime import datetime
                    data["last_updated"] = datetime.now().isoformat()
                    with open(recipes_file, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass  # Local update failure is non-fatal

                return {
                    "success": True,
                    "recipe_id": recipe_id,
                    "tags": tags,
                    "message": f"Tags updated on recipe '{recipe_id}' in Notion and locally.",
                }

            case "bulk_tag":
                if not tag:
                    return {"success": False, "error": "tag is required for 'bulk_tag'"}

                state = _load_sync_state()
                database_id = state.get("database_id")
                if not database_id:
                    return {
                        "success": False,
                        "error": "Notion not set up yet. Call notion(action='setup') first.",
                    }

                # If no recipe_ids, apply to all synced recipes
                target_ids = recipe_ids
                if not target_ids:
                    target_ids = list(state.get("recipes", {}).keys())

                if not target_ids:
                    return {
                        "success": True,
                        "message": "No recipes to tag. Sync recipes first.",
                        "updated": 0,
                    }

                if ctx:
                    await ctx.info(f"Adding tag '{tag}' to {len(target_ids)} recipe(s)...")

                try:
                    result = bulk_tag(target_ids, tag, api_key, database_id)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Bulk tag operation failed: {str(e)}",
                    }

                # Also update local recipes
                import json

                recipes_file = "kroger_recipes.json"
                try:
                    with open(recipes_file, "r") as f:
                        data = json.load(f)
                    for r in data.get("recipes", []):
                        if r["id"] in target_ids:
                            current_tags = r.get("tags", [])
                            if tag not in current_tags:
                                r["tags"] = current_tags + [tag]
                    from datetime import datetime
                    data["last_updated"] = datetime.now().isoformat()
                    with open(recipes_file, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception:
                    pass  # Local update failure is non-fatal

                return {
                    "success": True,
                    "tag": tag,
                    "updated": result["updated"],
                    "skipped": result["skipped"],
                    "errors": result.get("errors", []),
                    "message": f"Added tag '{tag}' to {result['updated']} recipe(s) in Notion.",
                }

            case "get_status":
                state = _load_sync_state()
                database_id = state.get("database_id")
                if not database_id:
                    return {
                        "success": True,
                        "configured": False,
                        "message": "Notion integration not set up. Call notion(action='setup') to get started.",
                    }

                try:
                    status = get_sync_status(api_key, database_id)
                except Exception as e:
                    return {
                        "success": False,
                        "error": f"Failed to get sync status: {str(e)}",
                        "database_id": database_id,
                        "last_synced": state.get("last_synced"),
                    }

                local_recipes = _load_all_recipes()
                status["configured"] = True
                status["total_local_recipes"] = len(local_recipes)
                status["database_url"] = (
                    f"https://notion.so/{database_id.replace('-', '')}"
                )
                return status

            case "view_recipe":
                if not recipe_id:
                    return {"success": False, "error": "recipe_id is required for 'view_recipe'"}

                state = _load_sync_state()
                entry = state.get("recipes", {}).get(recipe_id)
                if not entry or not entry.get("notion_page_id"):
                    return {
                        "success": False,
                        "error": (
                            f"Recipe '{recipe_id}' has not been synced to Notion. "
                            "Call notion(action='sync_all') first."
                        ),
                    }

                page_id = entry["notion_page_id"].replace("-", "")
                notion_url = f"https://notion.so/{page_id}"
                return {
                    "success": True,
                    "recipe_id": recipe_id,
                    "notion_page_id": entry["notion_page_id"],
                    "url": notion_url,
                    "synced_at": entry.get("synced_at"),
                }

            case _:
                return {
                    "success": False,
                    "error": (
                        f"Unknown action: '{action}'. "
                        "Valid actions: setup, sync_all, pull_changes, update_tags, "
                        "bulk_tag, get_status, view_recipe"
                    ),
                }
