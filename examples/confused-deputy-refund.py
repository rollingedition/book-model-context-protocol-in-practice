"""A confused deputy: a customer signs in to a host as C-0127 and asks the shop's server about C-0116's orders and
refunds one. Chapter 3's tools do it with the server's own key; `lib.owned_shop` takes the customer from the token's
subject and refuses."""
import json
import os
import re

from lib import auth_server, http_mcp, loopback, owned_shop, shop_api

SCOPES = ["orders:read", "stock:read", "refunds:write"]
SIGNED_IN, OTHER, OTHERS_ORDER = "C-0127", "C-0116", "O-1190"      # O-1190 is C-0116's delivered order


def call(url: str, token: str, name: str, **arguments) -> dict:
    response = http_mcp.post(url, "tools/call", {"name": name, "arguments": arguments},
                             headers={"Authorization": f"Bearer {token}"})
    result = json.loads(response.text)["result"]
    return result["structuredContent"] if not result["isError"] else {"error": result["content"][0]["text"]}


def show(label: str, result: dict, key: str) -> None:
    refused = re.sub(r"Q-[0-9a-f]{10}", "Q-...", result.get("error", "").split(": ", 1)[-1].split(". ")[0])
    print(f"{label}:", result.get(key) or f"refused ({refused})")


with auth_server.serve() as issuer, loopback.serve(shop_api.create_app()) as api_url:
    os.environ.update(shop_api.server_env(api_url))                    # the server runs in this process
    for owned, server in [(False, "chapter 3"), (True, "token's subject")]:
        with owned_shop.serve(issuer.url, owned=owned) as url:
            mine = auth_server.mint(issuer.url, url, SCOPES, subject=SIGNED_IN)
            found = call(url, mine, "find_orders", **({} if owned else {"customer_id": OTHER}))
            print(f"{server}, find_orders lists orders of:", found["customer_id"])
            quote = call(url, mine, "quote_refund", order_id=OTHERS_ORDER)
            show(f"{server}, quote_refund on {OTHERS_ORDER}", quote, "amount")
            if "quote_id" in quote:
                show(f"{server}, issue_refund", call(url, mine, "issue_refund", quote_id=quote["quote_id"]), "status")
            theirs = call(url, auth_server.mint(issuer.url, url, SCOPES, subject=OTHER), "quote_refund",
                          order_id=OTHERS_ORDER)
            spent = call(url, mine, "issue_refund", quote_id=theirs["quote_id"])
            show(f"{server}, {SIGNED_IN} spends {OTHER}'s quote", spent, "status")
