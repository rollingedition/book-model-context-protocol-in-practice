"""Two replicas of chapter 5's refund server: a confirmation needs a shared key and a shared store to complete once."""
import asyncio
import re
import sys
import tempfile

from mcp import Client, MCPError

from lib import confirmations, http_mcp, loopback, shared_state, shop_api

SHARED_KEY = "chapter-6-test-key-not-a-secret-0123456789"             # at least 32 bytes; a deployment reads its own
YES = {"action": "accept", "content": {"release": True}}              # the support lead's answer, as on the wire


async def outcome(call) -> str:                                       # refund status, tool error or protocol error
    try:
        result = await call
    except MCPError as error:
        return f"error {error.error.code} {error.error.message}"
    text = result.content[0].text.split(". ")[0] if result.is_error else result.structured_content["status"]
    return re.sub(r"Q-[0-9a-f]{10}", "Q-…", text)                    # quote IDs are random


async def refund_across(label: str, env: dict) -> None:
    with http_mcp.launch(__file__, env=env) as url_a, http_mcp.launch(__file__, env=env) as url_b:
        async with Client(url_a, elicitation_callback=confirmations.say_yes) as on_a, \
                Client(url_b, elicitation_callback=confirmations.say_yes) as on_b:
            print(f"{label} reads on a and b:", ", ".join([(await c.call_tool("get_order_status", {
                "order_id": "O-1873"})).structured_content["status"] for c in (on_a, on_b)]))
            quoted = await on_a.call_tool("quote_refund", {"order_id": "O-2289"})       # above the policy's limit
            args = {"quote_id": quoted.structured_content["quote_id"]}
            first = await on_a.session.call_tool("issue_refund", args, allow_input_required=True)   # asks on a
            answer = dict(input_responses={"confirm": YES}, request_state=first.request_state)
            print(f"{label} retry on b:", await outcome(on_b.session.call_tool("issue_refund", args, **answer)))
            if shared_state.STORE_VARIABLE in env:                    # the same answer again, sent to replica a
                print(f"{label} replay on a:", await outcome(on_a.session.call_tool("issue_refund", args, **answer)))


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url, tempfile.TemporaryDirectory() as shared:
        env = shop_api.server_env(api_url)                            # one shop API behind both replicas
        keyed = {**env, confirmations.STATE_KEY_VARIABLE: SHARED_KEY}
        await refund_across("own keys", env)                          # each process makes its own key
        await refund_across("shared key", keyed)
        await refund_across("shared store", {**keyed, shared_state.STORE_VARIABLE: f"{shared}/state.db"})


if "--serve" in sys.argv:                                             # one replica: chapter 5's server, over HTTP
    http_mcp.load_server("refund-asks-to-confirm.py").run(transport="streamable-http", port=http_mcp.port())
else:
    asyncio.run(main())
