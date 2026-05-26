"""
WhenParser — Phase 1 frozen grammar.

Accepted grammar (exactly):
    <namespace>.<field> (==|!=) '<literal>'

Examples:
    registry.radarr.url_internal == 'present'
    reconcile.event_type == 'removed'
    reconcile.event_type != 'changed'

Everything else is a parse error. No Jinja, no boolean operators,
no numeric comparisons, no method calls.

The platform does not implement a general expression language.
This grammar is intentionally minimal — it covers the only cases
needed in Phase 1 without opening a path to arbitrary evaluation.
"""

from __future__ import annotations
import re
from dataclasses import dataclass


# Strict pattern: <one_or_more_word_segments_with_dots> (==|!=) '<literal>'
# The left side allows exactly one dot-separated identifier path.
# The right side must be a single-quoted string literal.
_PATTERN = re.compile(
    r"^\s*"
    r"([\w][\w.]*[\w]|[\w]+)"   # lhs: dot-separated identifier, no leading/trailing dot
    r"\s*(==|!=)\s*"             # operator
    r"'([^']*)'"                 # rhs: single-quoted literal (no embedded single quotes)
    r"\s*$"
)


class WhenParseError(Exception):
    """Raised when a when: expression does not match the frozen grammar."""


@dataclass(frozen=True)
class WhenExpr:
    lhs: str        # e.g. "registry.radarr.url_internal"
    op: str         # "==" or "!="
    rhs: str        # literal value, e.g. "present"

    def evaluate(self, context: dict) -> bool:
        """
        Evaluate against a flat context dict.
        The lhs is resolved by walking dot-separated segments into nested dicts.
        Returns False (not True) if any segment is absent — absent = condition false.
        """
        value = _resolve_path(self.lhs, context)
        if value is None:
            # Missing path → condition is false (not an error at evaluation time)
            return False
        actual = str(value)
        if self.op == "==":
            return actual == self.rhs
        return actual != self.rhs


def parse_when(expr: str) -> WhenExpr:
    """
    Parse a when: expression string into a WhenExpr.
    Raises WhenParseError if the expression does not match the frozen grammar.
    """
    m = _PATTERN.match(expr)
    if not m:
        raise WhenParseError(
            f"Invalid when: expression {expr!r}. "
            "Accepted grammar: <namespace>.<field> (==|!=) '<literal>'. "
            "Jinja expressions and complex conditions are not supported."
        )
    lhs, op, rhs = m.group(1), m.group(2), m.group(3)
    # Additional guard: reject expressions that look like Jinja
    if "{{" in expr or "}}" in expr:
        raise WhenParseError(
            f"Invalid when: expression {expr!r}. "
            "Jinja-style expressions ({{ }}) are not supported. "
            "Use the grammar: <namespace>.<field> (==|!=) '<literal>'"
        )
    return WhenExpr(lhs=lhs, op=op, rhs=rhs)


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
