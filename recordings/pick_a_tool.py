"""Record `pick-a-tool` (chapter 1): which tool the model chooses for three of the shop's tickets.

It runs the book's own host loop against the chapter's real server, exactly as the example `host-picks-a-tool` does,
with the pinned local model in place of the replay, and saves each raw reply with the SHA-256 of the messages it
answered. Run from the book's root, in the recording runtime (recordings/requirements.txt):

    python recordings/pick_a_tool.py

It writes examples/data/recorded/pick-a-tool/replies.jsonl and manifest.json. Three calls take well under a minute
on 4 CPU cores once the model is loaded.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

BOOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOOK / "examples"))
sys.path.insert(0, str(BOOK / "recordings"))

from mcp import Client, StdioServerParameters  # noqa: E402

import local_model  # noqa: E402
from lib import host, loopback, shop_api  # noqa: E402
from lib.shop_data import load_shop  # noqa: E402

NAME = "pick-a-tool"
TICKETS = ("T-0003", "T-0010", "T-0015")      # an order ID as written, a bare order number, a stock question


async def main() -> None:
    shop = load_shop()
    model = local_model.LocalModel()
    out = BOOK / "examples" / "data" / "recorded" / NAME
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    with loopback.serve(shop_api.create_app()) as base_url:
        params = StdioServerParameters(command=sys.executable, args=["order-status-server.py", "--serve"],
                                       env=shop_api.server_env(base_url), cwd=BOOK / "examples")
        async with Client(params) as client:
            tools = (await client.list_tools()).tools
            for ticket_id in TICKETS:
                messages = host.build_messages(shop.ticket(ticket_id), tools)
                reply = model.complete(messages)
                entries.append({"ticket_id": ticket_id, "messages_sha256": host.messages_sha256(messages),
                                "reply": reply, "seconds": model.seconds[-1]})
                print(ticket_id, model.seconds[-1], "s:", reply.replace("\n", " ")[:120])
    with open(out / "replies.jsonl", "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    manifest = {"script": "recordings/pick_a_tool.py", **local_model.describe(),
                "prompt_sha256": hashlib.sha256(host.SYSTEM_PROMPT.encode()).hexdigest(),
                "created": date.today().isoformat(), "outputs": ["replies.jsonl"], "tickets": list(TICKETS),
                "calls": len(entries), "seconds_per_call": [e["seconds"] for e in entries]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
