"""Run: .venv/bin/python -m unittest discover tests. No Haat app needed: its /api is faked with MockTransport."""
import json
import unittest

import httpx2 as httpx
from mcp import Client
from mcp.server.auth.middleware.auth_context import auth_context_var
from mcp.server.auth.middleware.bearer_auth import AuthenticatedUser
from mcp.server.auth.provider import AccessToken

from haat_mcp import app
from haat_mcp.server import mcp

CART = {"lines": [], "subtotal_display": "৳0", "delivery_display": "৳60", "total_display": "৳60", "total": 60,
        "meter": "Add ৳299 more for free delivery.", "notice": None}
ME = {"id": 7, "username": "rahim", "client_id": "c1", "scopes": ["shop"], "resource": [app.MCP_URL],
      "expires": 4102444800}


def fake(handler):
    """Route the app's /api to `handler(request)`; returns the list of requests it saw."""
    seen = []

    def record(request):
        seen.append(request)
        return handler(request)
    app.TRANSPORT = httpx.MockTransport(record)
    app._jars.clear()
    app.verifier.seen.clear()
    return seen


def down(request):
    raise httpx.ConnectError("connection refused", request=request)


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def call(self, tool, args=None, user="7"):
        token = auth_context_var.set(AuthenticatedUser(AccessToken(token=f"tok-{user}", client_id="c1", scopes=["shop"],
                                                                   subject=user)))
        try:
            async with Client(mcp) as client:  # in-process; the server's tasks inherit the signed-in buyer
                return await client.call_tool(tool, args or {})
        finally:
            auth_context_var.reset(token)

    def text(self, result):
        return result.content[0].text.split(": ", 1)[-1]  # the SDK puts "Error executing tool <name>: " first

    async def test_app_down_says_so(self):
        fake(down)
        result = await self.call("view_cart")
        self.assertTrue(result.is_error)
        self.assertEqual(self.text(result), app.DOWN)

    async def test_proxy_up_app_down_says_so(self):
        fake(lambda r: httpx.Response(502))
        self.assertEqual(self.text(await self.call("my_orders")), app.DOWN)

    async def test_the_apps_refusal_reaches_the_model(self):
        def handler(r):
            if r.url.path == "/api/cart/":
                return httpx.Response(200, json={**CART, "lines": [{"id": "1"}]}, headers={"Set-Cookie": "csrftoken=abc; Path=/"})
            return httpx.Response(400, json={"message": "Your cart changed. Check it and try again."})
        fake(handler)
        result = await self.call("checkout", {"full_name": "R", "phone": "017", "address": "A", "city": "Dhaka",
                                              "expected_total": 60})
        self.assertTrue(result.is_error)
        self.assertEqual(self.text(result), "Your cart changed. Check it and try again.")

    async def test_writes_send_the_buyers_token_and_csrf(self):
        def handler(r):
            if r.url.path == "/api/products/rice/":
                return httpx.Response(200, json={"id": 3})
            return httpx.Response(200, json=CART, headers={"Set-Cookie": "csrftoken=abc; Path=/"})
        seen = fake(handler)
        result = await self.call("add_to_cart", {"slug": "rice", "quantity": 2})
        self.assertFalse(result.is_error, self.text(result))
        post = seen[-1]
        self.assertEqual((post.method, post.url.path), ("POST", "/api/cart/"))
        self.assertEqual(post.headers["X-CSRFToken"], "abc")
        self.assertEqual(post.headers["Authorization"], "Bearer tok-7")
        self.assertEqual(post.headers["Origin"], app.API_ORIGIN)
        self.assertEqual(json.loads(post.content), {"product": 3, "quantity": 2, "options": {}})

    async def test_each_buyer_has_their_own_cart(self):
        def handler(r):
            return httpx.Response(200, json=CART, headers={"Set-Cookie": f"sessionid=s-{r.headers['Authorization'][-1]}; Path=/"})
        seen = fake(handler)
        await self.call("view_cart", user="7")
        await self.call("view_cart", user="8")
        await self.call("view_cart", user="7")
        self.assertNotIn("cookie", seen[1].headers)  # buyer 8 never gets buyer 7's session
        self.assertEqual(seen[2].headers["cookie"], "sessionid=s-7")


class VerifierTests(unittest.IsolatedAsyncioTestCase):
    async def test_asks_the_app_who_the_token_is(self):
        seen = fake(lambda r: httpx.Response(200, json=ME))
        found = await app.verifier.verify_token("t1")
        self.assertEqual((found.subject, found.resource, found.scopes), ("7", app.MCP_URL, ["shop"]))
        self.assertEqual(seen[0].headers["Authorization"], "Bearer t1")
        await app.verifier.verify_token("t1")
        self.assertEqual(len(seen), 1)  # cached

    async def test_refused_tokens(self):
        fake(lambda r: httpx.Response(401, json={"message": "This app was signed out."}))
        self.assertIsNone(await app.verifier.verify_token("t1"))
        fake(lambda r: httpx.Response(200, json={"id": 7, "username": "rahim"}))  # the site's own login token
        self.assertIsNone(await app.verifier.verify_token("t1"))
        fake(lambda r: httpx.Response(200, json={**ME, "resource": ["https://other.example/"]}))
        self.assertIsNone((await app.verifier.verify_token("t1")).resource)  # MCP then refuses it

    async def test_app_down_lets_the_tool_say_so(self):
        fake(down)
        found = await app.verifier.verify_token("t1")
        self.assertIsNone(found.subject)
        with self.assertRaisesRegex(Exception, "not reachable"):
            await app.call(found, "GET", "/cart/")


class SignInRequiredTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_token_no_server(self):
        fake(lambda r: httpx.Response(401))
        asgi = httpx.ASGITransport(app=mcp.streamable_http_app())
        async with httpx.AsyncClient(transport=asgi, base_url="http://127.0.0.1:8100") as http:
            res = await http.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            self.assertEqual(res.status_code, 401)
            self.assertIn("resource_metadata=", res.headers["WWW-Authenticate"])
            res = await http.post("/mcp", headers={"Authorization": "Bearer bad"}, json={"jsonrpc": "2.0", "id": 1})
            self.assertEqual(res.status_code, 401)
            meta = (await http.get("/.well-known/oauth-protected-resource/mcp")).json()
            self.assertEqual(meta["authorization_servers"], [app.HAAT_URL])  # exactly the issuer: RFC 8414 compares strings


if __name__ == "__main__":
    unittest.main()
