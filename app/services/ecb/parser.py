"""
ECB Stage 1: Template parser.

Dispatches on schema_version. Returns a TemplateModel for v2 templates.
For v1 templates (legacy passthrough), raises PassthroughTemplate so
callers can handle the passthrough path explicitly.
"""

from __future__ import annotations
import yaml
from pydantic import ValidationError

from app.models.template import TemplateModel


class ParseError(Exception):
    pass


class PassthroughTemplate(Exception):
    """Raised for schema_version 1 templates. Carries the raw parsed dict."""
    def __init__(self, raw: dict):
        self.raw = raw
        super().__init__("schema_version 1 template — use passthrough path")


def parse_template(yaml_str: str) -> TemplateModel:
    """
    Parse a template YAML string into a validated TemplateModel.

    Raises PassthroughTemplate for schema_version 1.
    Raises ParseError for validation failures.
    """
    try:
        raw = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ParseError(f"Invalid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ParseError("Template must be a YAML mapping")

    sv = raw.get("schema_version")
    if sv == 1:
        raise PassthroughTemplate(raw)

    if sv != 2:
        raise ParseError(f"Unsupported schema_version: {sv!r}. Expected 2.")

    try:
        return TemplateModel.model_validate(raw)
    except ValidationError as exc:
        raise ParseError(f"Template validation failed: {exc}") from exc
