"""Compare two releases of a tool's definition the way a client depends on them (chapter 11).

A client depends on a tool through its schemas. It sends arguments that the tool's `inputSchema` accepted when the
client listed it, and the SDK's client checks every non-error result against the `outputSchema` from its last
`tools/list` (`mcp/client/session.py`, `validate_tool_result`). So a release breaks clients when it:

- removes or renames an output field, or changes its type: code and models that read the old field find nothing,
  and a result missing a field the old schema requires fails the client's check;
- adds a required input, or removes an input: old callers don't send the first, and send the second for nothing
  (the SDK's server drops arguments it doesn't know, without an error);
- changes an input's type.

    from lib import contract
    contract.breaking_changes(old_tool, new_tool)   # ["output warehouses[].on_hand: removed", ...] or []
    contract.fields(tool.output_schema)             # {"sku": ("string", True), "warehouses[].on_hand": ...}

`fields(schema)` flattens a JSON Schema into dotted paths, with `[]` for array items, each with its type and
whether it is required. It follows local `$ref`s into `$defs`, which is how pydantic, and so the SDK, writes nested
models, and reads `anyOf` with `null` as an optional value of the other type. It is a reviewer's diff, not a full
JSON Schema comparison: it doesn't compare patterns, bounds or enums, and a change it doesn't flag can still break a
client. Pair it with a test that validates real results against the old schema (`jsonschema`, as the client does).

`validator(schema)` is the `jsonschema` validator class for that test. A schema may name its dialect in `$schema`,
and the base protocol says to validate by the declared dialect, or by JSON Schema 2020-12 when none is declared
("JSON Schema Usage"). So it picks the class from the schema, as the SDK's client does with `validator_for`
(`mcp/client/session.py`, `_output_schema_validator`), with 2020-12 as the default: pydantic's schemas declare no
`$schema`, so they get `Draft202012Validator`, and a draft-07 schema gets `Draft7Validator`.
"""
from __future__ import annotations

from typing import Any

import jsonschema


def _resolve(schema: dict[str, Any], root: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = root["$defs"][schema["$ref"].removeprefix("#/$defs/")]
    options = [s for s in schema.get("anyOf", []) if s.get("type") != "null"]
    return _resolve(options[0], root) if len(options) == 1 else schema


def fields(schema: dict[str, Any] | None, root: dict[str, Any] | None = None,
           prefix: str = "") -> dict[str, tuple[str, bool]]:
    """Every field `schema` describes, as {path: (type, required)}."""
    if not schema:
        return {}
    root = root or schema
    schema = _resolve(schema, root)
    found: dict[str, tuple[str, bool]] = {}
    required = set(schema.get("required", []))
    for name, child in schema.get("properties", {}).items():
        child = _resolve(child, root)
        path = f"{prefix}{name}"
        found[path] = (child.get("type", "any"), name in required)
        if child.get("type") == "object":
            found.update(fields(child, root, path + "."))
        elif child.get("type") == "array" and "items" in child:
            found.update(fields(child["items"], root, path + "[]."))
    return found


def breaking_changes(old, new) -> list[str]:
    """What in `new`, a later release of the tool `old`, breaks a client written against `old`."""
    problems = []
    old_out, new_out = fields(old.output_schema), fields(new.output_schema)
    for path, (kind, _) in old_out.items():
        if path not in new_out:
            problems.append(f"output {path}: removed")
        elif new_out[path][0] != kind:
            problems.append(f"output {path}: {kind} became {new_out[path][0]}")
    old_in, new_in = fields(old.input_schema), fields(new.input_schema)
    for path, (kind, required) in new_in.items():
        if path not in old_in and required:
            problems.append(f"input {path}: new and required")
        elif path in old_in and old_in[path][0] != kind:
            problems.append(f"input {path}: {old_in[path][0]} became {kind}")
    problems += [f"input {path}: removed" for path in old_in if path not in new_in]
    return problems


def validator(schema: dict[str, Any]) -> type:
    """The `jsonschema` validator class for the dialect `schema` declares, or for 2020-12 when it declares none."""
    return jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
