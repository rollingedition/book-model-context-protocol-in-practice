"""What the shop's tool list costs in the host's prompt: bytes, and tokens counted with the recording model's tokenizer
when the recording was made (examples/data/recorded/description-choices/prompt_tokens.json). The point rests on the
revised, vague and endpoint prompt token lines."""
import asyncio
import hashlib
import json

from mcp import Client

from lib import shop_tools
from lib.host import RECORDED, tool_specs

# the token counts and line hashes the recording script wrote
counted = json.loads((RECORDED / "description-choices" / "prompt_tokens.json").read_text())


def cost(label: str, tools) -> tuple[int, int]:
    """Bytes and tokens of the tools as the host's prompt renders them, one JSON line per tool."""
    lines = [json.dumps(spec, ensure_ascii=False) for spec in tool_specs(tools)]
    # the hash of each line as the host renders it; a tool that changed since then fails here
    for spec, line in zip(tool_specs(tools), lines):
        if counted[label][spec["name"]]["sha256"] != hashlib.sha256(line.encode()).hexdigest():
            raise LookupError(f"{spec['name']} changed since its tokens were counted: re-run the recording script")
    tokens = sum(counted[label][spec["name"]]["tokens"] for spec in tool_specs(tools))
    return sum(len(line.encode()) for line in lines), tokens


async def main() -> None:
    async with Client(shop_tools.create_server()) as client:
        result = await client.list_tools()
    listed = result.tools
    print("tools/list result bytes:", len(result.model_dump_json(by_alias=True, exclude_none=True).encode()))
    vague = shop_tools.with_descriptions(listed, shop_tools.VAGUE_DESCRIPTIONS)
    for label, tools in (("revised", listed), ("vague", vague), ("endpoint", shop_tools.endpoint_tools())):
        size, tokens = cost(label, tools)
        print(f"{label} prompt bytes:", size)
        print(f"{label} prompt tokens:", tokens)
    tokens_per_tool = cost("revised", listed)[1] / len(listed)  # cost returns (bytes, tokens): index 1 is tokens
    print("revised tokens per tool:", round(tokens_per_tool))
    print("20 such tools tokens:", round(20 * tokens_per_tool))       # arithmetic on the counts, not a count
    print("prompt without tools tokens:", counted["prompt_without_tools"])
    print("recording context tokens:", counted["context"])


asyncio.run(main())
