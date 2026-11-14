"""The support host's Client ID Metadata Document, the checks an authorization server makes on it, and the SDK's client
sending its URL as the client ID, with and without the authorization server's support. The point rests on the
`client_id sent` line and on the fallback's error line, which show what the SDK did in each case."""
import asyncio

from mcp.client.auth import OAuthRegistrationError

from lib import auth_server, oauth_client, protected_shop

document = auth_server.client_document()                      # served at auth_server.CLIENT_ID
print("client_id:", document["client_id"])
print("redirect_uris:", ", ".join(document["redirect_uris"]))
print("token_endpoint_auth_method:", document["token_endpoint_auth_method"])
for label, url, candidate in [
        ("as published", auth_server.CLIENT_ID, document),
        ("with a secret", auth_server.CLIENT_ID, auth_server.client_document(client_secret="not-a-secret")),
        ("another client_id", auth_server.CLIENT_ID, auth_server.client_document(client_id="https://partner.example/")),
        ("on http", "http://support.fernhill.example/oauth/client.json", document)]:
    print(f"document {label}:", auth_server.document_problem(url, candidate) or "accepted")
try:
    oauth_client.provider("http://127.0.0.1/mcp", browser=oauth_client.ScriptedBrowser(),
                          client_metadata_url="http://localhost:4280/client.json")   # the SDK checks the scheme when it's built
except ValueError:
    print("SDK given an http client ID: ValueError")


async def connect(**server_options) -> None:
    with auth_server.serve(**server_options) as issuer, protected_shop.serve(issuer.url) as url:
        browser = oauth_client.ScriptedBrowser()
        try:
            async with oauth_client.connect(url, browser=browser) as client:
                await client.list_tools()
            print("client_id sent:", browser.requests[0]["client_id"])
        except* OAuthRegistrationError as group:                 # the SDK fell back to registration
            print("without metadata document support:", group.exceptions[0])


asyncio.run(connect())                                  # the shop's server advertises metadata document support
asyncio.run(connect(advertise_cimd=False))              # a server that doesn't, so the SDK registers instead
