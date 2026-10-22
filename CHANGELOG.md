# Changelog

All notable changes to the `kroger-mcp` package will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - Unreleased

### Changed

- **Tool failures are MCP error results** (`isError: true`), not successful results with `"success": false`. The text content says what went wrong and the next step to take, so a model that sees only text can recover. The structured content holds an `error` object with a stable `type` (for example `invalid_arguments`, `authentication_required`, `not_found`, `rate_limited`), a `message`, a `next_step` that names the tool to call, and, for Kroger API errors, the HTTP status, Kroger's error code and message, the request, the `X-Correlation-Id`, a hint, and the response body. Before this release an API error returned only "400 Client Error: Bad Request for url: ...". Clients that checked `success == false` must check `isError` instead.
- **Tool schemas declare the valid values**: location IDs (8 letters or digits), product IDs and UPCs (13 digits), ZIP codes (5 digits), department IDs (2 characters), result limits, `quantity` of 1 or more, and `modality` `PICKUP` or `DELIVERY`. A call that breaks them fails before any request, with an `invalid_arguments` error that lists each bad argument. The cart tools used to send a quantity of -5 or a modality of `BOAT` to Kroger.
- **`fulfillment` takes the Kroger API's values**: `ais` (in store), `csp` (curbside pickup), `dth` (delivery to home), and `sth` (ship to home). The previous values `delivery` and `pickup` are not API values, and the API ignored them, so results were not filtered. `dth` was rejected.
- `bulk_search_products` and `bulk_add_to_cart` items have typed fields, and an unknown key is an error (for example `upc` where `product_id` is expected). Every search term and brand is checked before the first search runs. A search that fails gets its own error object in the results. An error that would fail every later search too, such as a rate limit, rejected credentials, or a network failure, stops the remaining searches: they are listed with `searched: false`, the searches that ran are kept, and `stopped_early` gives the reason and next step. The call fails only if no search succeeded.
- `view_order_history` rejects a `limit` outside 1 to 50 instead of clamping it.
- A search that finds nothing is a successful result with `count: 0` and a message. It was `success: false`. A product search at a location ID that does not exist is a `not_found` error: the Products API returns an empty result for it, so the server checks the location when a search comes back empty.
- Warnings in the Products API's `meta.warnings` (for example "The following productIds were not found") are returned as `api_warnings`.
- `get_preferred_location` with no preferred location, and `test_authentication` and `get_authentication_info` when the user is not signed in, return normal results that say so.
- `force_reauthenticate` deletes the saved user token. It only cleared the cached client, so the next call loaded the same token again. Its message no longer says that a browser opens.
- `get_user_zip_code` returns `configured: false` when `KROGER_USER_ZIP_CODE` is not set, because the `10001` it returns then is a placeholder. An invalid `KROGER_USER_ZIP_CODE` is a configuration error.
- `get_product_images` no longer needs a location, because product images are the same at every store.
- `get_product_details` returns the same product fields as the search tools, plus every size of each image: `item` instead of `item_details`, and `number` instead of `aisle_number` in `aisle_locations`. Search results gain `pricing.savings`, and `on_sale` is false when the API sends a `promo` price of 0.
- Store addresses include `street2` in `search_locations` too. A store whose hours lack Monday reports `hours_monday: "Hours not available"`.
- The `kroger-mcp` command takes the same options as `kroger-mcp-cli` (`--transport`, `--zip-code`, and so on); both run `kroger_mcp.cli:main`. `run_server.py` is removed; `python server.py` still works.
- The `KROGER_*` settings in a `.env` file in the working directory are read when the server starts; other variables in the file and `.env` files in parent directories are ignored. The file was read from the directories above the installed package, with every variable in it.
- `kroger_mcp.__version__` reports the installed version. It said 0.1.0.
- **Tools run in worker threads.** They were `async` functions that made blocking HTTP requests, so each Kroger request stopped the whole server until it finished, which the 30-second timeout limits for connecting and for each read but not in total: other tool calls and cancellation waited, and with the `streamable-http` and `sse` transports every client waited on every other. The tools that call Kroger or read state files are now regular functions, which FastMCP runs in worker threads. The cached clients and the sign-in in progress have locks, and each change to the cart tracking, order history, or preferences file holds a lock on that file, so concurrent calls, and other server processes, do not lose each other's changes. Log messages to the client are sent from the worker thread, and one that cannot be sent no longer fails the tool.
- **`KROGER_USER_SCOPES` sets the scopes `start_authentication` requests** (default `product.compact cart.basic:write`, as before). `get_user_profile` needs `profile.compact`, which Kroger's Identity API requires; set `KROGER_USER_SCOPES` to `product.compact cart.basic:write profile.compact` if your app is registered for the Identity API, then sign in again. It is not requested by default, because Kroger refuses the whole sign-in with `invalid_scope` when an app requests a scope it is not registered for. A refused scope and the profile's `permission_denied` error both name the setting in their next step.
- Declares its direct dependency on `anyio`, and no longer depends on `python-dotenv` (kroger-api reads the `.env` file). The unmaintained `requirements.txt`, which asked for kroger-api 0.2.0 and any FastMCP version, is removed; `pyproject.toml` lists the dependencies.
- Requires kroger-api 0.4.0 or later, and FastMCP 3.4.3 or later. Error results need `ToolResult(is_error=...)`, which FastMCP added in 3.4.0, and FastMCP 3.4.3 is the first release that reports invalid arguments as its own `ValidationError`, which the server turns into an `invalid_arguments` error. With FastMCP 3.4.0 to 3.4.2, invalid arguments returned only FastMCP's message, without the structured error or a next step.

### Fixed

- The OAuth `state` was the first 16 characters of the PKCE code verifier, so the authorization URL exposed part of the secret verifier. It is now an independent random value.
- `start_authentication` without `KROGER_REDIRECT_URI` put `redirect_uri=None` in the authorization URL. It now uses the documented default, `http://localhost:8000/callback`.
- `complete_authentication` reports a refused authorization (`error=access_denied` in the redirect URL) instead of "Authorization code not found".
- A new sign-in replaces the cached user client, so cart tools use the new token at once.
- Tool calls no longer refresh the user token or request a new client-credentials token every time (kroger-api 0.4.0 checks the token's expiry instead of probing an endpoint that does not exist). An expired user token is refreshed before a cart call, and a refresh that fails says why.
- A cart, order history, or preferences file that cannot be read or is not valid JSON is a `local_state_error`. It was treated as empty, and the next save overwrote it. A failed write is an error too, where it used to be only a line on stderr. State files are written atomically.
- When the Kroger cart accepts the items but the local cart tracking cannot be updated, for any reason, the result is a success with a `warning`, so a retry does not add the items twice. A cart file whose `current_cart` is not a list of items with integer quantities is a `local_state_error`.
- A cart add that times out, loses its connection after sending, or gets a 5xx has `outcome_unknown: true`, and its next step says not to call the tool again until the user checks the cart, because Kroger may have added the items anyway. Retrying is suggested only when the request certainly did not reach Kroger.
- Two server processes that share the token directory (Claude Desktop and Claude Code, for example), and concurrent tool calls in one process, no longer sign each other out. The sign-in is renewed through kroger-api 0.4.0, which holds a lock on the token file while it renews: a process that waited for the lock uses the token that the other process saved, instead of sending the same refresh token again. A refresh that Kroger rejects because a process without the lock (an earlier version) refreshed first still uses that process's new token.
- `force_reauthenticate` waits for a renewal of the sign-in that is in progress, and a renewal that starts later finds the user signed out, so neither can save the deleted token again. A tool call that runs at the same time cannot keep using the old sign-in either.
- `kroger-mcp-cli` without `--redirect-uri` overrode `KROGER_REDIRECT_URI` with its default.
- State files are written through a temporary file with a unique name, so two server processes never write the same temporary file.
- Product image downloads time out after 30 seconds.

## [0.3.1] - 2026-07-08

### Added

- **Nutrition and allergen data exposed in product tools**: `search_products`, `bulk_search_products`, `get_product_details`, and `search_products_by_id` now return the `allergens`, `nutrition` (ingredient statement, serving size, nutrients), and `warnings` fields that the Kroger Products API 1.3.0 provides. Repeated warning lines are de-duplicated.
- **`additional_info` passthrough**: any product fields the formatter does not model (e.g. `snapEligible`, `ratingsAndReviews`, `allergensDescription`, `productPageURI`) are passed through untouched under `additional_info`, so new Kroger API fields are never silently dropped.

### Changed

- `search_products_by_id` now uses the same product formatter as the other product tools, so its results include full item, aisle, and image data

## [0.3.0] - 2026-07-08

### Added

- `bulk_search_products` tool: run up to 25 product searches in a single call, with shared formatting logic extracted into a `_format_product` helper (thanks @ksletmoe, #20; closes #1)

### Fixed

- **Preferred location, cart, and order history now persist reliably** (fixes #15): all local state files are stored in the same per-user data directory as the OAuth tokens (`$KROGER_TOKEN_DIR`, else `$XDG_DATA_HOME/kroger-mcp/` on Unix / `%APPDATA%\kroger-mcp\` on Windows) instead of the current working directory, which is read-only and/or changes between sessions under MCP hosts like Claude Desktop. Legacy files found in the working directory are migrated automatically.
- `Image` import updated for fastmcp >= 2.8.1 compatibility (thanks @dahifi, #17)
- Warnings are printed to stderr instead of stdout, which could corrupt the stdio MCP transport

### Changed

- **Requires fastmcp 3.x** (tested against 3.4.4) and kroger-api >= 0.3.0
- Added MseeP.ai security assessment badge to the README (thanks @lwsinclair, #6)

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
