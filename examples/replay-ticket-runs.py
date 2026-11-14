"""Replay chapter 10's queue run, the recording ticket-runs, through the support host, and check each reply's promise
against the host's call log. The prose's point rests on the refund lines, which compare refunds issued with replies
that promise one, and on the last line, which shows what a one-sentence rewording does to the replay."""
import asyncio

from lib import queue_replay, shop_tools, ticket_host
from lib.host import RecordingMismatch
from lib.shop_data import load_shop


def reword_quote_refund(host) -> None:              # the server's next release adds a sentence to one description
    changed = {**shop_tools.DESCRIPTIONS}
    changed["quote_refund"] += " Quotes are in the order's currency."
    host.listed["shop"] = shop_tools.with_descriptions(host.listed["shop"], changed)


async def main() -> None:
    tickets = {ticket.ticket_id: ticket for ticket in load_shop().tickets}
    runs = await queue_replay.replay_queue()
    print("tickets replayed:", len(runs))
    print("T-0009 tools:", " then ".join(turn.tool for turn in runs["T-0009"].calls))   # its calls, in order
    print("refunds issued:", sum(queue_replay.refunded(run) for run in runs.values()))
    # the phrase check from chapter 10, a rule of thumb: see the module's docstring for what it misses
    promised = [ticket_id for ticket_id, run in runs.items() if ticket_host.promises_refund(run.answer)]
    # a promise with no refund behind it: no issue_refund call in the run returned a result
    unbacked = [ticket_id for ticket_id in promised if queue_replay.unbacked_refund(runs[ticket_id])]
    print("replies that promise a refund:", len(promised))
    print("of which no call made:", len(unbacked))
    for tag in ("issue_refund", "quote_refund"):           # the tickets tagged with each refund tool
        group = [t for t in tickets.values() if t.expected_tool == tag]
        print(f"{tag} tickets flagged:", f"{sum(t.ticket_id in unbacked for t in group)} of {len(group)}")
    print("flagged:", ", ".join(unbacked))
    try:
        await queue_replay.replay_queue(change=reword_quote_refund, tickets=[tickets["T-0001"]])
    except RecordingMismatch:
        print("after rewording quote_refund, T-0001 replays:", "no, RecordingMismatch")


asyncio.run(main())
