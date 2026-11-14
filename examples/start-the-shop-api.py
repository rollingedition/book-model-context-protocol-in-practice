"""Start the shop's existing HTTP API on loopback and call it three ways: with its key, without it, and for an order
 that doesn't exist. The point rests on the `without key` line, which shows the API refuses a caller it can't identify."""
import httpx2

from lib import loopback, shop_api
from lib.shop_data import SHOP_SEED, load_shop

shop = load_shop()  # one fixed seed, so every run sees the same customers, orders and tickets
print("seed:", SHOP_SEED)
print("customers:", len(shop.customers))
print("products:", len(shop.products))
print("orders:", len(shop.orders))
print("tickets:", len(shop.tickets))

with loopback.serve(shop_api.create_app()) as base_url:  # serves on 127.0.0.1 at a free port until the block ends
    # the API checks this header; DEMO_API_KEY is the key the shop's API accepts
    response = httpx2.get(f"{base_url}/orders/O-2476", headers={"X-API-Key": shop_api.DEMO_API_KEY})
    order = response.json()
    print("with key:", response.status_code)
    print("order status:", order["status"])
    print("shipped on:", order["shipped_on"])
    print("total:", order["total"])
    print("without key:", httpx2.get(f"{base_url}/orders/O-2476").status_code)  # no header at all
    # O-7144 is a well-formed ID that the generated orders do not contain
    print("unknown order:", httpx2.get(f"{base_url}/orders/O-7144",
                                       headers={"X-API-Key": shop_api.DEMO_API_KEY}).status_code)
