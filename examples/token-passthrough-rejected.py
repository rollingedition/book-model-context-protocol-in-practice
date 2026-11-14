"""Token passthrough, refused both ways: the shop's server rejects a token issued for the partner's server, and the
shop's API receives no caller's token, only the server's own key. The two asserts at the end are the claims the prose
states, so a change that forwards a token fails the run."""
import json
import os

from lib import auth_server, http_mcp, loopback, owned_shop, shop_api

PARTNER = "https://partner.example/mcp"                  # the parcel-tracking server; same authorization server
SCOPES = ["orders:read", "stock:read"]
ORDER = {"name": "get_order_status", "arguments": {"order_id": "O-2476"}}   # C-0127's order
seen = []                                                # the headers of each request the shop's API receives


def recording(app):
    async def wrapped(scope, receive, send):
        if scope["type"] == "http":
            # ASGI sends each header as a pair of bytes, with the name in lowercase
            seen.append({key.decode(): value.decode() for key, value in scope["headers"]})
        await app(scope, receive, send)
    return wrapped


with auth_server.serve() as issuer, loopback.serve(recording(shop_api.create_app())) as api_url:
    os.environ.update(shop_api.server_env(api_url))      # the server's own key for the shop's API
    with owned_shop.serve(issuer.url) as url:
        partners = auth_server.mint(issuer.url, PARTNER, SCOPES, subject="C-0127")   # audience: the partner's server
        print("partner's token aud:", auth_server.claims(partners)["aud"])
        forwarded = http_mcp.post(url, "tools/call", ORDER, headers={"Authorization": f"Bearer {partners}"})
        print("partner forwards its token, shop's server answers:", forwarded.status_code)
        # the value of error= in the challenge, which names the reason for the refusal
        print("challenge error:", forwarded.headers["www-authenticate"].split('error="')[1].split('"')[0])
        own = auth_server.mint(issuer.url, url, SCOPES, subject="C-0127")            # audience: the shop's server
        answered = http_mcp.post(url, "tools/call", ORDER, headers={"Authorization": f"Bearer {own}"})
        print("host sends a token for the shop's server:", json.loads(answered.text)["result"]["structuredContent"]
              ["status"])
    print("requests that reached the shop's API:", len(seen))
    assert not any("authorization" in headers for headers in seen)                 # no caller's token reached the API
    assert all(h.get("x-api-key") == shop_api.DEMO_API_KEY for h in seen)     # every request carried the server's key
