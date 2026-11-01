"""Step-up: the SDK's client meets the refund's 403, asks the user again for the union of its scopes and
`refunds:write`, and retries. A user who may not grant `refunds:write` gets a token without it, and the refund fails."""
import asyncio
import os

from lib import auth_server, loopback, oauth_client, protected_shop, shop_api


async def refund(label: str, user_scopes: tuple[str, ...]) -> None:
    with auth_server.serve(user_scopes=user_scopes) as issuer, protected_shop.serve(issuer.url) as url:
        browser, storage = oauth_client.ScriptedBrowser(), oauth_client.MemoryStorage()
        async with oauth_client.connect(url, browser=browser, storage=storage) as client:
            quote = await client.call_tool("quote_refund", {"order_id": "O-1004", "reason": "arrived cracked"})
            print(f"{label}, quote amount:", quote.structured_content["amount"])
            print(f"{label}, quote within limit:", quote.structured_content["within_limit"])
            try:
                result = await client.call_tool("issue_refund", {"quote_id": quote.structured_content["quote_id"]})
                print(f"{label}, refund status:", result.structured_content["status"])
            except Exception as error:
                print(f"{label}, refund failed:", type(error).__name__, error)
        for number, asked in enumerate(browser.requests, start=1):
            print(f"{label}, authorization {number} asked for:", asked["scope"])
        print(f"{label}, token scope:", auth_server.claims(storage.tokens.access_token)["scope"])


async def main() -> None:
    with loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))                    # the server runs in this process
        await refund("lead", auth_server.SCOPES)
        await refund("non-lead", ("orders:read", "stock:read"))


asyncio.run(main())
