"""The support host works one ticket: each model turn, the tool call it makes, what the host did with it, and what
went back to the model. The replies are a recording (examples/data/recorded/ticket-runs/), from recordings/ticket_runs.py."""
import asyncio
import json

from lib import loopback, shop_api, ticket_host
from lib.host import ReplayModel
from lib.shop_data import load_shop

model = ReplayModel("ticket-runs")
TICKET = "T-0009"


async def main() -> None:
    ticket = load_shop().ticket(TICKET)
    print("ticket asks:", max(ticket.body.split("\n\n"), key=len))
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
        print(f"turn {number} back to the model:", turn.result[:160])
    print("model calls:", len(run.turns))
    print("model calls allowed per ticket:", ticket_host.MAX_TURNS)
    print("timeout per request, seconds:", ticket_host.CALL_TIMEOUT)
    manifest = json.loads((model.folder / "manifest.json").read_text())
    print("sampling temperature:", manifest["sampling"]["temperature"])
    print("sampling seed:", manifest["sampling"]["seed"])
    batches = manifest["batches"]
    print("recording batches:", len(batches))
    print("single-ticket batches:", sum(b["scenario"] == "one" for b in batches))
    seconds = [s for b in batches for s in b["seconds_per_call"]]
    print("seconds per model call, mean:", round(sum(seconds) / len(seconds), 1))
    print("longest batch, minutes:", round(max(sum(b["seconds_per_call"]) for b in batches) / 60, 1))


asyncio.run(main())
