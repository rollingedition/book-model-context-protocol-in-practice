"""A mix-up attack on the support host: the partner's server names an attacker's authorization server, which sends the
user on to the shop's. The `iss` in the shop's answer gives it away; without `iss`, the attacker gets a token."""
import asyncio

from mcp.client.auth import OAuthFlowError, OAuthTokenError

from lib import auth_server, oauth_client, protected_shop


async def attempt(label: str, **shop_options) -> None:
    with auth_server.serve(**shop_options) as shop_issuer, protected_shop.serve(shop_issuer.url) as shop_url:
        with auth_server.serve_mix_up(shop_issuer.url, target=shop_url) as attacker, \
                protected_shop.serve(attacker.url) as partner_url:          # the partner's server names the attacker
            browser = oauth_client.ScriptedBrowser()
            try:
                async with oauth_client.connect(partner_url, browser=browser) as client:
                    await client.list_tools()
            except* (OAuthFlowError, OAuthTokenError) as group:
                error = group.exceptions[0]
                print(f"{label}, host stopped:", type(error).__name__, str(error).split(":")[0])
            print(f"{label}, user consented at the shop's server:", "code" in browser.arrived)
            print(f"{label}, iss in the answer:", "shop's" if browser.arrived.get("iss") == shop_issuer.url else "none")
            print(f"{label}, codes the attacker received:", len(attacker.stolen))
            for loot in attacker.stolen:
                claims = auth_server.claims(loot["access_token"])
                print(f"{label}, attacker's token is for the shop's server:", claims["aud"] == shop_url)
                print(f"{label}, attacker's token scope:", claims["scope"])


asyncio.run(attempt("shop sends iss"))
asyncio.run(attempt("shop omits iss", send_iss=False, advertise_iss=False))
