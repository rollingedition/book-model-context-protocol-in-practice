"""Record `poisoned-tools` (chapter 9): which tool the model chooses, and with what arguments, when a tool definition
or a ticket carries instructions aimed at it.

Two batches, each run through the book's own host loop (`lib.host.build_messages`), exactly as the examples
`poisoned-description` and `ticket-injection` replay them:

- `partner`: three ordinary tickets, with the shop's tools (chapter 9's server, `lib.owned_shop`) beside the
  partner's `track_parcel` (`lib.partner`), once with its clean description and once with the poisoned one.
  6 calls.
- `injected`: the six tickets in the shop's data that carry instructions aimed at an agent, with the shop's tools
  only. 6 calls.

The tools are listed in-process. The pinned local model stands in for the replay, and each raw reply is saved with
the SHA-256 of the messages it answered. Run from the book's root, in the recording runtime
(recordings/requirements.txt):

    python recordings/poisoned_tools.py partner
    python recordings/poisoned_tools.py injected

A call takes 5 to 45 seconds on 4 CPU cores, so each batch stays under 10 minutes. Each run replaces the replies for
the batch it names and keeps the other. It writes examples/data/recorded/poisoned-tools/replies.jsonl and
manifest.json.
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

from mcp import Client  # noqa: E402

import local_model  # noqa: E402
from lib import host, owned_shop, partner  # noqa: E402
from lib.shop_data import load_shop  # noqa: E402

NAME = "poisoned-tools"
PARTNER_TICKETS = ("T-0003", "T-0006", "T-0016")
INJECTED_TICKETS = ("T-0008", "T-0030", "T-0037", "T-0040", "T-0041", "T-0046")
BATCHES = ("partner", "injected")


async def listed(server) -> list:
    async with Client(server) as client:
        return (await client.list_tools()).tools


async def runs() -> list[tuple[str, str, str, list]]:
    """(batch, ticket ID, condition, tools) for every call, in order."""
    shop = await listed(owned_shop.create_server())
    with_partner = {version: shop + await listed(partner.create_server(version)) for version in ("clean", "poisoned")}
    return ([("partner", t, version, with_partner[version]) for t in PARTNER_TICKETS for version in with_partner]
            + [("injected", t, "shop only", shop) for t in INJECTED_TICKETS])


async def main(batches: list[str]) -> None:
    shop = load_shop()
    out = BOOK / "examples" / "data" / "recorded" / NAME
    out.mkdir(parents=True, exist_ok=True)
    planned = [run for run in await runs() if run[0] in batches]
    model = local_model.LocalModel()
    replies = out / "replies.jsonl"
    kept = [] if not replies.exists() else [e for e in map(json.loads, replies.read_text(encoding="utf-8").splitlines())
                                            if e["batch"] not in batches]
    entries = []
    for batch, ticket_id, condition, tools in planned:
        messages = host.build_messages(shop.ticket(ticket_id), tools)
        reply = model.complete(messages)
        entries.append({"batch": batch, "ticket_id": ticket_id, "condition": condition,
                        "messages_sha256": host.messages_sha256(messages), "reply": reply,
                        "seconds": model.seconds[-1]})
        print(batch, ticket_id, condition, model.seconds[-1], "s:", reply.replace("\n", " ")[:120], flush=True)
    made = {e["batch"] for e in entries}
    entries = sorted(kept + entries, key=lambda e: BATCHES.index(e["batch"]))
    with open(replies, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    old = json.loads((out / "manifest.json").read_text()) if (out / "manifest.json").exists() else {}
    done = [b for b in old.get("batches", []) if b["batch"] not in batches] + [
        {"batch": b, "created": date.today().isoformat(), "calls": sum(e["batch"] == b for e in entries)}
        for b in batches if b in made]
    manifest = {"script": "recordings/poisoned_tools.py", **local_model.describe(),
                "prompt_sha256": hashlib.sha256(host.SYSTEM_PROMPT.encode()).hexdigest(),
                "definitions_sha256": {v: hashlib.sha256(d.encode()).hexdigest() for v, d in partner.DEFINITIONS.items()},
                "created": date.today().isoformat(), "outputs": ["replies.jsonl"],
                "batches": sorted(done, key=lambda b: BATCHES.index(b["batch"])),
                "tickets": {"partner": list(PARTNER_TICKETS), "injected": list(INJECTED_TICKETS)},
                "calls": len(entries), "seconds_per_call": [e["seconds"] for e in entries]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main([b for b in BATCHES if b in sys.argv[1:]] or list(BATCHES)))
