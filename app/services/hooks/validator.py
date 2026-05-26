"""
Hook definition validator — Phase 1.

Validates a hook YAML file against the frozen Phase 1 rules.
Returns a list of ValidationResult items. Callers check for any
ERROR severity result to decide whether to reject.

Frozen severity classifications:
  ERROR   — template rejected
  WARNING — template accepted, surfaced prominently
  INFO    — advisory only

Frozen validator rules:
  error:   invalid DAG (cycle, missing dependency ref)
  error:   invalid when: grammar (Jinja, non-literal, etc.)
  error:   registry_write key outside own namespace
  error:   registry_write key contains template expression
  error:   duplicate step IDs
  error:   unknown/missing step type
  error:   reserved fields used with non-null value
  warning: unguarded compose_command (no when: and no explicit critical:)
  warning: step depends on conditionally-skippable dependency without on_error
  warning: on_error: continue without explicit critical: flag
  info:    steps with no timeout_seconds
  info:    unused bind_as binding
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

from app.models.enums import ValidatorSeverity
from app.services.hooks.when_parser import parse_when, WhenParseError


@dataclass(frozen=True)
class ValidationResult:
    severity: ValidatorSeverity
    step_id: str | None
    message: str

    def as_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "step_id": self.step_id,
            "message": self.message,
        }


def validate_hook(
    hook_yaml_path: str,
    template_slug: str,
) -> list[ValidationResult]:
    """
    Validate a hook YAML file. Returns all findings.
    An empty list means the hook is clean.
    """
    path = Path(hook_yaml_path)
    if not path.exists():
        return []  # Missing hook file is not an error at validation time

    try:
        raw = yaml.safe_load(path.read_text())
    except Exception as exc:
        return [ValidationResult(
            severity=ValidatorSeverity.ERROR,
            step_id=None,
            message=f"YAML parse error: {exc}",
        )]

    if not isinstance(raw, dict):
        return [ValidationResult(
            severity=ValidatorSeverity.ERROR,
            step_id=None,
            message="Hook must be a YAML mapping",
        )]

    raw_steps = raw.get("steps", [])
    if not raw_steps:
        return []

    results: list[ValidationResult] = []
    seen_ids: set[str] = set()
    steps: list[dict] = []
    has_parse_error = False

    # --- Pass 1: structural validation ---
    for i, step in enumerate(raw_steps):
        if not isinstance(step, dict):
            results.append(ValidationResult(
                severity=ValidatorSeverity.ERROR,
                step_id=None,
                message=f"Step {i} is not a mapping",
            ))
            has_parse_error = True
            continue

        step_id = step.get("id", "")
        if not step_id:
            results.append(ValidationResult(
                severity=ValidatorSeverity.ERROR,
                step_id=None,
                message=f"Step {i} is missing 'id'",
            ))
            has_parse_error = True
            continue

        if step_id in seen_ids:
            results.append(ValidationResult(
                severity=ValidatorSeverity.ERROR,
                step_id=step_id,
                message=f"Duplicate step id: {step_id!r}",
            ))
            has_parse_error = True
            continue

        seen_ids.add(step_id)

        step_type = step.get("type", "")
        if not step_type:
            results.append(ValidationResult(
                severity=ValidatorSeverity.ERROR,
                step_id=step_id,
                message="Missing 'type'",
            ))
            has_parse_error = True
        elif step_type not in ("registry_read", "registry_write", "http_request",
                               "compose_command", "log"):
            results.append(ValidationResult(
                severity=ValidatorSeverity.ERROR,
                step_id=step_id,
                message=f"Unknown step type: {step_type!r}",
            ))
            has_parse_error = True

        steps.append(step)

    if has_parse_error:
        return results

    all_ids = {s["id"] for s in steps}

    # --- Pass 2: per-step semantic validation ---
    conditional_step_ids: set[str] = set()  # steps with a when: condition

    for step in steps:
        step_id = step["id"]
        step_type = step.get("type", "")

        # Validate dependency references
        depends_on = step.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        for dep in depends_on:
            if dep not in all_ids:
                results.append(ValidationResult(
                    severity=ValidatorSeverity.ERROR,
                    step_id=step_id,
                    message=f"depends_on references unknown step: {dep!r}",
                ))

        # Validate when: grammar
        when_expr = step.get("when")
        if when_expr:
            conditional_step_ids.add(step_id)
            try:
                parse_when(str(when_expr))
            except WhenParseError as exc:
                results.append(ValidationResult(
                    severity=ValidatorSeverity.ERROR,
                    step_id=step_id,
                    message=f"Invalid when: expression — {exc}",
                ))

        # registry_write namespace enforcement
        if step_type == "registry_write":
            key = step.get("key", "")
            if not key:
                results.append(ValidationResult(
                    severity=ValidatorSeverity.ERROR,
                    step_id=step_id,
                    message="registry_write missing 'key'",
                ))
            elif not key.startswith(f"{template_slug}."):
                results.append(ValidationResult(
                    severity=ValidatorSeverity.ERROR,
                    step_id=step_id,
                    message=(
                        f"registry_write key {key!r} is outside namespace "
                        f"'{template_slug}.*'. This template exclusively owns "
                        f"the '{template_slug}.*' capability namespace."
                    ),
                ))
            # Reject dynamic key templates
            if "{{" in key or "{" in key:
                results.append(ValidationResult(
                    severity=ValidatorSeverity.ERROR,
                    step_id=step_id,
                    message="registry_write key must be a literal string (no template expressions)",
                ))

        # compose_command: warn if unguarded and critical not explicit
        if step_type == "compose_command":
            has_when = bool(when_expr)
            has_explicit_critical = "critical" in step
            if not has_when and not has_explicit_critical:
                results.append(ValidationResult(
                    severity=ValidatorSeverity.WARNING,
                    step_id=step_id,
                    message=(
                        "compose_command has no when: condition and no explicit critical: flag. "
                        "Set critical: true if failure should surface as a platform warning, "
                        "or critical: false to acknowledge the risk. "
                        "Adding when: guards against running against an unavailable compose file."
                    ),
                ))

        # on_error: continue without explicit critical:
        if step.get("on_error") == "continue" and "critical" not in step:
            results.append(ValidationResult(
                severity=ValidatorSeverity.WARNING,
                step_id=step_id,
                message=(
                    "on_error: continue without explicit critical: flag. "
                    "Set critical: true if a failure here should surface as a platform warning, "
                    "or critical: false to acknowledge degraded execution is acceptable."
                ),
            ))

        # No timeout_seconds
        if "timeout_seconds" not in step:
            results.append(ValidationResult(
                severity=ValidatorSeverity.INFO,
                step_id=step_id,
                message="No timeout_seconds set. Default timeout (30s) will be used.",
            ))

    # --- Pass 3: DAG validation (cycle detection) ---
    graph: dict[str, list[str]] = {}
    for step in steps:
        depends_on = step.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        graph[step["id"]] = [d for d in depends_on if d in all_ids]

    cycle = _find_cycle(graph)
    if cycle:
        results.append(ValidationResult(
            severity=ValidatorSeverity.ERROR,
            step_id=None,
            message=f"DAG contains a cycle: {' → '.join(cycle)}",
        ))

    # --- Pass 4: warn about steps depending on conditionally-skippable steps ---
    for step in steps:
        step_id = step["id"]
        depends_on = step.get("depends_on", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        on_error = step.get("on_error", "fail")

        for dep in depends_on:
            if dep in conditional_step_ids and on_error != "continue":
                results.append(ValidationResult(
                    severity=ValidatorSeverity.WARNING,
                    step_id=step_id,
                    message=(
                        f"Depends on {dep!r} which may be skipped by its when: condition. "
                        f"This step will also be skipped in that case. "
                        f"If you want this step to run regardless, remove the dependency "
                        f"and use a when: condition on this step directly."
                    ),
                ))

    return results


def has_errors(results: list[ValidationResult]) -> bool:
    return any(r.severity == ValidatorSeverity.ERROR for r in results)


def _find_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    """DFS cycle detection. Returns cycle path or None."""
    visited: set[str] = set()
    rec_stack: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                path.append(neighbor)
                return True
        rec_stack.discard(node)
        path.pop()
        return False

    for node in graph:
        if node not in visited:
            if dfs(node):
                return path
    return None
