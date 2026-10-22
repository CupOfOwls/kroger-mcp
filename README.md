# 🛒 Kroger MCP Server 🛍️ -- FastMCP for Kroger Shopping

A [FastMCP](https://github.com/jlowin/fastmcp) server that provides AI assistants like Claude with access to Kroger's grocery shopping functionality through the Model Context Protocol ([MCP](https://docs.anthropic.com/en/docs/agents-and-tools/mcp)). This server enables AI assistants to find stores, search products, manage shopping carts, and access Kroger's comprehensive grocery data via the [kroger-api](https://github.com/CupOfOwls/kroger-api) python library.

📚 **Docs:** https://cupofowls.github.io/kroger-api/building-ai-agents/agent-lab — build an AI agent with kroger-mcp, and the full tool reference.

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

Pass the settings in the `env` block of your MCP client's JSON config, or put them in a `.env` file in the directory you start the server from (only its `KROGER_*` settings are read):

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

# Options such as an HTTP transport (see kroger-mcp --help)
uvx kroger-mcp --transport streamable-http --port 8000

# With FastMCP CLI for development
fastmcp dev server.py --with-editable .
```


## 🛠️ Features

### 💬 Built-In MCP Prompts
- **Shopping Path**: Find optimal path through store for a grocery list
- **Pharmacy Check**: Check if pharmacy at preferred location is open
- **Store Selection**: Help user set their preferred Kroger store
- **Recipe Shopping**: Find recipes and add ingredients to cart

### 📚 Available Tools

#### Location Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `search_locations` | Find Kroger stores near a zip code | No |
| `get_location_details` | Get detailed information about a specific store | No |
| `set_preferred_location` | Set a preferred store for future operations | No |
| `get_preferred_location` | Get the currently set preferred store | No |
| `check_location_exists` | Verify if a location ID is valid | No |

#### Product Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `search_products` | Search for products by name, brand, or other criteria | No |
| `bulk_search_products` | Run up to 25 product searches in a single call | No |
| `get_product_details` | Get detailed product information including pricing | No |
| `search_products_by_id` | Find products by their specific product ID | No |
| `get_product_images` | Get product images from specific perspective (front, back, etc.) | No |

#### Cart Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `add_items_to_cart` | Add a single item to cart | Yes |
| `bulk_add_to_cart` | Add multiple items to cart in one operation | Yes |
| `view_current_cart` | View items currently in your local cart tracking | No |
| `remove_from_cart` | Remove items from local cart tracking | No |
| `clear_current_cart` | Clear all items from local cart tracking | No |
| `mark_order_placed` | Move current cart to order history | No |
| `view_order_history` | View history of placed orders | No |

#### Information Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `list_chains` | Get all Kroger-owned chains | No |
| `get_chain_details` | Get details about a specific chain | No |
| `check_chain_exists` | Check if a chain exists | No |
| `list_departments` | Get all store departments | No |
| `get_department_details` | Get details about a specific department | No |
| `check_department_exists` | Check if a department exists | No |

#### Profile Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `get_user_profile` | Get authenticated user's profile information | Yes |
| `test_authentication` | Check that the user is signed in and the token has not expired, refreshing it if it has | No |
| `get_authentication_info` | Get detailed authentication status | No |
| `force_reauthenticate` | Delete the saved sign-in, so the user can sign in again | No |

`start_authentication` asks the user to grant `cart.basic:write` for the cart tools and `profile.compact` for `get_user_profile`. A sign-in made before version 0.4.0 did not ask for `profile.compact`, so `get_user_profile` fails with `permission_denied` until the user signs in again.

#### Utility Tools

| Tool | Description | Auth Required |
|------|-------------|---------------|
| `get_current_datetime` | Get current system date and time | No |

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

#### Where these files live

State files (cart, order history, preferences) and OAuth tokens are stored in the first matching location:
1. `$KROGER_TOKEN_DIR`, if you set that environment variable
2. `$XDG_DATA_HOME/kroger-mcp/` (defaults to `~/.local/share/kroger-mcp/`) on macOS/Linux
3. `%APPDATA%\kroger-mcp\` on Windows

They are never written to the current working directory, which may be read-only or change between sessions under MCP hosts like Claude Desktop. Files from older versions that live in the working directory are migrated automatically on first use.

Several server processes can share the directory, for example one for Claude Desktop and one for Claude Code. Each change to a state file, and each renewal of the sign-in, holds a lock on that file (a `.lock` file beside it), so the processes do not overwrite each other's changes or sign each other out.

### ⚡ Concurrent calls

Each tool that calls the Kroger API or reads a state file runs in a worker thread, so a slow Kroger request holds up only its own call. The assistant's other calls and cancellation go on, and so do the other clients of a server that uses the `streamable-http` or `sse` transport.

### ⚠️ Error Handling

A tool that fails returns an MCP error result (`isError: true`), so the assistant can see what went wrong and correct its next call:

- **Text content**: what went wrong, followed by `Next step:` and what to do about it, often naming the tool to call.
- **Structured content**: an `error` object with a stable `type`, the `message`, the `next_step`, the `tool`, and every detail the [kroger-api](https://github.com/CupOfOwls/kroger-api) package has about a Kroger API error: `status_code`, Kroger's `kroger_code` and `kroger_message`, the request `method` and `url`, the `correlation_id`, a `hint`, and the `response_body`.

| `type` | When |
|--------|------|
| `invalid_arguments` | An argument breaks the tool's input schema (wrong pattern, out of range, unknown name). `errors` lists each one. No request is sent. |
| `invalid_parameter` | kroger-api rejected a value the schema cannot check, such as a search term of more than 8 words. No request is sent. |
| `authentication_required` | The user is not signed in, or the sign-in expired and could not be renewed. |
| `location_required` | A product tool got no `location_id` and no preferred location is set. |
| `bad_request`, `authentication_error`, `permission_denied`, `not_found`, `rate_limited`, `server_error` | The Kroger API answered 400, 401, 403, 404, 429, or 5xx. |
| `connection_error`, `timeout` | The Kroger API could not be reached, or did not answer within 30 seconds. |
| `configuration_error` | A setting such as `KROGER_CLIENT_ID` is missing or invalid. Fix the server configuration and restart it. |
| `local_state_error` | A cart, order history, or preferences file could not be read or written. |

A cart add that times out, loses its connection after the request may have been sent, or gets a 5xx has `outcome_unknown: true`. Kroger may have added the items anyway, so the next step says to have the user check their cart before adding again, instead of retrying.

A search that finds nothing is not an error: it returns `count: 0` and a message. The full list of error types is in the [MCP tools reference](https://cupofowls.github.io/kroger-api/reference/mcp-tools#error-results).

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

## 🍪 OAuth2 Authentication

When Claude attempts to modify your Kroger account, you will be asked to insert a link into your browser that will handle authentication and allow Claude to add/remove items from your cart. Ensure that you have already made a Kroger account (this is different than your Kroger development account) before attempting to paste this link into your browser to initiate authentication.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## ⚠️ Disclaimer

This is an unofficial MCP server for the Kroger Public API. It is not affiliated with, endorsed by, or sponsored by Kroger.

For questions about the Kroger API, visit the [Kroger Developer Portal](https://developer.kroger.com/) or read the [kroger-api](https://github.com/CupOfOwls/kroger-api) package documentation.

---

<a href="https://mseep.ai/app/cupofowls-kroger-mcp"><img src="https://mseep.net/pr/cupofowls-kroger-mcp-badge.png" alt="MseeP.ai Security Assessment Badge" height="90"></a>
