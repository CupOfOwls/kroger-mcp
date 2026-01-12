# Changelog

All notable changes to the `kroger-mcp` package will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2025-01-12

### Added

- **Purchase Analytics System**: SQLite-based analytics with EWMA prediction algorithms
  - Purchase tracking with quantity, date, and modality recording
  - Statistical analysis (frequency, consumption rate, std deviation, seasonality)
  - Smart predictions for when items will be needed based on purchase history
  - Confidence scores and urgency levels (overdue, urgent, due soon, scheduled)

- **Pantry Inventory Tracking**: Estimate inventory levels based on consumption patterns
  - Auto-depletion calculation from purchase history
  - Manual adjustments that improve future predictions (feedback loop)
  - Low inventory alerts at configurable thresholds (default 20%)
  - Depletion rate learning from actual usage

- **Recipe Management**: Save and selectively reorder recipe ingredients
  - Save recipes with full ingredient lists, instructions, and Kroger product links
  - Selective ordering with `skip_items` fuzzy matching (skip items you already have)
  - Recipe scaling for different serving sizes
  - Recipe-pantry integration to check what you can cook

- **Smart Shopping Intelligence**: Intelligent shopping suggestions
  - Shopping suggestions combining predictions + routine items + seasonal items
  - Seasonal awareness for holidays (Thanksgiving, Christmas, Halloween, Easter, July 4th)
  - Item categorization (routine/regular/treat) with auto-detection and manual override

- **Reporting & Export**: Analytics reports and data export
  - Spending analysis by category
  - Shopping pattern analysis (day of week, modality preferences)
  - Prediction accuracy tracking
  - Pantry status reports
  - Complete JSON data export for backup or external analysis

- **Configuration System**: Tunable prediction parameters
  - EWMA alpha (decay factor)
  - Safety buffers per category
  - Category thresholds (routine/regular/treat)

### Technical

- SQLite database for analytics (`kroger_analytics.db`)
- 18 new prediction/analytics tools
- 9 recipe management tools
- 5 reporting tools
- Migration tool for existing JSON data

### New Tools (32 total)

**Prediction & Analytics (18)**:
`get_purchase_predictions`, `get_item_statistics`, `get_purchase_history`,
`get_shopping_suggestions`, `get_seasonal_items`, `categorize_item`,
`get_items_by_category`, `get_category_summary`, `get_pantry`, `add_to_pantry`,
`remove_from_pantry`, `update_pantry_item`, `restock_pantry_item`,
`get_low_inventory`, `configure_predictions`, `get_prediction_config`,
`reset_prediction_config`, `migrate_purchase_data`

**Recipe Management (9)**:
`save_recipe`, `get_recipes`, `get_recipe`, `search_recipes`, `update_recipe`,
`delete_recipe`, `preview_recipe_order`, `order_recipe_ingredients`,
`link_ingredient_to_product`

**Reporting (5)**:
`get_analytics_report`, `export_data`, `check_recipe_pantry`,
`generate_recipe_shopping_list`, `get_cookable_recipes`

## [0.2.0] - 2025-05-28

### Added

- **MCP-Compatible Authentication Flow**: Implemented a new authentication flow designed for MCP environments
  - New `start_authentication` tool to begin the OAuth flow
  - New `complete_authentication` tool to finish the OAuth flow with a redirect URL
  - Better error handling and messaging for authentication issues

### Changed

- **PKCE Support**: Updated to use the Proof Key for Code Exchange (PKCE) extension for enhanced OAuth security
- **Updated Dependencies**: Now requires kroger-api >= 0.2.0 for PKCE support
- **Improved Error Messaging**: Better error messages for authentication issues

### Removed

- **Browser-Based Authentication**: Removed the automatic browser-opening authentication flow, replaced with MCP-compatible flow

### Security

- Enhanced OAuth security with PKCE support, mitigating authorization code interception attacks

## [0.1.0] - 2025-05-23

### Added

- Initial release of the Kroger MCP server
- Support for FastMCP tools to interact with the Kroger API
- Location search and management
- Product search and details
- Cart management with local tracking
- Chain and department information
- User profile and authentication
