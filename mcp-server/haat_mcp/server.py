"""Haat's MCP server: tools a buyer's AI app uses to shop at Haat, each a few calls to the app's /api.

Every request needs the buyer's sign-in (OAuth, issued by the Haat app itself), so nothing here works for a
guest. Prices, stock and messages are the app's, passed through as the app words them."""
from urllib.parse import quote

from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import app

mcp = MCPServer(
    "Haat",
    instructions="Haat is a general store in Bangladesh; prices are in taka and orders are paid in cash on "
                 "delivery. Find products, add them to the cart, show the buyer the cart, then check out.",
    token_verifier=app.verifier,
    auth=AuthSettings(issuer_url=app.HAAT_URL, resource_server_url=app.MCP_URL, required_scopes=["shop"],
                      validate_token_resource=True),
)
READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
CHANGE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)


async def api(method, path, **kwargs):
    return await app.call(get_access_token(), method, path, **kwargs)


def tile(p):
    """A product as a list shows it."""
    return {"name": p["name"], "slug": p["slug"], "price": p["price_display"], "was": p["original_price_display"],
            "discount": p["discount_label"], "rating": p["rating_label"], "stock": p["stock_level"],
            "pick_first": p["choose_label"]}


def cart(c):
    return {"items": [{"item": line["id"], "name": line["name"], "options": line["options_line"],
                       "price": line["each_line"], "quantity": line["quantity"], "max_quantity": line["max_qty"],
                       "line_total": line["line_total_display"]} for line in c["lines"]],
            "subtotal": c["subtotal_display"], "delivery": c["delivery_display"], "total": c["total_display"],
            "expected_total": c["total"], "free_delivery": c["meter"], "notice": c["notice"]}


@mcp.tool(annotations=READ)
async def store_info() -> dict:
    """How Haat works: payment options, delivery cost and free-delivery threshold, cities it delivers to."""
    c = await api("GET", "/config/")
    return {"payments": c["payments"], "cities": c["cities"], "perks": c["perks"], "delivery": c["footer_line"]}


@mcp.tool(annotations=READ)
async def find_products(query: str = "", category: str = "", sort: str = "") -> dict:
    """Search or browse products by words, category slug, and sort ("price", "-price", "-rating"; blank: newest).
    Returns each product's slug, price and stock; also the category list."""
    res = await api("GET", "/products/", params={"q": query, "category": category, "sort": sort})
    return {"title": res["title"], "count": res["count_label"], "empty": res["empty"] if not res["results"] else None,
            "categories": [{"name": c["name"], "slug": c["slug"]} for c in res["categories"] if c["slug"]],
            "products": [tile(p) for p in res["results"]]}


@mcp.tool(annotations=READ)
async def product_details(slug: str) -> dict:
    """One product in full: price, options to pick (e.g. Size), each combination's price and stock, specs,
    and the latest buyer comments."""
    p = await api("GET", f"/products/{quote(slug, safe='')}/")
    comments = await api("GET", f"/products/{quote(slug, safe='')}/comments/")
    return {**tile(p), "summary": p["summary"], "category": p["category"]["name"], "specs": p["specs"],
            "stock_label": p["stock_label"], "max_quantity": p["max_qty"], "options": p["options"],
            "combinations": [{"choices": v["choices"], "price": v["price_display"], "stock": v["stock_label"],
                              "max_quantity": v["max_qty"]} for v in p["variants"]],
            "comments": [{"author": c["author"], "date": c["date"], "text": c["text"]} for c in comments["results"][:5]]}


@mcp.tool(annotations=CHANGE)
async def add_to_cart(slug: str, quantity: int = 1, options: dict[str, str] | None = None) -> dict:
    """Add a product to the cart. `options` picks one value per option the product has, e.g. {"Size": "M"}.
    Returns the cart."""
    p = await api("GET", f"/products/{quote(slug, safe='')}/")
    return cart(await api("POST", "/cart/", json={"product": p["id"], "quantity": quantity, "options": options or {}}))


@mcp.tool(annotations=READ)
async def view_cart() -> dict:
    """The cart: items, totals, delivery fee, and notes when stock changed. Show it to the buyer before checkout;
    its expected_total goes to checkout."""
    return cart(await api("GET", "/cart/"))


@mcp.tool(annotations=CHANGE)
async def change_cart(item: str, quantity: int) -> dict:
    """Set a cart item's quantity (`item` as view_cart lists it); 0 takes it out. Returns the cart."""
    path = f"/cart/{quote(item, safe='')}/"
    if quantity == 0:
        return cart(await api("DELETE", path))
    return cart(await api("PATCH", path, json={"quantity": quantity}))


@mcp.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False,
                                      open_world_hint=False))
async def checkout(full_name: str, phone: str, address: str, city: str, expected_total: int, email: str = "") -> dict:
    """Place a cash-on-delivery order for everything in the cart, delivered to the buyer. Ask the buyer first.
    `expected_total` is view_cart's expected_total the buyer agreed to; the order is refused if the cart
    changed since. `city` is one of store_info's cities."""
    if not (await api("GET", "/cart/"))["lines"]:
        raise ToolError("The cart is empty. Add products first.")
    order = await api("POST", "/orders/", json={"full_name": full_name, "phone": phone, "address": address,
                                                "city": city, "email": email, "expected_total": expected_total})
    return {"order": order["title"], "status": order["status_display"], "total": order["total_line"],
            "notice": order.get("notice")}


@mcp.tool(annotations=READ)
async def my_orders() -> dict:
    """The buyer's orders, newest first, with status and items."""
    orders = await api("GET", "/orders/")
    return {"orders": [{"order": o["title"], "status": o["status_display"], "placed": o["meta_line"],
                        "total": o["total_line"], "items": [f'{i["name"]}: {i["qty_line"]}' for i in o["items"]]}
                       for o in orders]}
