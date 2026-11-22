"""Draw what each set of tools costs in the host's prompt: the hatched instructions, then one segment per tool, for each set.
The prose rests on the revised bar's share of the context and on its smallest and largest tool, all printed."""
import asyncio
import json

from matplotlib.patches import Patch
from mcp import Client

from lib import shop_tools
from lib.figures import ACCENT, INK, MUTED, RULE, new_figure, save
from lib.host import RECORDED, tool_specs

counted = json.loads((RECORDED / "description-choices" / "prompt_tokens.json").read_text())
INSTRUCTIONS, CONTEXT = counted["prompt_without_tools"], counted["context"]


async def main() -> None:
    async with Client(shop_tools.create_server()) as client:
        listed = (await client.list_tools()).tools
    vague = shop_tools.with_descriptions(listed, shop_tools.VAGUE_DESCRIPTIONS)
    sets = [("endpoint", shop_tools.endpoint_tools(), INK), ("vague", vague, MUTED), ("revised", listed, ACCENT)]

    fig, ax = new_figure(height=4.8)
    for row, (label, tools, color) in enumerate(sets):
        # tokens as the recording script counted them; tool-list-size.py stops if a tool changed since
        counts = [counted[label][spec["name"]]["tokens"] for spec in tool_specs(tools)]
        total = INSTRUCTIONS + sum(counts)
        print(f"{label} prompt tokens with instructions: {total}")
        ax.barh(row, INSTRUCTIONS, height=0.5, facecolor="none", edgecolor=color, hatch="///", linewidth=0.8)
        left = INSTRUCTIONS
        for tokens in counts:
            ax.barh(row, tokens, left=left, height=0.5, color=color, edgecolor=RULE, linewidth=1.2)
            left += tokens
        ax.text(total + 70, row, f"{total:,} tokens", va="center", color=color)
        if label == "revised":
            print(f"smallest revised tool tokens: {min(counts)}")
            print(f"largest revised tool tokens: {max(counts)}")
            share = 100 * total / CONTEXT

    ax.grid(axis="y", visible=False)
    ax.axvline(CONTEXT, color=INK, linestyle="--", linewidth=1)
    ax.text(CONTEXT - 60, 2.45, f"recording context, {CONTEXT:,} tokens", ha="right", va="bottom", color=INK)
    ax.set(xlim=(0, CONTEXT * 1.03), xlabel="tokens in the host's prompt", yticks=range(3),
           yticklabels=[s[0] for s in sets])
    key = [Patch(facecolor="none", edgecolor=INK, hatch="///", label="hatched: host instructions without tools")]
    fig.legend(handles=key, loc="outside lower center", fontsize=6.5, handlelength=1.5)
    print("context tokens:", CONTEXT)
    print(f"revised with instructions share of context: {share:.1f}%")
    save(fig, "tool-list-tokens")


asyncio.run(main())
