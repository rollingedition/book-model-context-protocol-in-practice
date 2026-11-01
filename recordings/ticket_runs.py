"""Record `ticket-runs` (chapter 10, reused by chapter 11): the book's host working through the shop's tickets.

Each run drives chapter 10's host (`lib.ticket_host.queue_host`) against its real servers, the shop's
(`lib.support_shop`, over stdio, against the shop's API on loopback) and the partner's (`lib.partner`, in-process),
exactly as the examples replay it, with the pinned local model in place of the replay. Each raw reply is saved with
the SHA-256 of the messages it answered, so `lib.host.ReplayModel("ticket-runs")` can answer for it.

Two scenarios:

- `queue`: all 48 tickets, in ticket order, through one host and one shop server, as `work-the-ticket-queue`
  replays them. About 100 calls, so it is recorded in batches.
- `one TICKET_ID`: one ticket through a fresh host. Its first turn is the same messages as in the queue; a later
  turn differs only where the shop's state does (a refund's ID). The recording's first batch is `one T-0007`, made
  before the queue; the queue's replay uses its two replies for T-0007, since the messages match. `work-one-ticket`
  works T-0009 in a fresh host; its turns carry no quote or refund ID, so its messages match the queue's, and it
  replays replies from the queue's batches.

Batches: a run replays every reply it already has, which repeats the shop's state exactly (the host's scripted
people, the server's repeatable quote IDs and the API's refund numbering are all fixed), and calls the model only for
messages it has no reply for. It stops starting new calls after `--minutes` (default 7), so each command stays under
10 minutes; run the same command again to go on. A run that finds every reply recorded makes no call. Run from the
book's root, in the recording runtime (recordings/requirements.txt), with RE_MODELS naming the folder with the model
file if it isn't in recordings/.models:

    python recordings/ticket_runs.py queue            # repeat until it prints "complete"
    python recordings/ticket_runs.py one T-0007         # the first batch

It appends to examples/data/recorded/ticket-runs/replies.jsonl (one line per call: scenario, ticket, turn, hash,
reply, seconds) and rewrites manifest.json, listing each batch
(its scenario, date, calls, tickets and seconds per call) and whether the queue is complete.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

BOOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOOK / "examples"))
sys.path.insert(0, str(BOOK / "recordings"))

import local_model  # noqa: E402
from lib import host, loopback, shop_api, ticket_host  # noqa: E402
from lib.shop_data import load_shop  # noqa: E402

NAME = "ticket-runs"
OUT = BOOK / "examples" / "data" / "recorded" / NAME


def read_entries() -> list[dict]:
    if not (OUT / "replies.jsonl").exists():
        return []
    with open(OUT / "replies.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class OutOfTime(Exception):
    pass


class ResumingModel:
    """Answers from the replies already recorded; calls the live model for the rest until the time is up."""

    def __init__(self, scenario: str, minutes: float):
        self.name, self.scenario = "resuming", scenario
        self.deadline = time.monotonic() + minutes * 60
        entries = read_entries()
        self.known = {e["messages_sha256"]: e["reply"] for e in entries}
        self.batch = max((e["batch"] for e in entries), default=0) + 1
        self.live = None
        self.new = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        key = host.messages_sha256(messages)
        if key in self.known:
            return self.known[key]
        if time.monotonic() > self.deadline:
            raise OutOfTime
        self.live = self.live or local_model.LocalModel()
        reply = self.live.complete(messages)
        ticket_id = messages[1]["content"].split()[1]
        entry = {"scenario": self.scenario, "ticket_id": ticket_id,
                 "turn": sum(m["role"] == "assistant" for m in messages) + 1, "messages_sha256": key,
                 "reply": reply, "seconds": self.live.seconds[-1], "batch": self.batch,
                 "created": date.today().isoformat()}
        with open(OUT / "replies.jsonl", "a", encoding="utf-8") as f:     # saved at once: a killed run keeps it
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.known[key] = reply
        self.new.append(entry)
        print(ticket_id, f"turn {entry['turn']}", entry["seconds"], "s:", reply.replace("\n", " ")[:100], flush=True)
        return reply


async def record(scenario: str, ticket_ids: list[str], minutes: float) -> bool:
    shop = load_shop()
    model = ResumingModel(scenario, minutes)
    complete = True
    with loopback.serve(shop_api.create_app()) as base_url:
        async with ticket_host.queue_host(base_url) as queue:
            await queue.attach("shop")
            try:
                for ticket_id in ticket_ids:
                    await queue.work(model, shop.ticket(ticket_id))
            except OutOfTime:
                complete = False
    write_manifest(complete if scenario == "queue" else read_manifest_complete())
    return complete


def write_manifest(complete: bool) -> None:
    """The manifest, rebuilt from every reply recorded so far, so a batch cut off by a timeout is still listed."""
    entries = read_entries()
    batches = []
    for number in sorted({e["batch"] for e in entries}):
        mine = [e for e in entries if e["batch"] == number]
        batches.append({"batch": number, "scenario": mine[0]["scenario"], "created": mine[0]["created"],
                        "calls": len(mine), "tickets": sorted({e["ticket_id"] for e in mine}),
                        "seconds_per_call": [e["seconds"] for e in mine]})
    manifest = {"script": "recordings/ticket_runs.py", **local_model.describe(),
                "prompt_sha256": hashlib.sha256(ticket_host.QUEUE_PROMPT.encode()).hexdigest(),
                "created": min((e["created"] for e in entries), default=date.today().isoformat()),
                "outputs": ["replies.jsonl"], "calls": len(entries), "queue_complete": complete,
                "host": {"module": "examples/lib/ticket_host.py", "max_turns": ticket_host.MAX_TURNS,
                         "call_timeout_seconds": ticket_host.CALL_TIMEOUT, "consent": "approve_every_call",
                         "input_requests": "decline_every_request", "attached": "shop://policies/refund"},
                "batches": batches}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def read_manifest_complete() -> bool:
    path = OUT / "manifest.json"
    return path.exists() and json.loads(path.read_text(encoding="utf-8")).get("queue_complete", False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=["queue", "one"])
    parser.add_argument("ticket", nargs="?")
    parser.add_argument("--minutes", type=float, default=7.0)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ticket_ids = [t.ticket_id for t in load_shop().tickets] if args.scenario == "queue" else [args.ticket]
    done = asyncio.run(record(args.scenario, ticket_ids, args.minutes))
    print("complete" if done else "out of time: run the same command again to go on")


if __name__ == "__main__":
    main()
