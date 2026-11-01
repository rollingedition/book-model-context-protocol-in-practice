"""The host works through all 48 of the shop's tickets against the shop's server and the partner's, and counts what
happened. The model's replies are a recording (examples/data/recorded/ticket-runs/), made with recordings/ticket_runs.py."""
import asyncio
from collections import Counter

from lib import loopback, shop_api, ticket_host
from lib.host import ReplayModel
from lib.shop_data import load_shop

model = ReplayModel("ticket-runs")


async def main() -> None:
    tickets = load_shop().tickets
    with loopback.serve(shop_api.create_app()) as base_url:
        async with ticket_host.queue_host(base_url) as host:
            await host.attach("shop")
            runs = {ticket.ticket_id: await host.work(model, ticket) for ticket in tickets}
    calls = [turn for run in runs.values() for turn in run.calls]
    print("tickets worked:", len(runs))
    print("model calls:", sum(len(run.turns) for run in runs.values()))
    print("tool calls:", len(calls))
    for outcome, count in sorted(Counter(turn.outcome for turn in calls).items()):
        print(f"outcome {outcome}:", count)
    first = [runs[t.ticket_id].calls[0].tool if runs[t.ticket_id].calls else None for t in tickets]
    right = sum(tool == ticket_host.expected_first_tool(t) for tool, t in zip(first, tickets))
    print("first tool as tagged:", f"{right} of {len(tickets)}")
    print("stopped at the turn limit:", sum(run.answer is None for run in runs.values()))
    refunds = {tid for tid, run in runs.items() if any(turn.tool == "shop.issue_refund" for turn in run.calls)}
    for tag in ("issue_refund", "quote_refund"):
        group = [t for t in tickets if t.expected_tool == tag]
        print(f"{tag} tickets that called issue_refund:", f"{sum(t.ticket_id in refunds for t in group)} of {len(group)}")
        promised = [t for t in group if t.ticket_id not in refunds and ticket_host.promises_refund(runs[t.ticket_id].answer)]
        print(f"{tag} tickets promising a refund that never ran:", f"{len(promised)} of {len(group)}")
    print("refunds issued:", sum(t.tool == "shop.issue_refund" and t.outcome == "result" for t in calls))
    asked = [f"{r.server}.{r.tool}" for r, d in host.gate.log if d != "allowed by the host's list"]
    print("consent questions:", len(asked))
    print("consent asked for:", asked)
    injected = [t for t in tickets if t.injected]
    print("injected tickets that called issue_refund:", f"{sum(t.ticket_id in refunds for t in injected)} of {len(injected)}")
    print("T-0003 tool:", runs["T-0003"].calls[0].tool)
    print("T-0003 tracking number:", runs["T-0003"].calls[0].arguments.get("tracking_number"))
    print("T-0048 reply:", runs["T-0048"].answer)


asyncio.run(main())
