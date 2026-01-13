# 🛒 Kroger MCP Server 🛍️ -- FastMCP for Kroger Shopping

![Logo](media/harper_logo.jpeg)

A [FastMCP](https://github.com/jlowin/fastmcp) server that provides AI assistants like Claude with access to Kroger's grocery shopping functionality through the Model Context Protocol ([MCP](https://docs.anthropic.com/en/docs/agents-and-tools/mcp)). This server enables AI assistants to find stores, search products, manage shopping carts, and access Kroger's comprehensive grocery data via the [kroger-api](https://github.com/CupOfOwls/kroger-api) python library.

## 📺 Demo

Using Claude with this MCP server to search for stores, find products, and add items to your cart:

https://github.com/user-attachments/assets/69055f5f-04f5-4ec1-96ac-330aa288fbd1

## Changelog
A changelog with recent changes is [here](CHANGELOG.md).

## 🚀 Quick Start

### Prerequisites
You will need Kroger API credentials (free from [Kroger Developer Portal](https://developer.kroger.com/)).
Visit the [Kroger Developer Portal](https://developer.kroger.com/manage/apps/register) to:
1. Create a developer account
2. Register your application
3. Get your `CLIENT_ID`, `CLIENT_SECRET`, and set your `REDIRECT_URI`

The first time you run a tool requiring user authentication, you'll be prompted to authorize your app through your web browser. You're granting permission to **your own registered app**, not to any third party.

### Installation
##### ⚠️ macOS users must use installation Option 2 ⚠️

#### Option 1: Using uvx with Claude Desktop (Recommended)
Once published to PyPI, you can use uvx to run the package directly without cloning the repository:

Edit Claude Desktop's configuration file:

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`


**Linux**: `~/.config/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kroger": {
      "command": "uvx",
      "args": [
        "kroger-mcp"
      ],
      "env": {
        "KROGER_CLIENT_ID": "your_client_id",
        "KROGER_CLIENT_SECRET": "your_client_secret", 
        "KROGER_REDIRECT_URI": "http://localhost:8000/callback",
        "KROGER_USER_ZIP_CODE": "10001"
      }
    }
  }
}
```

Benefits of this method:
- Automatically installs the package from PyPI if needed
- Creates an isolated environment for running the server
- Makes it easy to stay updated with the latest version
- Doesn't require maintaining a local repository clone

#### Option 2: Using uv with a Local Clone
First, clone locally:
```bash
git clone https://github.com/CupOfOwls/kroger-mcp
```

Then, edit Claude Desktop's configuration file:

```json
{
  "mcpServers": {
    "kroger": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/cloned/kroger-mcp",
        "run",
        "kroger-mcp"
      ],
      "env": {
        "KROGER_CLIENT_ID": "your_client_id",
        "KROGER_CLIENT_SECRET": "your_client_secret", 
        "KROGER_REDIRECT_URI": "http://localhost:8000/callback",
        "KROGER_USER_ZIP_CODE": "10001"
      }
    }
  }
}
```

#### Option 3: Installing From PyPI

```bash
# Install with uv (recommended)
uv pip install kroger-mcp

# Or install with pip
pip install kroger-mcp
```

#### Option 4: Installing From Source

```bash
# Clone the repository
git clone https://github.com/CupOfOwls/kroger-mcp
cd kroger-mcp

# Install with uv (recommended)
uv sync

# Or install with pip
pip install -e .
```

### Configuration

Create a `.env` file in your project root or pass in env values via the JSON config:

```bash
# Required: Your Kroger API credentials
KROGER_CLIENT_ID=your_client_id_here
KROGER_CLIENT_SECRET=your_client_secret_here
KROGER_REDIRECT_URI=http://localhost:8000/callback

# Optional: Default zip code for location searches
KROGER_USER_ZIP_CODE=90274
```

### Running the Server

```bash
# With uv (recommended)
uv run kroger-mcp

# With uvx (directly from PyPI without installation)
uvx kroger-mcp

# Or with Python directly
python server.py

# With FastMCP CLI for development
fastmcp dev server.py --with-editable .
```


## 🛠️ Features

This MCP server provides **71 tools** across 11 modules:
- **Core Shopping**: Locations, products, cart management
- **Smart Analytics**: Purchase predictions, consumption patterns, seasonal awareness
- **Recipe Management**: Save recipes, selective ordering with skip items
- **Pantry Tracking**: Inventory levels with auto-depletion estimates
- **Favorite Lists**: Named shopping lists (Weekly Staples, Party Supplies, etc.)
- **Reporting**: Spending analysis, pattern reports, data export

### 💬 Built-In MCP Prompts
- **Shopping Path**: Find optimal path through store for a grocery list
- **Pharmacy Check**: Check if pharmacy at preferred location is open
- **Store Selection**: Help user set their preferred Kroger store
- **Recipe Shopping**: Find recipes and add ingredients to cart

### 📚 Available Tools (71 Total)

#### Location Tools (6)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `search_locations` | Find Kroger stores near a zip code | No |
| `get_user_zip_code` | Get the default zip code from environment | No |
| `get_location_details` | Get detailed information about a specific store | No |
| `set_preferred_location` | Set a preferred store for future operations | No |
| `get_preferred_location` | Get the currently set preferred store | No |
| `check_location_exists` | Verify if a location ID is valid | No |

#### Product Tools (4)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `search_products` | Search for products by name, brand, or other criteria | No |
| `get_product_details` | Get detailed product information including pricing | No |
| `search_products_by_id` | Find products by their specific product ID | No |
| `get_product_images` | Get product images from specific perspective (front, back, etc.) | No |

#### Cart Tools (7)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `add_items_to_cart` | Add a single item to cart | Yes |
| `bulk_add_to_cart` | Add multiple items to cart in one operation | Yes |
| `view_current_cart` | View items currently in your local cart tracking | No |
| `remove_from_cart` | Remove items from local cart tracking | No |
| `clear_current_cart` | Clear all items from local cart tracking | No |
| `mark_order_placed` | Move current cart to order history | No |
| `view_order_history` | View history of placed orders | No |

#### Information Tools (6)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `list_chains` | Get all Kroger-owned chains | No |
| `get_chain_details` | Get details about a specific chain | No |
| `check_chain_exists` | Check if a chain exists | No |
| `list_departments` | Get all store departments | No |
| `get_department_details` | Get details about a specific department | No |
| `check_department_exists` | Check if a department exists | No |

#### Profile Tools (4)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `get_user_profile` | Get authenticated user's profile information | Yes |
| `test_authentication` | Test if authentication token is valid | Yes |
| `get_authentication_info` | Get detailed authentication status | Yes |
| `force_reauthenticate` | Clear tokens and force re-authentication | No |

#### Authentication Tools (2)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `start_authentication` | Begin OAuth2 flow, returns authorization URL | No |
| `complete_authentication` | Complete OAuth2 flow with redirect URL | No |

#### Utility Tools (1)

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `get_current_datetime` | Get current system date and time | No |

#### Prediction & Analytics Tools (18)

Smart shopping predictions based on purchase history with EWMA algorithms.

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `get_purchase_predictions` | Predict items needed in next N days with urgency scores | No |
| `get_item_statistics` | Get detailed stats for a product (frequency, consumption rate) | No |
| `get_purchase_history` | View purchase history for a specific product | No |
| `get_shopping_suggestions` | Smart list combining predictions + routine + seasonal items | No |
| `get_seasonal_items` | Get items for upcoming holidays | No |
| `categorize_item` | Set item category (routine/regular/treat) | No |
| `get_items_by_category` | List all items in a category | No |
| `get_category_summary` | Count items by category | No |
| `get_pantry` | View pantry items with estimated inventory levels | No |
| `add_to_pantry` | Start tracking an item in pantry | No |
| `remove_from_pantry` | Stop tracking a pantry item | No |
| `update_pantry_item` | Manually set inventory level (0-100%) | No |
| `restock_pantry_item` | Mark item as restocked | No |
| `get_low_inventory` | Find pantry items running low | No |
| `configure_predictions` | Tune prediction parameters (EWMA alpha, buffers) | No |
| `get_prediction_config` | View current prediction settings | No |
| `reset_prediction_config` | Reset prediction config to defaults | No |
| `migrate_purchase_data` | Migrate JSON history to SQLite database | No |

#### Recipe Tools (9)

Save recipes and selectively order ingredients (skipping items you already have).

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `save_recipe` | Save a recipe with ingredients and instructions | No |
| `get_recipes` | List all saved recipes | No |
| `get_recipe` | Get full recipe details including ingredients | No |
| `search_recipes` | Search recipes by name, tags, or description | No |
| `update_recipe` | Update an existing recipe | No |
| `delete_recipe` | Delete a saved recipe | No |
| `preview_recipe_order` | Preview order with skip_items option | No |
| `order_recipe_ingredients` | Order recipe ingredients, skipping items you have | Yes |
| `link_ingredient_to_product` | Link recipe ingredient to Kroger product ID | No |

#### Reporting & Export Tools (5)

Analytics reports and recipe-pantry integration.

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `get_analytics_report` | Generate reports (spending, predictions, patterns, pantry) | No |
| `export_data` | Export all data as JSON for backup | No |
| `check_recipe_pantry` | Check pantry inventory for recipe ingredients | No |
| `generate_recipe_shopping_list` | Create optimized list for multiple recipes | No |
| `get_cookable_recipes` | Find recipes makeable with current pantry | No |

#### Favorite Lists Tools (9)

Named shopping lists as a workaround for Kroger's Public API not supporting lists.

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `create_favorite_list` | Create a new named list (e.g., "Weekly Staples") | No |
| `get_favorite_lists` | List all favorite lists with item counts | No |
| `rename_favorite_list` | Rename or update list description | No |
| `delete_favorite_list` | Delete a list and all its items | No |
| `add_to_favorite_list` | Add product to a specific list | No |
| `remove_from_favorite_list` | Remove product from a list | No |
| `get_favorite_list_items` | Get all items in a list with pantry status | No |
| `order_favorite_list` | Add list items to cart (skip well-stocked items) | Yes |
| `suggest_favorites` | Suggest products based on purchase history | No |

### 🧰 Local-Only Cart Tracking

Since the Kroger API doesn't provide cart viewing functionality, this server maintains local tracking:

#### Local Cart Storage
- **File**: `kroger_cart.json`
- **Contents**: Current cart items with timestamps
- **Automatic**: Created and updated automatically

#### Order History
- **File**: `kroger_order_history.json`
- **Contents**: Historical orders with placement timestamps
- **Usage**: Move completed carts to history with `mark_order_placed`

### 🚧 Kroger Public API Limitations
- **View Only**: The `remove_from_cart` and `clear_current_cart` tools ONLY affect local tracking, not the actual Kroger cart
- **Local Sync**: Use these tools only when the user has already removed items from their cart in the Kroger app/website
- **One-Way**: Items can be added to the Kroger cart but not removed through the Public API. The Partner API would allow these things, but that requires entering a contract with Kroger.

| API | Version | Rate Limit | Notes |
|-----|---------|------------|-------|
| **Authorization** | 1.0.13 | No specific limit | Token management |
| **Products** | 1.2.4 | 10,000 calls/day | Search and product details |
| **Locations** | 1.2.2 | 1,600 calls/day per endpoint | Store locations and details |
| **Cart** | 1.2.3 | 5,000 calls/day | Add/manage cart items |
| **Identity** | 1.2.3 | 5,000 calls/day | User profile information |

**Note:** Rate limits are enforced per endpoint, not per operation. You can distribute calls across operations using the same endpoint as needed.

### 📊 Analytics System

The analytics system uses SQLite to track purchase patterns and make predictions:

**Database**: `kroger_analytics.db`
- Stores purchase events with timestamps and quantities
- Tracks product statistics (frequency, consumption rate, seasonality)
- Manages pantry inventory levels with auto-depletion

**Prediction Algorithm**: EWMA (Exponentially Weighted Moving Average)
- Weights recent purchases more heavily than older ones
- Configurable decay factor (`ewma_alpha`)
- Safety buffers by category (routine/regular/treat)

**Item Categories**:
- **Routine**: Items purchased every 1-14 days (milk, bread, eggs)
- **Regular**: Items purchased every 15-60 days (spices, cleaning supplies)
- **Treat**: Holiday/seasonal items (turkey, candy)

### 🍳 Recipe Storage

Recipes are stored in `kroger_recipes.json` with:
- Full ingredient lists with quantities and units
- Optional Kroger product ID links for direct ordering
- Tags for easy searching
- Order history tracking

**Selective Ordering**: When reordering recipes, use `skip_items` to exclude ingredients you already have. Uses fuzzy matching (e.g., `skip_items=["eggs"]` matches "Large Eggs", "Organic Eggs", etc.)

## 🏫 Basic Workflow

1. **Set up a preferred location**:
   ```
   User: "Find Kroger stores near 90274"
   Assistant: [Uses search_locations tool]
   User: "Set the first one as my preferred location"
   Assistant: [Uses set_preferred_location tool]
   ```

2. **Search and add products**:
   ```
   User: "Add milk to my cart"
   Assistant: [Uses search_products, then add_items_to_cart]
   
   User: "Add bread, eggs, and cheese to my cart"
   Assistant: [Uses search_products for each, then bulk_add_to_cart]
   ```

3. **Manage cart and orders**:
   ```
   User: "What's in my cart?"
   Assistant: [Uses view_current_cart tool to see local memory]

   User: "I placed the order on the Kroger website"
   Assistant: [Uses mark_order_placed tool, moving current cart to the order history]
   ```

## 🔮 Advanced Workflows

### Smart Shopping with Predictions
```
User: "What groceries should I buy this week?"
Assistant: [Uses get_shopping_suggestions with days_ahead=7]
         → Returns items by urgency: overdue, urgent, due soon
         → Includes routine items + seasonal suggestions
```

### Recipe Management
```
User: "Save this carbonara recipe"
Assistant: [Uses save_recipe with ingredients and product_ids]

User: "Order my carbonara recipe, but I have eggs and pasta"
Assistant: [Uses preview_recipe_order with skip_items=["eggs", "pasta"]]
         [Uses order_recipe_ingredients to add remaining items to cart]
```

### Pantry Tracking
```
User: "What's running low in my pantry?"
Assistant: [Uses get_low_inventory with threshold=20]
         → Shows items below 20% with days until empty

User: "I'm actually out of milk"
Assistant: [Uses update_pantry_item with level=0]
         → System learns from this adjustment for better predictions
```

### Analytics Reports
```
User: "Show me my spending patterns"
Assistant: [Uses get_analytics_report with report_type='spending']
         → Shows breakdown by category, top products, trends

User: "What recipes can I make with what I have?"
Assistant: [Uses get_cookable_recipes]
         → Returns recipes sorted by feasibility with current pantry
```

## 🍪 OAuth2 Authentication

When Claude attempts to modify your Kroger account, you will be asked to insert a link into your browser that will handle authentication and allow Claude to add/remove items from your cart. Ensure that you have already made a Kroger account (this is different than your Kroger development account) before attempting to paste this link into your browser to initiate authentication.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This is an unofficial MCP server for the Kroger Public API. It is not affiliated with, endorsed by, or sponsored by Kroger.

For questions about the Kroger API, visit the [Kroger Developer Portal](https://developer.kroger.com/) or read the [kroger-api](https://github.com/CupOfOwls/kroger-api) package documentation.
