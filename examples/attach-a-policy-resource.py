"""The host attaches the shop's policies that the server marks for the assistant at a high priority, and the model never
chooses them. The second read of the refund policy is answered from the client's cache, so only the first reaches the trace, which the last printed line counts."""
import asyncio
import pathlib

from lib import loopback, shop_api, ticket_host, wire
from lib.shop_data import load_shop

LOG = pathlib.Path("attach-a-policy-resource.jsonl")


async def main() -> None:
    LOG.unlink(missing_ok=True)
    with loopback.serve(shop_api.create_app()) as base_url:
        servers = ticket_host.queue_servers(base_url)      # the shop's and the partner's servers, as the queue uses them
        servers["shop"] = wire.relay(servers["shop"], log=str(LOG))      # logs every message the shop's server exchanges
        async with ticket_host.queue_host(base_url, servers) as host:
            listed = (await host.clients["shop"].list_resources()).resources
            for resource in listed:
                print(f"{resource.uri}: priority {resource.annotations.priority}")
            priorities = {str(r.uri): r.annotations.priority for r in listed}
            print("policies listed:", len(listed))
            print("refund policy priority:", priorities.pop("shop://policies/refund"))      # removed, so the rest are the others
            print("other policies' priority:", ", ".join(str(p) for p in sorted(set(priorities.values()))))
            print("attach at priority at least:", ticket_host.ATTACH_PRIORITY)
            print("tools the model sees:", len(host.tools()))
            print("attached:", ", ".join(await host.attach("shop")))
            again = await host.clients["shop"].read_resource("shop://policies/refund")      # a second read of the same policy
            print("ttl ms:", again.ttl_ms)
            system = host.messages(load_shop().ticket("T-0007"))[0]["content"]      # index 0: the system message, which holds the policy
            print("system prompt, characters:", len(system))
            print("of which the policy:", len(host.context))
    reads = [m for direction, m in wire.read_trace(str(LOG)) if m.get("method") == "resources/read"]
    print("resources/read sent to the server:", len(reads))
    LOG.unlink()


asyncio.run(main())
