"""The shop's policies: six short documents written for the book, kept in `examples/data/shop/policies/`.

Each file opens with its title (`# Refund policy`), an `Updated:` date and a one-sentence summary, then the policy
itself in Markdown. `load_policies()` reads those three lines, so a server can describe every policy in its resource
list without opening the files again on each request.

    from lib.policies import load_policies, policy
    [p.slug for p in load_policies()]    # ['data-handling', 'escalation', 'refund', 'returns', 'shipping', 'stock']
    policy("refund").path                # absolute path to refund.md

The policies are licensed CC BY 4.0 with the book's text; see the data card, `examples/data/shop/README.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path

POLICY_DIR = Path(__file__).resolve().parent.parent / "data" / "shop" / "policies"


@dataclass(frozen=True)
class Policy:
    slug: str                 # "refund": the file's name without ".md"
    title: str                # "Refund policy"
    summary: str              # the one-sentence summary under the title
    updated: date             # the date the policy last changed; fixed, never today's
    path: Path                # absolute path to the Markdown file

    @property
    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")


def _read(path: Path) -> Policy:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    title, updated, summary = lines[0].removeprefix("# "), lines[1].removeprefix("Updated: "), lines[2]
    return Policy(path.stem, title, summary, date.fromisoformat(updated), path)


@cache
def load_policies() -> tuple[Policy, ...]:
    """Every policy, sorted by slug."""
    return tuple(_read(path) for path in sorted(POLICY_DIR.glob("*.md")))


def policy(slug: str) -> Policy:
    """One policy by its slug, such as "refund". Raises KeyError for an unknown slug."""
    for found in load_policies():
        if found.slug == slug:
            return found
    raise KeyError(slug)
