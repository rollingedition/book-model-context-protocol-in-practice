"""The support host works one ticket and prints each model turn: the tool call, its outcome, and what went back to the
model. The model's replies are replayed from the recording in examples/data/recorded/ticket-runs/, which
recordings/ticket_runs.py made."""
import asyncio
import json

from lib import loopback, shop_api, ticket_host
from lib.host import ReplayModel
from lib.shop_data import load_shop

model = ReplayModel("ticket-runs")      # replays the recorded replies, so no model runs here
TICKET = "T-0009"


async def main() -> None:
    ticket = load_shop().ticket(TICKET)
    print("ticket asks:", max(ticket.body.split("\n\n"), key=len))      # the customer's message is the ticket's longest paragraph
    print("order the customer means:", ticket.order_id)
    with loopback.serve(shop_api.create_app()) as base_url:
        async with ticket_host.queue_host(base_url) as host:
            await host.attach("shop")
            run = await host.work(model, ticket)
    for number, turn in enumerate(run.turns, start=1):
        if turn.tool is None:
            print(f"turn {number} reply:", turn.reply)
            continue
        print(f"turn {number} tool:", turn.tool)
        print(f"turn {number} arguments:", turn.arguments)
        print(f"turn {number} outcome:", turn.outcome)
        print(f"turn {number} back to the model:", turn.result[:160])      # the first 160 characters, enough for a message
    print("model calls:", len(run.turns))
    print("model calls allowed per ticket:", ticket_host.MAX_TURNS)
    print("timeout per request, seconds:", ticket_host.CALL_TIMEOUT)
    manifest = json.loads((model.folder / "manifest.json").read_text())
    print("sampling temperature:", manifest["sampling"]["temperature"])
    print("sampling seed:", manifest["sampling"]["seed"])
    batches = manifest["batches"]
    print("recording batches:", len(batches))
    print("single-ticket batches:", sum(b["scenario"] == "one" for b in batches))      # "one" marks a batch of a single ticket
    seconds = [s for b in batches for s in b["seconds_per_call"]]
    print("seconds per model call, mean:", round(sum(seconds) / len(seconds), 1))
    # the batch's time is its calls' seconds added up
    print("longest batch, minutes:", round(max(sum(b["seconds_per_call"]) for b in batches) / 60, 1))


asyncio.run(main())
