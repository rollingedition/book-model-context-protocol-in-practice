"""Show the _meta that every request and result carries, add one key of the shop's own, and send a request without
the client's capabilities. The prose's claims about the envelope come from the printed keys and the bare request's error code."""
import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from mcp.types import Implementation

from lib import byte_meter, loopback, raw_stdio, shop_api, wire

COMMAND = [sys.executable, "list-what-the-server-offers.py", "--serve"]


async def main() -> None:
    Path("meta.jsonl").unlink(missing_ok=True)       # the relay appends to its log
    with loopback.serve(shop_api.create_app()) as base_url:
        server = StdioServerParameters(command=COMMAND[0], args=COMMAND[1:], env=shop_api.server_env(base_url))
        # the relay logs every line the client and server exchange, so the byte counts are of lines as sent
        async with Client(wire.relay(server, log="meta.jsonl"),
                          # the name and version the SDK sends as clientInfo in _meta; the server must not rely on them
                          client_info=Implementation(name="shop-host", version="0.1.0")) as client:
            # a key under the shop's own prefix, which the protocol leaves to the shop to define
            await client.call_tool("get_order_status", {"order_id": "O-2476"},
                                   meta={"example.fernhill/requestId": "req-0001"})
    trace = [message for _, message in wire.read_trace("meta.jsonl")]
    call = next(m for m in trace if m.get("method") == "tools/call")          # the first tools/call request in the log
    result = next(m for m in trace if m.get("id") == call["id"] and "result" in m)   # its response, with the same id
    for key, value in call["params"]["_meta"].items():
        print(f"request {key}:", json.dumps(value))
    for key, value in result["result"]["_meta"].items():
        print(f"result {key}:", json.dumps(value))
    lines = [json.loads(entry)["line"] for entry in Path("meta.jsonl").read_text(encoding="utf-8").splitlines()]   # as sent
    print("request _meta bytes:", byte_meter.meta_bytes(lines, call["params"]["_meta"]))
    print("result _meta bytes:", byte_meter.meta_bytes(lines, result["result"]["_meta"]))

    with raw_stdio.launch(COMMAND, env={}) as raw:          # the same request, without clientCapabilities
        # capabilities=None leaves clientCapabilities out of _meta: the request the server must reject
        reply = raw.request("tools/list", meta=raw_stdio.envelope("2026-07-28", capabilities=None))
        print("without capabilities, error code:", reply["error"]["code"])
        print("without capabilities, message:", reply["error"]["message"])


asyncio.run(main())
