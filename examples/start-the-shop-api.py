"""Start the shop's existing HTTP API on loopback and call it the way any API client does."""
import httpx2

from lib import loopback, shop_api
from lib.shop_data import SHOP_SEED, load_shop

shop = load_shop()
print("seed:", SHOP_SEED)
print("customers:", len(shop.customers))
print("products:", len(shop.products))
print("orders:", len(shop.orders))
print("tickets:", len(shop.tickets))

with loopback.serve(shop_api.create_app()) as base_url:
    response = httpx2.get(f"{base_url}/orders/O-2476", headers={"X-API-Key": shop_api.DEMO_API_KEY})
    order = response.json()
    print("with key:", response.status_code)
    print("order status:", order["status"])
    print("shipped on:", order["shipped_on"])
    print("total:", order["total"])
    print("without key:", httpx2.get(f"{base_url}/orders/O-2476").status_code)
    print("unknown order:", httpx2.get(f"{base_url}/orders/O-7144",
                                       headers={"X-API-Key": shop_api.DEMO_API_KEY}).status_code)
