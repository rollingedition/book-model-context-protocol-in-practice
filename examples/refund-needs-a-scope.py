"""The shop's server refuses a refund without `refunds:write` with a 403 challenge, decided on the parsed body rather than
on `Mcp-Name` or the first `Authorization` header, refuses methods no scope maps, and can hide the tools a token can't
call. The point rests on the 403 lines, and on the refusals a header-only check would have let through: the spellings of
`Mcp-Name`, the 2025-11-25 client, and the second header."""
import json
import os

from lib import auth_server, http_mcp, loopback, protected_shop, shop_api

REFUND = {"name": "issue_refund", "arguments": {"quote_id": "Q-00000000aa"}}
IN_BASE64 = "=?base64?aXNzdWVfcmVmdW5k?="                                   # "issue_refund", as the spec encodes it


def bearer(token: str, **headers: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", **headers}


with auth_server.serve() as issuer, loopback.serve(shop_api.create_app()) as api_url:
    os.environ.update(shop_api.server_env(api_url))                       # the server runs in this process
    for hide in (False, True):                                       # hiding off, then on
        with protected_shop.serve(issuer.url, hide_tools=hide) as url:  # hide_tools drops the tools this token can't call
            token = auth_server.mint(issuer.url, url, ["orders:read", "stock:read"])
            listed = http_mcp.post(url, "tools/list", headers=bearer(token)).json()["result"]
            print(f"hide_tools={hide}, tools listed:", ", ".join(tool["name"] for tool in listed["tools"]))
    print("tools/list cacheScope:", listed["cacheScope"])                 # the SDK's default, which suits a list that depends on the token
    with protected_shop.serve(issuer.url) as url:
        token = auth_server.mint(issuer.url, url, ["orders:read", "stock:read"])
        status = http_mcp.post(url, "tools/call", {"name": "get_order_status", "arguments": {"order_id": "O-1873"}},
                               headers=bearer(token))
        print("get_order_status:", status.status_code)
        refused = http_mcp.post(url, "tools/call", REFUND, headers=bearer(token))
        print("issue_refund:", refused.status_code)
        print("challenge:", refused.headers["www-authenticate"].split(", resource_metadata")[0])   # the challenge without its URL
        assert "resource_metadata=" in refused.headers["www-authenticate"]
        # the header claims a tool the token may call, but the body asks for the refund, which the server must refuse
        lying = http_mcp.post(url, "tools/call", REFUND, headers=bearer(token, **{"Mcp-Name": "get_order_status"}))
        print("issue_refund named get_order_status in Mcp-Name:", lying.status_code, lying.json()["error"]["code"])
        encoded = http_mcp.post(url, "tools/call", REFUND, headers=bearer(token, **{"Mcp-Name": IN_BASE64}))
        print("issue_refund with Mcp-Name in base64:", encoded.status_code)
        # revision 2025-11-25 sends no Mcp-Name header at all, so the server must check the body for it
        print("issue_refund at 2025-11-25:", protected_shop.call_at_2025_11_25(url, token, REFUND).status_code)
        # two Authorization headers: the read-only token first, then junk, which the server must refuse outright
        twice = protected_shop.call_with_headers(url, REFUND, [("Authorization", f"Bearer {token}"),
                                                               ("Authorization", "Bearer x")])
        print("issue_refund with two Authorization headers:", twice.status_code, twice.json()["error"])
        # prompts/get names a prompt, not a tool, so no scope in the map covers it and the server refuses it
        unmapped = http_mcp.post(url, "prompts/get", {"name": "review_refund"}, headers=bearer(token))
        print("prompts/get, which no scope maps:", unmapped.status_code)
        lead = auth_server.mint(issuer.url, url, ["orders:read", "stock:read", "refunds:write"])
        allowed = http_mcp.post(url, "tools/call", REFUND, headers=bearer(lead))
        print("issue_refund with a lead token:", allowed.status_code, json.loads(allowed.text)["result"]["isError"])
