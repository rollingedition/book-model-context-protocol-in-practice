"""A token issued for another server, presented to the shop's server: the SDK's default accepts it, and it's refused once
the server checks the audience, either through AuthSettings or in the token verifier. The point rests on the partner's
token's status line in each configuration, and on the warning line that the default alone raises."""
import warnings

from mcp.server.auth.settings import AuthSettings

from lib import auth_server, http_mcp, shop_tools

PARTNER = "https://partner.example/mcp"                  # another MCP server, with the same authorization server
SCOPES = ["orders:read", "stock:read"]


def shop(issuer: str, validate_token_resource: bool | None, verifier_checks_aud: bool):
    def build(base_url: str):
        resource = base_url + "/mcp"
        # the verifier checks aud only when it's given an audience; None checks nothing
        verifier = auth_server.JwtVerifier(issuer, audience=resource if verifier_checks_aud else None)
        # None leaves the SDK's default in place, which is off and warns; True refuses other servers' tokens
        settings = AuthSettings(issuer_url=issuer, resource_server_url=resource, required_scopes=SCOPES,
                                validate_token_resource=validate_token_resource)
        return shop_tools.create_server(auth=settings, token_verifier=verifier).streamable_http_app()
    return build


with auth_server.serve() as issuer:
    for label, validate, in_verifier in [("SDK default", None, False), ("validate_token_resource=True", True, False),
                                         ("verifier checks aud", False, True)]:
        # record every warning, and show them all, so each configuration reports only what it raised
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with auth_server.serve_built(shop(issuer.url, validate, in_verifier)) as base_url:
                url = base_url + "/mcp"
                own = auth_server.mint(issuer.url, url, SCOPES)
                foreign = auth_server.mint(issuer.url, PARTNER, SCOPES)     # signed by the same authorization server
                for name, token in [("own token", own), ("partner's token", foreign)]:
                    response = http_mcp.post(url, "tools/list", headers={"Authorization": f"Bearer {token}"})
                    print(f"{label}, {name}:", response.status_code)
        print(f"{label}, warnings:", ", ".join(sorted({w.category.__name__ for w in caught})) or "none")
