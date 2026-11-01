"""Scan the 2025-era shop server and its host's OAuth setup for every dependency that revision 2026-07-28 removes or
deprecates, and every SDK 1.x API that SDK 2.x renamed or moved."""
import ast

from lib import legacy

found: dict[str, list[str]] = {rule.feature: [] for rule in legacy.RULES}


def where(tree: ast.Module, node: ast.AST, listing: str) -> str:
    """The function a node sits in, or the listing's setup when it sits in none."""
    for function in ast.walk(tree):
        if isinstance(function, ast.AsyncFunctionDef | ast.FunctionDef) and node in ast.walk(function):
            return function.name
    return f"{listing} setup"


for listing, source in legacy.LISTINGS.items():
    tree = ast.parse(source)                   # parsed, never run: SDK 1.x can't install beside 2.x
    for node in ast.walk(tree):
        for rule in legacy.RULES:
            if rule.matches(node) and where(tree, node, listing) not in found[rule.feature]:
                found[rule.feature].append(where(tree, node, listing))

print("written for:", legacy.WRITTEN_FOR)
for kind in ("removed", "deprecated", "sdk"):
    rules = [rule for rule in legacy.RULES if rule.kind == kind and found[rule.feature]]
    print(f"{kind} dependencies:", len(rules))
    for rule in rules:
        print(f"  {rule.feature}: {', '.join(found[rule.feature])} -> {rule.replacement}")
        if rule.removal:
            print(f"  {rule.feature} earliest removal: {rule.removal}")
