"""record_return asks the person who opened a returned parcel what they found, in a form a resolver asks for."""
import asyncio
from typing import Annotated, Literal

from mcp import Client, MCPError
from mcp.server.mcpserver import AcceptedElicitation, Elicit, ElicitationResult, MCPServer, Resolve
from mcp.types import ElicitResult
from pydantic import BaseModel, Field

server = MCPServer("shop-returns", version="0.5.0")
Reason = Literal["damaged in transit", "wrong item sent", "missing part", "arrived late", "changed mind"]


class Inspection(BaseModel):          # the form: a flat object with primitive fields only
    reason: Reason = Field(description="The refund policy's reason that fits what you found")
    restock: bool = Field(description="The item can go back on sale")
    note: str | None = Field(default=None, max_length=200, description="Anything the refund should say")


def ask(order_id: str, sku: str) -> Elicit[Inspection]:
    return Elicit(f"You opened the return of {sku} from order {order_id}. What did you find?", Inspection)


@server.tool(description="Record what a returned item was like when its parcel was opened. The user fills in a form.")
def record_return(order_id: str, sku: str, found: Annotated[ElicitationResult[Inspection], Resolve(ask)]) -> str:
    if isinstance(found, AcceptedElicitation):
        return f"Recorded: {found.data.reason}, restock {found.data.restock}."
    return ("The user declined: don't record this return, and don't ask again." if found.action == "decline"
            else "The user closed the form without answering: ask again later.")


SCRIPT = [ElicitResult(action="accept", content={"reason": "damaged in transit", "restock": False}),
          ElicitResult(action="decline"), ElicitResult(action="cancel")]       # the scripted user's three answers
forms = []                                                                     # each form the user was shown


async def scripted_user(context, params) -> ElicitResult:
    forms.append(params.requested_schema)
    return SCRIPT.pop(0)


async def main() -> None:
    arguments = {"order_id": "O-1145", "sku": "KG-1043"}
    async with Client(server, elicitation_callback=scripted_user) as client:
        for action in ("accept", "decline", "cancel"):
            print(f"{action}:", (await client.call_tool("record_return", arguments)).content[0].text)
    print("form fields:", ", ".join(forms[0]["properties"]))
    print("required:", ", ".join(forms[0]["required"]))
    async with Client(server) as client:            # no elicitation_callback, so no elicitation capability
        try:
            await client.call_tool("record_return", arguments)
        except MCPError as error:
            print("client without elicitation:", error.error.code)


asyncio.run(main())
