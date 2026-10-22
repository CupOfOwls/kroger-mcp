"""Tool failures are isError results with structured, actionable details."""
import time
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from fastmcp import FastMCP, Client

from kroger_api import validation
from kroger_api.errors import NotFoundError
from kroger_api.token_storage import load_token
from kroger_mcp.errors import ToolErrorMiddleware
from kroger_mcp.server import create_server
from kroger_mcp.tools import auth_tools, cart_tools, params, shared

from conftest import BASE, TOKEN_URL, call_error, call_ok, kroger_error, save_user_token

PRODUCT = "0001111041700"
STORE = "01400513"


# --- invalid arguments -------------------------------------------------------

INVALID_ARGUMENTS = [
    ("search_products", {"search_term": "milk", "location_id": STORE, "limit": 51}, "limit"),
    ("search_products", {"search_term": "milk", "location_id": STORE, "fulfillment": "delivery"}, "fulfillment"),
    ("search_products", {"search_term": "milk", "location_id": "123"}, "location_id"),
    ("search_products", {"search_term": "ab", "location_id": STORE}, "search_term"),
    ("search_products", {"location_id": STORE}, "search_term"),
    ("bulk_search_products", {"searches": []}, "searches"),
    ("bulk_search_products", {"searches": [{"term": "milk"}] * 26}, "searches"),
    ("bulk_search_products", {"searches": [{"term": "milk", "fulfilment": "csp"}]}, "searches[0].fulfilment"),
    ("get_product_details", {"product_id": "abc", "location_id": STORE}, "product_id"),
    ("search_locations", {"zip_code": "45202-1234"}, "zip_code"),
    ("search_locations", {"zip_code": "45202", "radius_in_miles": 0}, "radius_in_miles"),
    ("get_department_details", {"department_id": "ZZZ"}, "department_id"),
    ("add_items_to_cart", {"product_id": PRODUCT, "quantity": -5}, "quantity"),
    ("add_items_to_cart", {"product_id": PRODUCT, "modality": "pickup"}, "modality"),
    ("bulk_add_to_cart", {"items": [{"upc": PRODUCT}]}, "items[0].product_id"),
    ("bulk_add_to_cart", {"items": [{"product_id": PRODUCT, "quantity": 0}]}, "items[0].quantity"),
    ("view_order_history", {"limit": 0}, "limit"),
]


@pytest.mark.parametrize("tool, arguments, param", INVALID_ARGUMENTS)
async def test_invalid_arguments_are_rejected_before_any_request(mcp, requests_mock, tool, arguments, param):
    error, text = await call_error(mcp, tool, arguments)
    assert error["type"] == "invalid_arguments"
    problem = next(p for p in error["errors"] if p["param"] == param)
    if problem["error_code"].startswith("missing"):
        assert "input" not in problem
    assert f"Invalid arguments for {tool}:" in text
    assert requests_mock.call_count == 0


async def test_kroger_api_validation_reaches_the_caller(mcp, requests_mock):
    # The schema can check only the length; the word count is checked by kroger-api
    error, text = await call_error(mcp, "search_products", {
        "search_term": "one two three four five six seven eight nine", "location_id": STORE})
    assert error["type"] == "invalid_parameter"
    assert error["param"] == "search_term"
    assert "at most 8 words" in error["requirement"]
    assert error["next_step"] == "Correct search_term and call the tool again."
    assert requests_mock.call_count == 0


def test_literal_parameters_match_kroger_api():
    fulfillment = params.Fulfillment.__origin__.__args__[0].__args__
    assert set(fulfillment) == set(validation.FULFILLMENT_TYPES)
    assert set(params.Modality.__origin__.__args__) == set(validation.CART_MODALITIES)


# --- Kroger API errors ---------------------------------------------------------


async def test_bad_request_carries_every_detail(mcp, requests_mock, app_token):
    requests_mock.get(
        f"{BASE}/v1/products",
        status_code=400,
        json=kroger_error("PRODUCT-2011", "Field 'locationId' must have a length of 8 alphanumeric characters"),
        headers={"X-Correlation-Id": "corr-123"},
    )
    error, text = await call_error(mcp, "search_products", {"search_term": "milk", "location_id": STORE})
    assert error["type"] == "bad_request"
    assert error["status_code"] == 400
    assert error["kroger_code"] == "PRODUCT-2011"
    assert error["kroger_message"].startswith("Field 'locationId'")
    assert error["correlation_id"] == "corr-123"
    assert error["method"] == "GET"
    assert "filter.term=milk" in error["url"]
    assert error["response_body"]["errors"]["code"] == "PRODUCT-2011"
    assert "Kroger API error 400 Bad Request" in text
    assert "corr-123" in text


async def test_unknown_location_names_the_tool_to_use(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/locations/99999999", status_code=404)
    error, _ = await call_error(mcp, "get_location_details", {"location_id": "99999999"})
    assert error["type"] == "not_found"
    assert error["status_code"] == 404
    assert "No store has this locationId" in error["hint"]
    assert "search_locations" in error["next_step"]


async def test_rate_limit_says_not_to_retry(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/chains", status_code=429, headers={"Retry-After": "120"},
                      json={"errors": {"code": "Rate-1", "reason": "Too many requests"}})
    error, text = await call_error(mcp, "list_chains")
    assert error["type"] == "rate_limited"
    assert error["retry_after"] == 120
    assert "Do not retry now" in error["next_step"]
    assert "retry after: 120 seconds" in text


async def test_rejected_app_credentials_point_to_the_server_configuration(mcp, requests_mock):
    requests_mock.post(TOKEN_URL, status_code=401,
                       json={"error": "unauthorized", "error_description": "invalid credentials"})
    error, _ = await call_error(mcp, "list_departments")
    assert error["type"] == "authentication_error"
    assert error["kroger_code"] == "unauthorized"
    assert "KROGER_CLIENT_ID and KROGER_CLIENT_SECRET" in error["next_step"]
    assert "restart the MCP server" in error["next_step"]


async def test_missing_credentials_are_a_configuration_error(mcp, requests_mock, monkeypatch):
    monkeypatch.delenv("KROGER_CLIENT_SECRET")
    error, _ = await call_error(mcp, "list_chains")
    assert error["type"] == "configuration_error"
    assert "KROGER_CLIENT_SECRET" in error["message"]
    assert "env block" in error["next_step"]
    assert requests_mock.call_count == 0


async def test_connection_failure_is_reported(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/departments", exc=requests.exceptions.ConnectionError("Name or service not known"))
    error, _ = await call_error(mcp, "list_departments")
    assert error["type"] == "connection_error"
    assert "Name or service not known" in error["reason"]
    assert error["next_step"].startswith("Retry once")


# --- product results that are empty or partial ---------------------------------


async def test_empty_search_at_an_unknown_store_is_an_error(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/products", json={"data": [], "meta": {}})
    requests_mock.head(f"{BASE}/v1/locations/99999999", status_code=404)
    error, _ = await call_error(mcp, "search_products", {"search_term": "milk", "location_id": "99999999"})
    assert error["type"] == "not_found"
    assert error["location_id"] == "99999999"
    assert "search_locations" in error["next_step"]


async def test_empty_search_at_a_real_store_is_a_result(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/products", json={"data": [], "meta": {}})
    requests_mock.head(f"{BASE}/v1/locations/{STORE}", status_code=204)
    result = await call_ok(mcp, "search_products", {"search_term": "zzzzz", "location_id": STORE})
    assert result["count"] == 0
    assert "No products found" in result["message"]


async def test_api_warnings_are_passed_through(mcp, requests_mock, app_token):
    warning = f"The following productIds were not found: {PRODUCT}"
    requests_mock.get(f"{BASE}/v1/products", json={"data": [], "meta": {"warnings": [warning]}})
    requests_mock.head(f"{BASE}/v1/locations/{STORE}", status_code=204)
    result = await call_ok(mcp, "search_products_by_id", {"product_id": PRODUCT, "location_id": STORE})
    assert result["count"] == 0
    assert result["api_warnings"] == [warning]


async def test_bulk_search_reports_each_failed_search(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/products", [
        {"json": {"data": [{"productId": PRODUCT, "description": "Milk"}]}},
        {"status_code": 500, "json": kroger_error("PRODUCT-5000", "Internal error")},
    ])
    result = await call_ok(mcp, "bulk_search_products",
                           {"searches": [{"term": "milk"}, {"term": "bread"}], "location_id": STORE})
    assert result["searches_successful"] == 1
    failed = result["results"][1]
    assert failed["success"] is False
    assert failed["error"]["type"] == "server_error"
    assert failed["error"]["kroger_code"] == "PRODUCT-5000"


async def test_bulk_search_fails_when_every_search_fails(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/products", status_code=500, json=kroger_error("PRODUCT-5000", "Internal error"))
    error, _ = await call_error(mcp, "bulk_search_products",
                                {"searches": [{"term": "milk"}, {"term": "bread"}], "location_id": STORE})
    assert error["type"] == "all_searches_failed"
    assert len(error["results"]) == 2
    assert error["next_step"].startswith("Retry once")


async def test_bulk_search_checks_every_term_before_searching(mcp, requests_mock):
    error, _ = await call_error(mcp, "bulk_search_products", {
        "searches": [{"term": "milk"}, {"term": "a  b c d e f g h"}], "location_id": STORE})
    assert error["type"] == "invalid_parameter"
    assert error["param"] == "searches[1].term"
    assert requests_mock.call_count == 0


async def test_no_location_and_no_preference(mcp, requests_mock):
    error, _ = await call_error(mcp, "search_products", {"search_term": "milk"})
    assert error["type"] == "location_required"
    assert "set_preferred_location" in error["next_step"]
    assert requests_mock.call_count == 0


async def test_missing_image_perspective_lists_the_available_ones(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/products/{PRODUCT}", json={"data": {"productId": PRODUCT, "images": [
        {"perspective": "front", "sizes": [{"size": "large", "url": "https://img/front.jpg"}]},
        {"perspective": "back", "sizes": [{"size": "large", "url": "https://img/back.jpg"}]},
    ]}})
    error, _ = await call_error(mcp, "get_product_images", {"product_id": PRODUCT, "perspective": "top"})
    assert error["type"] == "invalid_parameter"
    assert error["available_perspectives"] == ["front", "back"]


async def test_failed_image_download_is_reported(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/products/{PRODUCT}", json={"data": {"productId": PRODUCT, "images": [
        {"perspective": "front", "sizes": [{"size": "large", "url": "https://img.example/front.jpg"}]},
    ]}})
    requests_mock.get("https://img.example/front.jpg", status_code=503)
    error, _ = await call_error(mcp, "get_product_images", {"product_id": PRODUCT})
    assert error["type"] == "image_download_failed"
    assert error["status_code"] == 503


# --- user authentication -------------------------------------------------------


async def test_cart_without_sign_in_asks_for_it(mcp, requests_mock):
    error, _ = await call_error(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert error["type"] == "authentication_required"
    assert "start_authentication" in error["next_step"]
    assert requests_mock.call_count == 0


async def test_expired_sign_in_is_refreshed_before_the_cart_call(mcp, requests_mock):
    save_user_token(expires_at=time.time() - 10)
    refresh = requests_mock.post(TOKEN_URL, json={"access_token": "renewed", "expires_in": 1800})
    cart = requests_mock.put(f"{BASE}/v1/cart/add", status_code=204)
    await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert "grant_type=refresh_token" in refresh.last_request.text
    assert cart.last_request.headers["Authorization"] == "Bearer renewed"


async def test_expired_sign_in_that_cannot_be_renewed(mcp, requests_mock):
    save_user_token(expires_at=time.time() - 10)
    requests_mock.post(TOKEN_URL, status_code=400,
                       json={"error": "invalid_grant", "error_description": "invalid refresh_token"})
    error, _ = await call_error(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert error["type"] == "authentication_required"
    assert "invalid refresh_token" in error["message"]
    assert error["kroger_code"] == "invalid_grant"


async def test_cart_403_asks_for_a_user_sign_in(mcp, requests_mock):
    save_user_token()
    requests_mock.put(f"{BASE}/v1/cart/add", status_code=403,
                      json={"code": "AUTH-1007", "reason": "Invalid token on request", "timestamp": 1})
    error, _ = await call_error(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert error["type"] == "permission_denied"
    assert error["kroger_code"] == "AUTH-1007"
    assert "start_authentication" in error["next_step"]


async def test_status_tools_report_a_missing_sign_in_as_data(mcp, requests_mock):
    result = await call_ok(mcp, "test_authentication")
    assert result["token_valid"] is False
    result = await call_ok(mcp, "get_authentication_info")
    assert result["authenticated"] is False


async def test_force_reauthenticate_deletes_the_saved_token(mcp, requests_mock):
    save_user_token()
    await call_ok(mcp, "force_reauthenticate")
    assert load_token(shared.USER_TOKEN_FILE) is None
    error, _ = await call_error(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert error["type"] == "authentication_required"


async def test_start_authentication_uses_an_independent_state(mcp, requests_mock):
    result = await call_ok(mcp, "start_authentication")
    query = parse_qs(urlparse(result["auth_url"]).query)
    state = query["state"][0]
    assert state == auth_tools._auth_state
    assert state not in auth_tools._pkce_params["code_verifier"]
    assert query["redirect_uri"] == [auth_tools.DEFAULT_REDIRECT_URI]


async def test_sign_in_requests_only_the_cart_scopes_by_default(mcp, requests_mock):
    """An app that is not registered for the Identity API could not sign in at all if profile.compact were requested"""
    result = await call_ok(mcp, "start_authentication")
    query = parse_qs(urlparse(result["auth_url"]).query)
    assert query["scope"] == ["product.compact cart.basic:write"]
    assert result["scope"] == "product.compact cart.basic:write"
    assert query["code_challenge_method"] == ["S256"]


@pytest.mark.parametrize("setting", ["product.compact cart.basic:write profile.compact",
                                     " product.compact, cart.basic:write,profile.compact cart.basic:write "])
async def test_sign_in_requests_the_scopes_in_kroger_user_scopes(mcp, requests_mock, monkeypatch, setting):
    monkeypatch.setenv("KROGER_USER_SCOPES", setting)
    result = await call_ok(mcp, "start_authentication")
    query = parse_qs(urlparse(result["auth_url"]).query)
    assert query["scope"] == ["product.compact cart.basic:write profile.compact"]
    assert result["scope"] == "product.compact cart.basic:write profile.compact"


async def test_refused_scope_explains_kroger_user_scopes(mcp, requests_mock, monkeypatch):
    monkeypatch.setenv("KROGER_USER_SCOPES", "product.compact cart.basic:write profile.compact")
    await call_ok(mcp, "start_authentication")
    error, _ = await call_error(mcp, "complete_authentication", {
        "redirect_url": "http://localhost:8000/callback?error=invalid_scope&error_description=invalid+scope"})
    assert error["type"] == "authorization_failed"
    assert "(product.compact cart.basic:write profile.compact)" in error["next_step"]
    assert "remove the scope from KROGER_USER_SCOPES" in error["next_step"]
    assert "Kroger Developer Portal" in error["next_step"]


async def test_profile_403_explains_how_to_get_the_profile_scope(mcp, requests_mock):
    save_user_token()
    requests_mock.get(f"{BASE}/v1/identity/profile", status_code=403,
                      json={"code": "AUTH-1007", "reason": "Invalid scope on request", "timestamp": 1})
    error, _ = await call_error(mcp, "get_user_profile")
    assert error["type"] == "permission_denied"
    assert "registered for the Identity API" in error["next_step"]
    assert "KROGER_USER_SCOPES to 'product.compact cart.basic:write profile.compact'" in error["next_step"]
    assert "call start_authentication and have the user sign in again" in error["next_step"]


async def test_profile_returns_the_profile_id(mcp, requests_mock):
    save_user_token()
    requests_mock.get(f"{BASE}/v1/identity/profile", json={"data": {"id": "user-1"}})
    result = await call_ok(mcp, "get_user_profile")
    assert result["profile_id"] == "user-1"
    assert requests_mock.last_request.headers["Authorization"] == "Bearer user"


async def test_complete_authentication_before_start(mcp, requests_mock):
    error, _ = await call_error(mcp, "complete_authentication",
                                {"redirect_url": "http://localhost:8000/callback?code=abc&state=x"})
    assert error["type"] == "authentication_not_started"


async def test_complete_authentication_reports_a_refusal(mcp, requests_mock):
    await call_ok(mcp, "start_authentication")
    error, _ = await call_error(mcp, "complete_authentication", {
        "redirect_url": "http://localhost:8000/callback?error=access_denied&error_description=User+denied+access"})
    assert error["type"] == "authorization_failed"
    assert error["oauth_error"] == "access_denied"
    assert "User denied access" in error["message"]


async def test_complete_authentication_without_code(mcp, requests_mock):
    await call_ok(mcp, "start_authentication")
    error, _ = await call_error(mcp, "complete_authentication", {"redirect_url": "http://localhost:8000/callback"})
    assert error["type"] == "invalid_redirect_url"


async def test_complete_authentication_with_another_state(mcp, requests_mock):
    await call_ok(mcp, "start_authentication")
    error, _ = await call_error(mcp, "complete_authentication",
                                {"redirect_url": "http://localhost:8000/callback?code=abc&state=other"})
    assert error["type"] == "state_mismatch"
    assert requests_mock.call_count == 0


async def test_complete_authentication_with_a_rejected_code(mcp, requests_mock):
    await call_ok(mcp, "start_authentication")
    requests_mock.post(TOKEN_URL, status_code=400, json={"error": "invalid_grant", "error_description": "invalid code"})
    error, _ = await call_error(mcp, "complete_authentication", {
        "redirect_url": f"http://localhost:8000/callback?code=abc&state={auth_tools._auth_state}"})
    assert error["type"] == "bad_request"
    assert "start_authentication again" in error["next_step"]


async def test_new_sign_in_replaces_the_cached_client(mcp, requests_mock):
    save_user_token(access_token="old")
    cart = requests_mock.put(f"{BASE}/v1/cart/add", status_code=204)
    await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert cart.last_request.headers["Authorization"] == "Bearer old"

    await call_ok(mcp, "start_authentication")
    requests_mock.post(TOKEN_URL, json={"access_token": "new", "refresh_token": "r", "expires_in": 1800})
    await call_ok(mcp, "complete_authentication", {
        "redirect_url": f"http://localhost:8000/callback?code=abc&state={auth_tools._auth_state}"})
    await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert cart.last_request.headers["Authorization"] == "Bearer new"


# --- local state ---------------------------------------------------------------


async def test_corrupt_cart_file_is_reported_and_kept(mcp, isolated):
    cart_file = isolated / cart_tools.CART_FILE
    cart_file.write_text("{not json")
    error, _ = await call_error(mcp, "view_current_cart")
    assert error["type"] == "local_state_error"
    assert error["path"] == str(cart_file)
    assert cart_file.read_text() == "{not json"


async def test_cart_state_of_the_wrong_type_is_reported(mcp, isolated):
    (isolated / cart_tools.CART_FILE).write_text("[]")
    error, _ = await call_error(mcp, "clear_current_cart")
    assert error["type"] == "local_state_error"
    assert "JSON list, not a JSON dict" in error["message"]


async def test_local_tracking_failure_after_a_cart_add_is_a_warning(mcp, requests_mock, isolated):
    save_user_token()
    requests_mock.put(f"{BASE}/v1/cart/add", status_code=204)
    (isolated / cart_tools.CART_FILE).write_text("{not json")
    result = await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert "Do not add the items again" in result["warning"]


async def test_preferred_location_that_cannot_be_saved(mcp, requests_mock, app_token, monkeypatch):
    requests_mock.get(f"{BASE}/v1/locations/{STORE}", json={"data": {"locationId": STORE, "name": "Kroger"}})

    real_replace = shared.os.replace

    def fail_for_preferences(source, target):
        # Token files are saved with os.replace too; only the state file write fails
        if str(target).endswith(shared.PREFERENCES_FILE):
            raise PermissionError(13, "Permission denied")
        real_replace(source, target)

    monkeypatch.setattr(shared.os, "replace", fail_for_preferences)
    error, _ = await call_error(mcp, "set_preferred_location", {"location_id": STORE})
    assert error["type"] == "local_state_error"
    assert "Permission denied" in error["message"]


async def test_no_preferred_location_is_a_result(mcp):
    result = await call_ok(mcp, "get_preferred_location")
    assert result["preferred_location_id"] is None


async def test_mark_order_placed_with_an_empty_cart(mcp):
    error, _ = await call_error(mcp, "mark_order_placed")
    assert error["type"] == "empty_cart"


async def test_unset_zip_code_is_marked_as_a_placeholder(mcp):
    result = await call_ok(mcp, "get_user_zip_code")
    assert result["configured"] is False
    assert "placeholder" in result["message"]


async def test_invalid_zip_code_setting_is_a_configuration_error(mcp, requests_mock, monkeypatch):
    monkeypatch.setenv("KROGER_USER_ZIP_CODE", "45202-1234")
    error, _ = await call_error(mcp, "search_locations")
    assert error["type"] == "configuration_error"
    assert error["setting"] == "KROGER_USER_ZIP_CODE"
    assert requests_mock.call_count == 0


# --- the error plumbing itself -------------------------------------------------


async def test_unexpected_exception_is_an_internal_error(mcp, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(cart_tools, "_load_cart_data", broken)
    error, _ = await call_error(mcp, "view_current_cart")
    assert error["type"] == "internal_error"
    assert error["exception_type"] == "RuntimeError"
    assert "boom" in error["message"]


async def test_middleware_handles_a_tool_without_translate_errors(requests_mock):
    requests_mock.get(f"{BASE}/v1/chains/NOPE", status_code=404)
    response = requests.get(f"{BASE}/v1/chains/NOPE")

    server = FastMCP("test")
    server.add_middleware(ToolErrorMiddleware())

    @server.tool()
    async def lookup_chain() -> dict:
        raise NotFoundError(response)

    async with Client(server) as client:
        error, _ = await call_error(client, "lookup_chain")
    assert error["type"] == "not_found"
    assert error["status_code"] == 404
    assert error["next_step"] == "Get the valid chain names with list_chains."


async def test_every_tool_translates_errors():
    tools = await create_server().list_tools()
    assert len(tools) == 31
    for tool in tools:
        assert hasattr(tool.fn, "__wrapped__"), f"{tool.name} is missing @translate_errors"
