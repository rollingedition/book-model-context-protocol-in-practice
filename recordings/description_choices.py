"""Record `description-choices` (chapter 3): which tool the model chooses for eight tickets when the shop's five tools
carry one of three sets of descriptions: one-line ones (`vague`), the shop's first draft (`draft`), and the shop's
revision after reading the first two runs (`revised`, the server's own `DESCRIPTIONS`).

It runs the book's own host loop exactly as the example `vague-description-wrong-tool` does: the tools come from the
chapter's server (`lib.shop_tools`), listed in-process, and each set is the same list with only each tool's
description replaced. The pinned local model stands in for the replay, and each raw reply is saved with the SHA-256
of the messages it answered.

It also counts, with the model's own tokenizer, the tokens each tool takes in the host's prompt, for each set
and for the endpoint-shaped set (`shop_tools.endpoint_tools()`), for the example `tool-list-size`. Counting
tokens runs no model. Run from the book's root, in the recording runtime (recordings/requirements.txt):

    python recordings/description_choices.py vague draft      # first batch: 16 calls, about 7.5 minutes
    python recordings/description_choices.py revised          # second batch: 8 calls

A call takes 5 to 45 seconds on 4 CPU cores, so the three sets are recorded in batches to keep each run under 10
minutes. Each run replaces the replies for the sets it names and keeps the others. It writes
examples/data/recorded/description-choices/replies.jsonl, prompt_tokens.json and manifest.json.
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
from lib import host, shop_tools  # noqa: E402
from lib.shop_data import load_shop  # noqa: E402

NAME = "description-choices"
TICKETS = ("T-0002", "T-0013", "T-0004", "T-0022", "T-0006", "T-0029", "T-0024", "T-0016")
SETS = {"vague": shop_tools.VAGUE_DESCRIPTIONS, "draft": shop_tools.DRAFT_DESCRIPTIONS,
        "revised": shop_tools.DESCRIPTIONS}


def token_counts(model: local_model.LocalModel, tools) -> dict:
    """Tokens per tool as the host's prompt renders it (one JSON line per tool), with each line's SHA-256."""
    out = {}
    for spec in host.tool_specs(tools):
        line = json.dumps(spec, ensure_ascii=False)
        out[spec["name"]] = {"tokens": len(model.llm.tokenize(line.encode(), add_bos=False, special=False)),
                             "sha256": hashlib.sha256(line.encode()).hexdigest()}
    return out


async def main(sets: list[str]) -> None:
    shop = load_shop()
    model = local_model.LocalModel()
    out = BOOK / "examples" / "data" / "recorded" / NAME
    out.mkdir(parents=True, exist_ok=True)
    async with Client(shop_tools.create_server()) as client:
        listed = (await client.list_tools()).tools
    tool_sets = {label: shop_tools.with_descriptions(listed, SETS[label]) for label in SETS}
    replies = out / "replies.jsonl"
    kept = [] if not replies.exists() else [e for e in map(json.loads, replies.read_text(encoding="utf-8").splitlines())
                                            if e["descriptions"] not in sets]
    entries = []
    for ticket_id in TICKETS:
        for label in sets:
            tools = tool_sets[label]
            messages = host.build_messages(shop.ticket(ticket_id), tools)
            reply = model.complete(messages)
            entries.append({"ticket_id": ticket_id, "descriptions": label,
                            "messages_sha256": host.messages_sha256(messages), "reply": reply,
                            "seconds": model.seconds[-1]})
            print(ticket_id, label, model.seconds[-1], "s:", reply.replace("\n", " ")[:100], flush=True)
    entries = sorted(kept + entries, key=lambda e: (list(SETS).index(e["descriptions"]), TICKETS.index(e["ticket_id"])))
    with open(replies, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    bare_prompt = host.SYSTEM_PROMPT.format(tools="")
    tokens = {"tokenizer": local_model.MODEL, "context": local_model.CONTEXT,
              "prompt_without_tools": len(model.llm.tokenize(bare_prompt.encode(), add_bos=False, special=False)),
              **{label: token_counts(model, tool_sets[label]) for label in SETS},
              "endpoint": token_counts(model, shop_tools.endpoint_tools())}
    (out / "prompt_tokens.json").write_text(json.dumps(tokens, indent=2) + "\n", encoding="utf-8")
    old = json.loads((out / "manifest.json").read_text()) if (out / "manifest.json").exists() else {}
    batches = [b for b in old.get("batches", []) if not set(b["sets"]) & set(sets)] + [
        {"sets": sets, "created": date.today().isoformat(), "runner": local_model.describe().get("runner")}]
    manifest = {"script": "recordings/description_choices.py", **local_model.describe(), "batches": batches,
                "description_sets_sha256": {label: hashlib.sha256(json.dumps(SETS[label], sort_keys=True).encode())
                                            .hexdigest() for label in SETS},
                "prompt_sha256": hashlib.sha256(host.SYSTEM_PROMPT.encode()).hexdigest(),
                "created": date.today().isoformat(), "outputs": ["replies.jsonl", "prompt_tokens.json"],
                "tickets": list(TICKETS), "description_sets": list(SETS), "calls": len(entries),
                "seconds_per_call": [e["seconds"] for e in entries]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main([label for label in SETS if label in sys.argv[1:]] or list(SETS)))
