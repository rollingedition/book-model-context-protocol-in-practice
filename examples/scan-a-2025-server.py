"""Sorts the 2025-era server's dependencies, and its host's OAuth setup, into removed, deprecated and SDK changes, each
with its replacement. The prose's point, that removed dependencies fail for every client at the pinned revision, rests on the first group's
count and the functions it names."""
import ast

from lib import legacy

found: dict[str, list[str]] = {rule.feature: [] for rule in legacy.RULES}


def where(tree: ast.Module, node: ast.AST, listing: str) -> str:
    """The function a node sits in, or the listing's setup when it sits in none."""
    for function in ast.walk(tree):
        if isinstance(function, ast.AsyncFunctionDef | ast.FunctionDef) and node in ast.walk(function):
            return function.name
    return f"{listing} setup"                # module-level code, outside every function


for listing, source in legacy.LISTINGS.items():
    tree = ast.parse(source)                   # parsed, never run: SDK 1.x can't install beside 2.x
    for node in ast.walk(tree):
        for rule in legacy.RULES:
            # each function is listed once per feature, however many of its nodes match
            if rule.matches(node) and where(tree, node, listing) not in found[rule.feature]:
                found[rule.feature].append(where(tree, node, listing))

print("written for:", legacy.WRITTEN_FOR)
for kind in ("removed", "deprecated", "sdk"):
    rules = [rule for rule in legacy.RULES if rule.kind == kind and found[rule.feature]]   # a rule with no match is left out
    print(f"{kind} dependencies:", len(rules))
    for rule in rules:
        print(f"  {rule.feature}: {', '.join(found[rule.feature])} -> {rule.replacement}")
        if rule.removal:                          # only deprecated features have a removal date
            print(f"  {rule.feature} earliest removal: {rule.removal}")
