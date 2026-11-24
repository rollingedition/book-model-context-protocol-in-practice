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

`widened_inputs(old, new)` is the other half, for a reviewer: input changes that break no client but let the tool
accept calls it refused before. Its docstring says what it lists and what it leaves out.

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


def _wider_bound(key: str, old: dict[str, Any], new: dict[str, Any]) -> str | None:
    """How `new` relaxes the bound `key` of `old`, or None when it doesn't."""
    if key not in old:
        return None
    if key not in new:
        return f"{key} {old[key]} dropped"
    looser = new[key] < old[key] if key == "minimum" else new[key] > old[key]
    return f"{key} {old[key]} became {new[key]}" if looser else None


def _values(schema: dict[str, Any]) -> list | None:
    """The values `enum` or `const` admits, or None when neither restricts them."""
    return [schema["const"]] if "const" in schema else schema.get("enum")


def widened_inputs(old, new) -> list[str]:
    """Input changes in `new`, a later release of the tool `old`, that let it accept calls `old` refused.

    None of these breaks a client, so `breaking_changes` doesn't report them, but each widens what a caller, or a
    model, can ask the tool to do. For each top-level argument it lists: a new argument; a required argument made
    optional; an `enum` or `const` that admits more values, or is dropped; a `pattern` dropped or changed (it can't
    tell a looser pattern from a stricter one, so a person reads it); a `maxLength` or `maximum` raised or dropped,
    and a `minimum` lowered or dropped. For the arguments object, it lists a new or wider `additionalProperties`:
    `false` made a schema or allowed, or a schema made allowed.

    It leaves out: properties nested inside an argument, and array items; a type widened or made nullable;
    `minLength`, `exclusiveMinimum`, `exclusiveMaximum`, `format`, `multipleOf` and the array and object bounds;
    `oneOf`, `allOf`, `not` and the conditional keywords; one `additionalProperties` schema replaced by another; and
    any change in what the tool does behind the same schema. A wider input isn't always more authority, so the list
    is for a person to read, not a gate.
    """
    widened = []
    old_in, new_in = old.input_schema or {}, new.input_schema or {}
    old_args, new_args = old_in.get("properties", {}), new_in.get("properties", {})
    old_required, new_required = set(old_in.get("required", [])), set(new_in.get("required", []))
    for name, schema in new_args.items():
        if name not in old_args:
            widened.append(f"{name}: new, {'required' if name in new_required else 'optional'}")
            continue
        was, now = _resolve(old_args[name], old_in), _resolve(schema, new_in)
        if name in old_required and name not in new_required:
            widened.append(f"{name}: required became optional")
        old_values, new_values = _values(was), _values(now)
        if old_values is not None and new_values is None:
            widened.append(f"{name}: enum dropped")
        elif old_values is not None and (added := [v for v in new_values if v not in old_values]):
            widened.append(f"{name}: admits {', '.join(map(str, added))}")
        if "pattern" in was and was["pattern"] != now.get("pattern"):
            widened.append(f"{name}: pattern {'changed' if 'pattern' in now else 'dropped'}")
        widened += [f"{name}: {change}" for key in ("maxLength", "maximum", "minimum")
                    if (change := _wider_bound(key, was, now))]
    old_extra = old_in.get("additionalProperties", True)              # absent means any extra key is allowed
    new_extra = new_in.get("additionalProperties", True)
    if old_extra is not True and old_extra != new_extra and (new_extra is True or old_extra is False):
        widened.append("additionalProperties: wider")
    return widened


def validator(schema: dict[str, Any]) -> type:
    """The `jsonschema` validator class for the dialect `schema` declares, or for 2020-12 when it declares none."""
    return jsonschema.validators.validator_for(schema, default=jsonschema.Draft202012Validator)
