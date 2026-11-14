"""Serves the ported refund confirmation from one app to a 2026-07-28 client and a 2025-11-25 client, then sends the 2025
client's session ID to a second replica. The prose's point rests on the two "question came as" lines (one resolver, two
forms), the two refund lines, and the two session lines: the replica that made the session answers, and the other returns a 404."""
import asyncio
import os

import httpx2
from mcp import Client

from lib import confirmations, http_mcp, loopback, shop_api, wire


LEGACY = {"MCP-Protocol-Version": "2025-11-25", "Accept": "application/json, text/event-stream"}   # a 2025 version routes to the 2025 handler


def asked_how(exchanges: list[dict]) -> str:
    messages = [m for e in exchanges for m in e["messages"]]
    if any(m.get("method") == "elicitation/create" for m in messages):
        return "a request the server pushed mid-call"
    return "an input request in a result" if any(m.get("result", {}).get("resultType") == "input_required"
                                                 for m in messages) else "never"


async def main() -> None:
    server = http_mcp.load_server("replace-pushed-requests.py")     # the ported issue_refund, with its resolver
    with loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))
        with loopback.serve(wire.record_http(server.streamable_http_app(), "a.jsonl")) as a, \
             loopback.serve(http_mcp.load_server("replace-pushed-requests.py").streamable_http_app()) as b:
            for mode, order in (("auto", "O-2289"), ("legacy", "O-1085")):     # both above the policy limit
                seen = len(wire.read_http_trace("a.jsonl"))   # this client's exchanges come after this count
                async with Client(a + "/mcp", mode=mode, elicitation_callback=confirmations.say_yes) as client:
                    quote = (await client.call_tool("quote_refund", {"order_id": order})).structured_content
                    refund = await client.call_tool("issue_refund", {"quote_id": quote["quote_id"]})
                    # the first response from this client that set a session ID
                    session = next((e["response_headers"]["mcp-session-id"] for e in wire.read_http_trace("a.jsonl")
                                    [seen:] if "mcp-session-id" in e["response_headers"]), None)
                    print(f"{mode} revision:", client.protocol_version)
                    print(f"{mode} session header:", "set" if session else "none")
                    for replica, url in (("a", a), ("b", b)) if session else ():   # no session, nothing to send
                        sent = httpx2.post(url + "/mcp", headers={"Mcp-Session-Id": session, **LEGACY},
                                           json={"jsonrpc": "2.0", "id": 9, "method": "tools/list"})
                        listed = "tools listed" if "check_stock" in sent.text else sent.json()["error"]["message"]
                        print(f"2025 session on replica {replica}: HTTP {sent.status_code},", listed)
                print(f"{mode} question came as:", asked_how(wire.read_http_trace("a.jsonl")[seen:]))  # this client's exchanges, as replica a logged them
                print(f"{mode} refund:", refund.structured_content["status"])


asyncio.run(main())
