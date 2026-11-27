"""The MCP server's only link to the Haat app: its /api, called as the signed-in buyer, plus the token check.

The app owns everything (accounts, carts, prices, the words shown); this module passes calls through and turns
an app that is down, or that refuses a call, into one readable line for the model."""
import hashlib
import os
import time

import httpx2 as httpx  # the HTTP client the MCP SDK ships with
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError

HAAT_URL = os.environ.get("HAAT_URL", "http://localhost:5174").rstrip("/")  # the site: it signs buyers in (OAuth issuer)
# Where this server calls the API: Django itself, not through the site's dev proxy, so "down" reads as down.
HAAT_API = os.environ.get("HAAT_API", "http://127.0.0.1:8000/api").rstrip("/")
API_ORIGIN = "/".join(HAAT_API.split("/")[:3])
MCP_URL = os.environ.get("MCP_RESOURCE_URL", "http://127.0.0.1:8100/mcp")  # must equal the backend's MCP_RESOURCE_URL
VERIFY_SECONDS = 60  # a revoked sign-in or a disabled account stops working within this long
DOWN = f"The Haat app is not reachable at {API_ORIGIN}. Start it and try again."
TRANSPORT = None  # tests put an httpx.MockTransport here


def new_client():
    # Django's CSRF check on cart and order changes wants the API's own origin.
    return httpx.AsyncClient(base_url=HAAT_API, timeout=10, transport=TRANSPORT,
                             headers={"Origin": API_ORIGIN, "Referer": f"{API_ORIGIN}/"})


def down(res):
    """Nothing answered, or only a proxy in front of the app did (Vite in dev, nginx in production)."""
    return res is None or res.status_code in (502, 503, 504)


def first_message(res):
    try:
        body = res.json()
    except ValueError:
        return None
    return body.get("message") if isinstance(body, dict) else None


# The cart lives in the app's session cookie, so each buyer keeps one cookie jar here.
# shortcut: in memory, so restarting this server empties AI carts; move carts onto the account to keep them.
_jars: dict[str, httpx.AsyncClient] = {}


async def call(token: AccessToken, method: str, path: str, **kwargs):
    """One API call as the token's buyer. Returns the JSON body; raises ToolError with the app's own message."""
    jar = token.subject or token.token  # a token left unchecked while the app was down keeps its own jar
    if jar not in _jars:
        _jars[jar] = new_client()
    http = _jars[jar]
    headers = {"Authorization": f"Bearer {token.token}"}
    if method != "GET":
        if "csrftoken" not in http.cookies:
            await call(token, "GET", "/cart/")  # the app hands out its CSRF cookie with the cart
        headers["X-CSRFToken"] = http.cookies["csrftoken"]
    try:
        res = await http.request(method, path, headers=headers, **kwargs)
    except httpx.TransportError:
        res = None
    if down(res):
        raise ToolError(DOWN)
    if res.is_error:
        if res.status_code == 401:
            verifier.forget(token.token)
        raise ToolError(first_message(res) or f"The Haat app had an error ({res.status_code}). Try again later.")
    return res.json() if res.content else None


class Verifier:
    """MCP's token check: asks the app who the token belongs to, then trusts the answer for VERIFY_SECONDS."""

    def __init__(self):
        self.seen: dict[str, tuple[AccessToken, float]] = {}

    def forget(self, token):
        self.seen.pop(hashlib.sha256(token.encode()).hexdigest(), None)

    async def verify_token(self, token: str) -> AccessToken | None:
        key, now = hashlib.sha256(token.encode()).hexdigest(), time.monotonic()
        if (hit := self.seen.get(key)) and now - hit[1] < VERIFY_SECONDS:
            return hit[0]
        try:
            async with new_client() as http:
                res = await http.get("/auth/me/", headers={"Authorization": f"Bearer {token}"})
        except httpx.TransportError:
            res = None
        if down(res) or res.status_code >= 500:
            # The app can't say now. Let the call through so the tool can tell the model the app is down:
            # every tool needs the app, so an unchecked token gets nothing from it.
            return AccessToken(token=token, client_id="", scopes=["shop"], resource=MCP_URL)
        if res.status_code != 200:
            self.forget(token)
            return None
        me = res.json()
        if "client_id" not in me:  # the site's own login token, not an AI app's
            return None
        # A token with no RFC 8707 resource was still issued by Haat to an app it registered: it is ours.
        resource = MCP_URL if MCP_URL in (me["resource"] or [MCP_URL]) else None
        found = AccessToken(token=token, client_id=me["client_id"], scopes=me["scopes"], expires_at=me["expires"],
                            resource=resource, subject=str(me["id"]))
        if len(self.seen) > 10_000:  # drop stale entries so the cache stays bounded
            self.seen = {k: v for k, v in self.seen.items() if now - v[1] < VERIFY_SECONDS}
        self.seen[key] = (found, now)
        return found


verifier = Verifier()
