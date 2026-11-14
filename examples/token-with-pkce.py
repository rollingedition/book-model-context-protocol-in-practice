"""The SDK's client gets a token for the shop's server with the authorization code grant, PKCE S256 and the resource
parameter, then the authorization server refuses a code sent twice, a wrong verifier and the plain method. The point
rests on the status line, the refusals at the end, and the asserts that check the challenge, the resource and the token."""
import asyncio
import os

import httpx2

from lib import auth_server, loopback, oauth_client, protected_shop, shop_api


async def main() -> None:
    with auth_server.serve() as issuer, loopback.serve(shop_api.create_app()) as api_url:
        os.environ.update(shop_api.server_env(api_url))                  # the server runs in this process
        with protected_shop.serve(issuer.url) as url:
            browser, storage = oauth_client.ScriptedBrowser(), oauth_client.MemoryStorage()
            async with oauth_client.connect(url, browser=browser, storage=storage) as client:
                result = await client.call_tool("get_order_status", {"order_id": "O-1873"})
            print("O-1873 status:", result.structured_content["status"])
            asked, exchanged = issuer.events                              # /authorize, then /token
            print("authorization request:", ", ".join(key for key in asked if key != "endpoint"))
            print("code_challenge_method:", asked["code_challenge_method"])
            # the challenge is the hash of the verifier that the token request revealed
            assert oauth_client.s256(exchanged["code_verifier"]) == asked["code_challenge"]
            assert asked["resource"] == exchanged["resource"] == url                  # the server's URL, in both requests
            claims = auth_server.claims(storage.tokens.access_token)
            for claim, expected in [("aud", url), ("iss", issuer.url)]:            # the server; the issuer
                assert claims[claim] == expected, claim
            print("token sub:", claims["sub"])
            print("token scope:", claims["scope"])
            print("refresh token:", storage.tokens.refresh_token)
            again = httpx2.post(issuer.url + "/token", data=exchanged)      # the same code a second time
            print("code sent twice:", again.status_code, again.json()["error"])
            # the challenge is the hash of a verifier this example knows, so the guessed one is the only thing wrong
            code = oauth_client.authorize_by_hand(issuer.url, url, challenge=oauth_client.s256("the-real-verifier"))
            stolen = {**exchanged, "code": code["code"], "code_verifier": "a-guessed-verifier"}
            print("wrong verifier:", httpx2.post(issuer.url + "/token", data=stolen).json()["error"])
            # method="plain" sends the verifier itself as the challenge, which OAuth 2.1 forbids
            plain = oauth_client.authorize_by_hand(issuer.url, url, challenge="the-real-verifier", method="plain")
            print("plain method:", plain["error"], "/", plain["error_description"])


asyncio.run(main())
