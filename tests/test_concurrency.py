"""Tools run in worker threads, so the Kroger requests of concurrent calls overlap

These tests use a Kroger API on localhost instead of requests_mock, which
handles one request at a time.
"""
import asyncio
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest
from fastmcp import Client

from kroger_api.client import KrogerClient
from kroger_api.token_storage import save_token
from kroger_mcp.server import create_server
from kroger_mcp.tools import cart_tools

from conftest import call_ok, save_user_token

CHAINS = {"data": [{"name": "KROGER", "divisionNumbers": ["014"]}]}


class LocalKroger:
    """A Kroger API on localhost

    routes maps (method, path) to a function that takes the request handler
    and returns (status, body); a body of None sends no content. A function
    that raises answers 500.
    """

    def __init__(self):
        self.routes = {}
        self.requests = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def handle_request(self):
                path = urlsplit(self.path).path
                length = int(self.headers.get("Content-Length") or 0)
                self.body = self.rfile.read(length).decode() if length else ""
                server.requests.append((self.command, path, self.headers.get("Authorization")))
                try:
                    status, body = server.routes[(self.command, path)](self)
                except Exception as e:
                    status, body = 500, {"error": f"{type(e).__name__}: {e}"}
                data = b"" if body is None else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = do_PUT = handle_request

            def log_message(self, format, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def calls(self, method, path):
        return [r for r in self.requests if r[:2] == (method, path)]

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def kroger(requests_mock, monkeypatch):
    requests_mock.real_http = True  # requests to the local API are not mocked
    monkeypatch.setenv("NO_PROXY", "*")
    server = LocalKroger()
    monkeypatch.setattr(KrogerClient, "BASE_URL", server.url)
    yield server
    server.close()


@pytest.fixture
def saved_app_token():
    save_token({"access_token": "app", "expires_in": 1800, "expires_at": time.time() + 1800},
               ".kroger_token_client_product.compact.json")


def slow(seconds, status, body):
    def route(request):
        time.sleep(seconds)
        return status, body
    return route


async def test_kroger_requests_of_concurrent_calls_overlap(mcp, kroger, saved_app_token):
    both_arrived = threading.Barrier(2)

    def chains(request):
        # Fails after 5 seconds unless the other call's request arrives meanwhile
        both_arrived.wait(timeout=5)
        return 200, CHAINS

    kroger.routes[("GET", "/v1/chains")] = chains
    results = await asyncio.gather(call_ok(mcp, "list_chains"), call_ok(mcp, "list_chains"))
    assert [r["count"] for r in results] == [1, 1]


async def test_concurrent_first_calls_get_one_app_token(mcp, kroger):
    kroger.routes[("POST", "/v1/connect/oauth2/token")] = slow(0.3, 200, {"access_token": "app", "expires_in": 1800})
    kroger.routes[("GET", "/v1/chains")] = lambda request: (200, CHAINS)
    await asyncio.gather(*(call_ok(mcp, "list_chains") for _ in range(3)))
    assert len(kroger.calls("POST", "/v1/connect/oauth2/token")) == 1
    assert {r[2] for r in kroger.calls("GET", "/v1/chains")} == {"Bearer app"}


async def test_expired_sign_in_is_renewed_once_for_concurrent_calls(mcp, kroger):
    save_user_token(access_token="old", refresh_token="r0", expires_at=time.time() - 60)
    kroger.routes[("POST", "/v1/connect/oauth2/token")] = slow(
        0.3, 200, {"access_token": "renewed", "refresh_token": "r1", "expires_in": 1800})
    kroger.routes[("PUT", "/v1/cart/add")] = lambda request: (204, None)
    await asyncio.gather(*(call_ok(mcp, "add_items_to_cart", {"product_id": f"000111104170{i}"}) for i in range(3)))
    assert len(kroger.calls("POST", "/v1/connect/oauth2/token")) == 1
    assert {r[2] for r in kroger.calls("PUT", "/v1/cart/add")} == {"Bearer renewed"}


async def test_concurrent_cart_adds_keep_every_item_in_the_local_tracking(mcp, kroger, monkeypatch):
    save_user_token()
    kroger.routes[("PUT", "/v1/cart/add")] = lambda request: (204, None)
    load_cart_data = cart_tools._load_cart_data

    def slow_load():
        # Without the lock, each add would read the cart before the other saves it
        data = load_cart_data()
        time.sleep(0.3)
        return data

    monkeypatch.setattr(cart_tools, "_load_cart_data", slow_load)
    products = ["0001111041700", "0001111041701", "0001111041702"]
    await asyncio.gather(*(call_ok(mcp, "add_items_to_cart", {"product_id": p}) for p in products))
    cart = (await call_ok(mcp, "view_current_cart"))["current_cart"]
    assert sorted(item["product_id"] for item in cart) == products


async def test_log_messages_from_the_worker_thread_reach_the_client(requests_mock, app_token):
    from conftest import BASE

    requests_mock.get(f"{BASE}/v1/chains", json=CHAINS)
    messages = []

    async def on_log(message):
        messages.append((message.level, message.data))

    async with Client(create_server(), log_handler=on_log) as client:
        await call_ok(client, "list_chains")
    texts = [data.get("msg") if isinstance(data, dict) else data for _, data in messages]
    assert texts == ["Getting list of Kroger chains", "Found 1 chains"]
    assert {level for level, _ in messages} == {"info"}


async def test_a_log_message_that_cannot_be_sent_never_fails_the_tool(mcp, requests_mock, app_token, monkeypatch):
    from fastmcp import Context

    from conftest import BASE

    async def broken(self, message, *args, **kwargs):
        raise RuntimeError("the client went away")

    monkeypatch.setattr(Context, "info", broken)
    requests_mock.get(f"{BASE}/v1/chains", json=CHAINS)
    assert (await call_ok(mcp, "list_chains"))["count"] == 1
