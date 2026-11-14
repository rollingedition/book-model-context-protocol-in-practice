"""A mix-up attack on the support host, run against a shop server that sends `iss` and one that omits it. The point rests
on the codes-received lines: the `iss` mismatch leaves the attacker nothing, and without `iss` it gets a token."""
import asyncio

from mcp.client.auth import OAuthFlowError, OAuthTokenError

from lib import auth_server, oauth_client, protected_shop


async def attempt(label: str, **shop_options) -> None:
    with auth_server.serve(**shop_options) as shop_issuer, protected_shop.serve(shop_issuer.url) as shop_url:
        # the attacker's server forwards the browser to the shop's, and the partner's server names the attacker
        with auth_server.serve_mix_up(shop_issuer.url, target=shop_url) as attacker, \
                protected_shop.serve(attacker.url) as partner_url:
            browser = oauth_client.ScriptedBrowser()
            try:
                async with oauth_client.connect(partner_url, browser=browser) as client:
                    await client.list_tools()
            except* (OAuthFlowError, OAuthTokenError) as group:
                error = group.exceptions[0]
                print(f"{label}, host stopped:", type(error).__name__, str(error).split(":")[0])  # the message's first phrase
            assert "code" in browser.arrived                                  # the user consented at the shop's server
            print(f"{label}, iss in the answer:", "shop's" if browser.arrived.get("iss") == shop_issuer.url else "none")
            print(f"{label}, codes the attacker received:", len(attacker.stolen))
            for loot in attacker.stolen:
                claims = auth_server.claims(loot["access_token"])
                assert claims["aud"] == shop_url                              # the token names the shop's server as its audience
                print(f"{label}, attacker's token scope:", claims["scope"])


asyncio.run(attempt("shop sends iss"))
asyncio.run(attempt("shop omits iss", send_iss=False, advertise_iss=False))
