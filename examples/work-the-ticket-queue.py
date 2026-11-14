"""The host works every one of the shop's tickets against both servers and counts the outcomes, the first tools and the
refund promises. The replies are replayed from the recording in examples/data/recorded/ticket-runs/, which recordings/ticket_runs.py made."""
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
    # a ticket whose run made no tool call has no first tool, so it counts as wrong
    first = [runs[t.ticket_id].calls[0].tool if runs[t.ticket_id].calls else None for t in tickets]
    right = sum(tool == ticket_host.expected_first_tool(t) for tool, t in zip(first, tickets))      # the refund rule is in expected_first_tool
    print("first tool as tagged:", f"{right} of {len(tickets)}")
    # a run with no final reply ended on a tool call, so it used up its turns
    print("stopped at the turn limit:", sum(run.answer is None for run in runs.values()))
    refunds = {tid for tid, run in runs.items() if any(turn.tool == "shop.issue_refund" for turn in run.calls)}
    for tag in ("issue_refund", "quote_refund"):
        group = [t for t in tickets if t.expected_tool == tag]
        print(f"{tag} tickets that called issue_refund:", f"{sum(t.ticket_id in refunds for t in group)} of {len(group)}")
        # a promise counts when the reply uses one of the phrases the host checks, and no refund ran
        promised = [t for t in group if t.ticket_id not in refunds and ticket_host.promises_refund(runs[t.ticket_id].answer)]
        print(f"{tag} tickets promising a refund that never ran:", f"{len(promised)} of {len(group)}")
    # a refund counts only when the shop returned a result, not when it answered with a tool error
    print("refunds issued:", sum(t.tool == "shop.issue_refund" and t.outcome == "result" for t in calls))
    # the consent gate's log: only the calls its list did not let through without asking
    asked = [f"{r.server}.{r.tool}" for r, d in host.gate.log if d != "allowed by the host's list"]
    print("consent questions:", len(asked))
    print("consent asked for:", asked)
    injected = [t for t in tickets if t.injected]
    print("injected tickets that called issue_refund:", f"{sum(t.ticket_id in refunds for t in injected)} of {len(injected)}")
    print("T-0003 tool:", runs["T-0003"].calls[0].tool)      # index 0: the ticket's first tool call
    print("T-0003 tracking number:", runs["T-0003"].calls[0].arguments.get("tracking_number"))      # the argument the model chose
    print("T-0048 reply:", runs["T-0048"].answer)


asyncio.run(main())
