"""Draw the tool each ticket's first call used against the tool it should have used, as a grid of counts. The boxed
diagonal holds the right calls and the shaded cell is the largest wrong one; the printed lines give both."""
import asyncio
from collections import Counter

from matplotlib.patches import Rectangle

from lib import queue_replay, ticket_host
from lib.figures import ACCENT, INK, RULE, new_figure, save
from lib.shop_data import load_shop


async def main() -> None:
    tickets = load_shop().tickets
    runs = await queue_replay.replay_queue()
    # (expected first tool, tool called first); a run that made no call counts as "no tool"
    pairs = [(ticket_host.expected_first_tool(t), runs[t.ticket_id].calls[0].tool if runs[t.ticket_id].calls else "no tool")
             for t in tickets]
    cells = Counter(pairs)
    rows, cols = sorted({e for e, _ in pairs}), sorted({c for _, c in pairs})
    wrong = sorted(((n, e, c) for (e, c), n in cells.items() if e != c), key=lambda w: (-w[0], w[1], w[2]))
    print("tickets scored:", len(pairs))
    print("right first calls:", sum(n for (e, c), n in cells.items() if e == c))
    print("wrong first calls:", sum(n for n, _, _ in wrong))
    for n, expected, called in wrong:
        print(f"expected {expected}, called {called}:", n)
    print("largest wrong cell:", f"expected {wrong[0][1]}, called {wrong[0][2]}")

    fig, ax = new_figure(height=3.6)
    ax.grid(False)
    for i, expected in enumerate(rows):
        for j, called in enumerate(cols):
            n, right, peak = cells[(expected, called)], expected == called, (expected, called) == wrong[0][1:]
            # the boxes sit above their neighbours' outlines, so no RULE line doubles an INK box
            ax.add_patch(Rectangle((j, i), 1, 1, facecolor=ACCENT if peak else "none", edgecolor=INK if right else RULE,
                                   linewidth=1.8 if right else 0.8, zorder=3 if right else 2))
            if n:
                ax.text(j + 0.5, i + 0.5, str(n), ha="center", va="center", color=RULE if peak else INK,
                        fontweight="bold" if right else "normal")
    ax.set(xlim=(0, len(cols)), ylim=(len(rows), 0), xlabel="tool called first (boxed: the right call)",
           ylabel="expected first tool")
    ax.set_xticks([j + 0.5 for j in range(len(cols))], cols, rotation=45, ha="right", rotation_mode="anchor")
    ax.set_yticks([i + 0.5 for i in range(len(rows))], rows)
    ax.tick_params(length=0)
    ax.spines[:].set_visible(False)
    save(fig, "first-tool-confusion")


asyncio.run(main())
