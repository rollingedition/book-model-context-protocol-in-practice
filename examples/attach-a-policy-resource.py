"""The host, not the model, chooses which of the shop's resources go into the model's context: those marked for the
assistant with a high priority. A second read comes from the client's cache, within the server's ttlMs."""
import asyncio
import pathlib

from lib import loopback, shop_api, ticket_host, wire
from lib.shop_data import load_shop

LOG = pathlib.Path("attach-a-policy-resource.jsonl")


async def main() -> None:
    LOG.unlink(missing_ok=True)
    with loopback.serve(shop_api.create_app()) as base_url:
        servers = ticket_host.queue_servers(base_url)
        servers["shop"] = wire.relay(servers["shop"], log=str(LOG))
        async with ticket_host.queue_host(base_url, servers) as host:
            listed = (await host.clients["shop"].list_resources()).resources
            for resource in listed:
                print(f"{resource.uri}: priority {resource.annotations.priority}")
            priorities = {str(r.uri): r.annotations.priority for r in listed}
            print("policies listed:", len(listed))
            print("refund policy priority:", priorities.pop("shop://policies/refund"))
            print("other policies' priority:", ", ".join(str(p) for p in sorted(set(priorities.values()))))
            print("attach at priority at least:", ticket_host.ATTACH_PRIORITY)
            print("tools the model sees:", len(host.tools()))
            print("attached:", ", ".join(await host.attach("shop")))
            again = await host.clients["shop"].read_resource("shop://policies/refund")
            print("ttl ms:", again.ttl_ms)
            system = host.messages(load_shop().ticket("T-0007"))[0]["content"]
            print("system prompt, characters:", len(system))
            print("of which the policy:", len(host.context))
    reads = [m for direction, m in wire.read_trace(str(LOG)) if m.get("method") == "resources/read"]
    print("resources/read sent to the server:", len(reads))
    LOG.unlink()


asyncio.run(main())
