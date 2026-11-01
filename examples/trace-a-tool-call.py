"""The OpenTelemetry spans the SDK emits for the shop's tool calls, over Streamable HTTP on loopback and in memory."""
import asyncio

from mcp import Client
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.semconv._incubating.attributes.mcp_attributes import McpMethodNameValues

from lib import loopback, shop_tools
from lib.testing import shop_api_here

spans = InMemorySpanExporter()
trace.set_tracer_provider(provider := TracerProvider())
provider.add_span_processor(SimpleSpanProcessor(spans))      # each span, as it ends, into memory


def finished(name: str) -> list:
    return [span for span in spans.get_finished_spans() if span.name == name]


def parent(span) -> str:
    return next((s.name for s in spans.get_finished_spans() if span.parent and s.context.span_id ==
                 span.parent.span_id), "none")


async def main() -> None:
    server = shop_tools.create_server()
    with shop_api_here(), loopback.serve(server.streamable_http_app()) as base_url:
        async with Client(base_url + "/mcp") as client:
            await client.call_tool("find_orders", {"customer_id": "C-0127"})
            await client.call_tool("quote_refund", {"order_id": "O-7144"})            # a tool error
        print("HTTP spans:", ", ".join(sorted(span.name for span in spans.get_finished_spans())))
        call, error = finished("tools/call find_orders")[0], finished("tools/call quote_refund")[0]
        print("HTTP server span:", call.name, f"({call.kind.name}), parent: {parent(call)}")
        for key in sorted(set(call.attributes) - {"jsonrpc.request.id"}):
            print(f"attribute {key}:", call.attributes[key])
        print("tool error span status:", error.status.status_code.name)
        print("tool error span error.type:", error.attributes["error.type"])
        spans.clear()
        async with Client(server) as client:
            await client.call_tool("find_orders", {"customer_id": "C-0127"})
            with trace.get_tracer("shop-tests").start_as_current_span("test find_orders"):
                await client.call_tool("find_orders", {"customer_id": "C-0127"})
        print("in-memory spans:", ", ".join(sorted(span.name for span in spans.get_finished_spans())))
        print("in-memory server span parents:", ", ".join(parent(s) for s in finished("tools/call find_orders")))
    print("pinned semconv lists server/discover:", "server/discover" in {m.value for m in McpMethodNameValues})


asyncio.run(main())
