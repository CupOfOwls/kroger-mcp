"""Cart writes whose outcome is unknown, shared sign-ins, bulk search stops, and the entry points"""
import json
import sys
import time

import pytest
import requests

from kroger_api.token_storage import save_token
from kroger_mcp.tools import cart_tools, shared

from conftest import BASE, TOKEN_URL, call_error, call_ok, kroger_error, save_user_token

PRODUCT = "0001111041700"
STORE = "01400513"
CART_URL = f"{BASE}/v1/cart/add"


# --- a cart add whose outcome is unknown must not be retried --------------------


@pytest.mark.parametrize("response", [
    {"exc": requests.exceptions.ReadTimeout("read timed out")},
    {"exc": requests.exceptions.ConnectionError("Connection aborted: RemoteDisconnected")},
    {"status_code": 504, "text": ""},
])
async def test_cart_add_with_an_unknown_outcome_says_not_to_retry(mcp, requests_mock, response):
    save_user_token()
    requests_mock.put(CART_URL, **response)
    for tool, arguments in [("add_items_to_cart", {"product_id": PRODUCT}),
                            ("bulk_add_to_cart", {"items": [{"product_id": PRODUCT}]})]:
        error, _ = await call_error(mcp, tool, arguments)
        assert error["outcome_unknown"] is True
        assert error["next_step"].startswith("Do not call the tool again yet")
        assert "Retry" not in error["next_step"]
    # Neither add was recorded in the local cart tracking
    assert (await call_ok(mcp, "view_current_cart"))["current_cart"] == []


async def test_cart_add_that_never_connected_can_be_retried(mcp, requests_mock):
    save_user_token()
    requests_mock.put(CART_URL, exc=requests.exceptions.ConnectTimeout("connect timed out"))
    error, _ = await call_error(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert error["outcome_unknown"] is False
    assert error["next_step"].startswith("Retry once")


async def test_read_timeout_can_still_be_retried(mcp, requests_mock, app_token):
    requests_mock.get(f"{BASE}/v1/chains", exc=requests.exceptions.ReadTimeout("read timed out"))
    error, _ = await call_error(mcp, "list_chains")
    assert error["outcome_unknown"] is False
    assert error["next_step"].startswith("Retry once")


# --- a cart file of the wrong shape ------------------------------------------------


@pytest.mark.parametrize("cart", [
    {"current_cart": None},
    {"current_cart": ["not an item"]},
    {"current_cart": [{"product_id": PRODUCT, "quantity": "2", "modality": "PICKUP"}]},
])
async def test_cart_file_of_the_wrong_shape_never_fails_a_cart_add(mcp, requests_mock, isolated, cart):
    save_user_token()
    cart_put = requests_mock.put(CART_URL, status_code=204)
    (isolated / cart_tools.CART_FILE).write_text(json.dumps(cart))

    result = await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert "Do not add the items again" in result["warning"]
    result = await call_ok(mcp, "bulk_add_to_cart", {"items": [{"product_id": PRODUCT}]})
    assert "Do not add the items again" in result["warning"]
    assert cart_put.call_count == 2

    error, _ = await call_error(mcp, "view_current_cart")
    assert error["type"] == "local_state_error"
    assert "current_cart" in error["message"]


# --- a sign-in shared by two server processes --------------------------------------


async def test_sign_in_refreshed_by_another_process_is_used(mcp, requests_mock):
    """Process B refreshed and rotated the refresh token, so this process's copy is rejected"""
    save_user_token(access_token="old", refresh_token="refresh-1", expires_at=time.time() + 1800)
    requests_mock.put(CART_URL, status_code=204)
    await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})  # caches the client

    # The cached token expires; meanwhile process B saves a renewed token
    shared._authenticated_client.client.token_info["expires_at"] = time.time() - 10
    save_user_token(access_token="from-b", refresh_token="refresh-2", expires_at=time.time() + 1800)
    token_requests = requests_mock.post(TOKEN_URL, status_code=400,
                                        json={"error": "invalid_request", "error_description": "invalid refresh_token"})

    await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert requests_mock.last_request.headers["Authorization"] == "Bearer from-b"
    assert token_requests.call_count == 0


async def test_simultaneous_refresh_by_another_process_is_used(mcp, requests_mock):
    """Both processes refreshed at once; the other one won, so this one's refresh is rejected"""
    save_user_token(access_token="old", refresh_token="refresh-1", expires_at=time.time() - 10)

    def token_response(request, context):
        # Process B saves its renewed token just before Kroger rejects this refresh
        save_token({"access_token": "from-b", "refresh_token": "refresh-2", "expires_in": 1800,
                    "expires_at": time.time() + 1800}, shared.USER_TOKEN_FILE)
        context.status_code = 400
        return {"error": "invalid_request", "error_description": "invalid refresh_token"}

    requests_mock.post(TOKEN_URL, json=token_response)
    requests_mock.put(CART_URL, status_code=204)
    await call_ok(mcp, "add_items_to_cart", {"product_id": PRODUCT})
    assert requests_mock.last_request.headers["Authorization"] == "Bearer from-b"


# --- bulk search stops on errors that would fail every search -----------------------


async def test_bulk_search_keeps_earlier_results_when_rate_limited(mcp, requests_mock, app_token):
    products = requests_mock.get(f"{BASE}/v1/products", [
        {"json": {"data": [{"productId": PRODUCT, "description": "Milk"}]}},
        {"status_code": 429, "json": kroger_error("PRODUCT-4290", "Too many requests")},
    ])
    result = await call_ok(mcp, "bulk_search_products", {
        "searches": [{"term": "milk"}, {"term": "bread"}, {"term": "eggs"}], "location_id": STORE})
    assert products.call_count == 2
    assert result["searches_successful"] == 1 and result["searches_completed"] == 2
    assert result["results"][0]["count"] == 1
    assert result["results"][1]["error"]["type"] == "rate_limited"
    assert result["results"][2] == {"term": "eggs", "success": False, "searched": False, "data": []}
    assert result["stopped_early"]["error_type"] == "rate_limited"
    assert "Do not retry" in result["stopped_early"]["next_step"]


async def test_bulk_search_stops_at_the_first_network_failure(mcp, requests_mock, app_token):
    products = requests_mock.get(f"{BASE}/v1/products", exc=requests.exceptions.ConnectionError("Network is unreachable"))
    error, _ = await call_error(mcp, "bulk_search_products", {
        "searches": [{"term": "milk"}, {"term": "bread"}, {"term": "eggs"}], "location_id": STORE})
    assert products.call_count == 1
    assert error["type"] == "connection_error"
    assert [r.get("searched", True) for r in error["results"]] == [True, False, False]


async def test_bulk_search_checks_every_brand_before_searching(mcp, requests_mock, app_token):
    products = requests_mock.get(f"{BASE}/v1/products", json={"data": []})
    error, _ = await call_error(mcp, "bulk_search_products", {
        "searches": [{"term": "milk"}, {"term": "bread", "brand": "  "}, {"term": "eggs"}], "location_id": STORE})
    assert products.call_count == 0
    assert error["type"] == "invalid_parameter"
    assert error["param"] == "searches[1].brand"


async def test_invalid_parameter_in_one_search_does_not_stop_the_others(mcp, requests_mock, app_token, monkeypatch):
    from kroger_api.api.product import ProductAPI
    from kroger_api.errors import InvalidParameterError

    original = ProductAPI.search_products

    def search_products(self, term=None, **kwargs):
        if term == "bread":
            raise InvalidParameterError("limit", 99, "must be from 1 to 50")
        return original(self, term=term, **kwargs)

    monkeypatch.setattr(ProductAPI, "search_products", search_products)
    requests_mock.get(f"{BASE}/v1/products", json={"data": [{"productId": PRODUCT, "description": "Milk"}]})
    result = await call_ok(mcp, "bulk_search_products", {
        "searches": [{"term": "milk"}, {"term": "bread"}, {"term": "eggs"}], "location_id": STORE})
    assert [r["success"] for r in result["results"]] == [True, False, True]
    assert result["results"][1]["error"]["type"] == "invalid_parameter"
    assert "stopped_early" not in result


# --- formatting, entry points, and package metadata ---------------------------------


async def test_product_details_use_the_search_result_fields(mcp, requests_mock, app_token):
    product = {
        "productId": PRODUCT, "description": "Milk",
        "items": [{"size": "1 gal", "price": {"regular": 3.29, "promo": 2.99}}],
        "aisleLocations": [{"description": "Dairy", "number": "12"}],
        "images": [{"perspective": "front", "sizes": [{"size": "large", "url": "https://img/l.jpg"},
                                                       {"size": "small", "url": "https://img/s.jpg"}]}],
    }
    requests_mock.get(f"{BASE}/v1/products/{PRODUCT}", json={"data": product})
    requests_mock.get(f"{BASE}/v1/products", json={"data": [product]})
    details = await call_ok(mcp, "get_product_details", {"product_id": PRODUCT, "location_id": STORE})
    found = (await call_ok(mcp, "search_products", {"search_term": "milk", "location_id": STORE}))["data"][0]

    assert details["item"] == found["item"]
    assert details["pricing"] == found["pricing"]
    assert details["pricing"]["on_sale"] is True and details["pricing"]["savings"] == 0.3
    assert details["aisle_locations"] == found["aisle_locations"]
    assert [s["size"] for s in details["images"][0]["sizes"]] == ["large", "small"]
    assert found["images"][0]["url"] == "https://img/l.jpg"
    assert details["location_id"] == STORE


def test_redirect_uri_setting_is_not_overridden_by_the_cli(monkeypatch):
    from kroger_mcp import cli

    monkeypatch.setenv("KROGER_REDIRECT_URI", "http://localhost:9000/callback")
    monkeypatch.setattr(sys, "argv", ["kroger-mcp"])
    monkeypatch.setattr("kroger_mcp.server.FastMCP.run", lambda self, *args, **kwargs: None)
    cli.main()
    import os
    assert os.environ["KROGER_REDIRECT_URI"] == "http://localhost:9000/callback"


def test_both_commands_run_the_same_entry_point():
    from pathlib import Path

    pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text()
    assert 'kroger-mcp = "kroger_mcp.cli:main"' in pyproject
    assert 'kroger-mcp-cli = "kroger_mcp.cli:main"' in pyproject


def test_package_version_matches_the_installed_metadata():
    from importlib.metadata import version

    import kroger_mcp
    assert kroger_mcp.__version__ == version("kroger-mcp")
