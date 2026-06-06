"""
WhenParser — Phase 3 extended grammar.

Accepted grammar:
    Simple:
        <namespace>.<field> (==|!=) '<literal>'

    Compound (exactly one 'and'):
        <simple> and <simple>

Examples:
    registry.radarr.url_internal == 'present'
    reconcile.event_type == 'removed'
    registry.prowlarr_api_key != '' and registry.existing_prowlarr_app_id == ''

No Jinja, no 'or', no parentheses, no numeric comparisons, no method calls.
This grammar is intentionally minimal — it covers exactly what Phase 3 hooks need.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Union


# Single condition pattern: <dot.path> (==|!=) '<literal>'
_SINGLE = re.compile(
    r"^\s*"
    r"([\w][\w.]*[\w]|[\w]+)"   # lhs: dot-separated identifier
    r"\s*(==|!=)\s*"             # operator
    r"'([^']*)'"                 # rhs: single-quoted literal
    r"\s*$"
)


class WhenParseError(Exception):
    """Raised when a when: expression does not match the frozen grammar."""


@dataclass(frozen=True)
class WhenExpr:
    lhs: str
    op: str
    rhs: str

    def evaluate(self, context: dict) -> bool:
        value = _resolve_path(self.lhs, context)
        if value is None:
            return False
        actual = str(value)
        if self.op == "==":
            return actual == self.rhs
        return actual != self.rhs


@dataclass(frozen=True)
class WhenAndExpr:
    left: WhenExpr
    right: WhenExpr

    def evaluate(self, context: dict) -> bool:
        return self.left.evaluate(context) and self.right.evaluate(context)


def _parse_single(expr: str) -> WhenExpr:
    m = _SINGLE.match(expr)
    if not m:
        raise WhenParseError(
            f"Invalid when: condition {expr!r}. "
            "Accepted grammar: <namespace>.<field> (==|!=) '<literal>'"
        )
    return WhenExpr(lhs=m.group(1), op=m.group(2), rhs=m.group(3))


def parse_when(expr: str) -> Union[WhenExpr, WhenAndExpr]:
    """
    Parse a when: expression string.
    Raises WhenParseError if the expression does not match the frozen grammar.
    """
    if "{{" in expr or "}}" in expr:
        raise WhenParseError(
            f"Invalid when: expression {expr!r}. "
            "Jinja-style expressions ({{ }}) are not supported."
        )

    # Split on ' and ' (with surrounding spaces) — handles exactly one conjunction
    and_parts = re.split(r"\s+and\s+", expr, maxsplit=1)
    if len(and_parts) == 2:
        left = _parse_single(and_parts[0].strip())
        right = _parse_single(and_parts[1].strip())
        return WhenAndExpr(left=left, right=right)

    return _parse_single(expr.strip())


def _resolve_path(dotpath: str, context: dict) -> str | None:
    """Walk a dot-separated path into a nested dict. Returns None if absent."""
    parts = dotpath.split(".")
    current = context
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current if isinstance(current, (str, int, float, bool)) else str(current)
