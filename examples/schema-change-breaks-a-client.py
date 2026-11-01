"""Release 2 of the shop's server renames check_stock's on_hand to count: what a connected client and a contract check see."""
import asyncio

from mcp import Client
from pydantic import BaseModel

from lib import confirmations, contract, shop_tools
from lib.testing import shop_api_here


class Warehouse(BaseModel):
    warehouse: str
    count: int                                            # release 1 called it on_hand
    last_counted: str


class StockReport(BaseModel):
    sku: str
    available: int
    warehouses: list[Warehouse]


def check_stock(sku: shop_tools.Sku) -> StockReport:
    report = confirmations.chapter3_tools()["check_stock"].fn(sku)       # release 1's tool does the reading
    return StockReport(sku=sku, available=report.available, warehouses=[Warehouse(
        warehouse=w.warehouse, count=w.on_hand, last_counted=str(w.last_counted)) for w in report.warehouses])


async def main() -> None:
    server = shop_tools.create_server()
    with shop_api_here():                                  # the server's tools run in this process
        async with Client(server) as client:
            listing = await client.list_tools()
            print("release 1's tools/list cache hint:", f"ttlMs {listing.ttl_ms}")
            server.remove_tool("check_stock")                                  # the release, while connected
            server.add_tool(check_stock, description=shop_tools.DESCRIPTIONS["check_stock"])
            try:
                await client.call_tool("check_stock", {"sku": "KG-1031"})
            except RuntimeError as error:
                print("client that listed before the release:", error.args[0].splitlines()[0])
            new = next(tool for tool in (await client.list_tools()).tools if tool.name == "check_stock")
            result = await client.call_tool("check_stock", {"sku": "KG-1031"})
            print("client after listing again:", "result" if not result.is_error else "tool error")
    old = next(tool for tool in listing.tools if tool.name == "check_stock")
    print("contract check:", "; ".join(contract.breaking_changes(old, new)) or "no breaking change")
    validator = contract.validator(old.output_schema)(old.output_schema)    # by the dialect the schema declares
    print("validator for release 1's schema:", type(validator).__name__ + ", as it declares",
          old.output_schema.get("$schema", "no $schema"))
    print("release 2's result against release 1's schema:", next(validator.iter_errors(result.structured_content)).message)


asyncio.run(main())
