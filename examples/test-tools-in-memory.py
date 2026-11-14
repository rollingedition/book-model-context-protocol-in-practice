"""Four pytest tests of the shop's tools: three through the SDK's in-process client, and one over Streamable HTTP on
loopback, which reaches a check an in-memory test never makes. The prose's point rests on the unknown-order test's
line and on the last line, which counts the passes."""
import pytest
from mcp import Client

from lib import http_mcp, loopback, shop_tools
from lib.testing import anyio_backend, run, shop_api_env

pytestmark = pytest.mark.anyio                            # runs the async tests on anyio's pytest plugin


async def test_order_status_fields(shop_api_env):        # shop_api_env serves the shop's API on loopback for this test
    # raise_exceptions=True: a bug outside a tool's body raises here, with its own message
    async with Client(shop_tools.create_server(), raise_exceptions=True) as client:
        result = await client.call_tool("get_order_status", {"order_id": "O-1873"})
    assert not result.is_error
    assert result.structured_content["order_id"] == "O-1873"
    assert result.structured_content["status"] == "delivered"


async def test_unknown_order_is_a_tool_error(shop_api_env):
    async with Client(shop_tools.create_server(), raise_exceptions=True) as client:
        result = await client.call_tool("quote_refund", {"order_id": "O-7144"})
    assert result.is_error                                    # raise_exceptions doesn't make it raise
    assert "find_orders" in result.content[0].text            # the model is told what to do instead


async def test_malformed_order_id_is_refused(shop_api_env):
    async with Client(shop_tools.create_server(), raise_exceptions=True) as client:
        result = await client.call_tool("get_order_status", {"order_id": "1873"})
    assert result.is_error
    text = result.content[0].text                             # only argument validation writes this error:
    assert "order_id" in text and "string_pattern_mismatch" in text   # the field and pydantic's pattern check


def test_http_refuses_a_mismatched_header(shop_api_env):
    with loopback.serve(shop_tools.create_server().streamable_http_app()) as base_url:
        # the header names check_stock while the body calls get_order_status: the mismatch the server must refuse
        reply = http_mcp.post(base_url + "/mcp", "tools/call", {"name": "get_order_status",
                              "arguments": {"order_id": "O-1873"}}, headers={"Mcp-Name": "check_stock"})
    assert reply.status_code == 400
    assert reply.json()["error"]["code"] == -32020        # the JSON-RPC code the server returns for the mismatch


if __name__ == "__main__":
    run(__file__)
