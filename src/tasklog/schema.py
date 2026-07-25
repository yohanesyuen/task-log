"""Frontmatter validation against the entry schema."""

from __future__ import annotations

import json
from importlib import resources

from jsonschema import Draft202012Validator

from . import extensions, paths


class ValidationError(Exception):
    """Raised when a frontmatter dict fails schema validation. Never raised
    after a file has been written — validation always happens first."""


def load_schema() -> dict:
    """Prefer the host repo's docs/task-log.schema.json when it exists, so a
    repo can tighten the schema for its own conventions; otherwise use the
    default shipped with this package."""
    override = paths.schema_override_path()
    if override.is_file():
        schema = json.loads(override.read_text(encoding="utf-8"))
    else:
        packaged = resources.files("tasklog").joinpath("data/schema.json")
        schema = json.loads(packaged.read_text(encoding="utf-8"))

    overlay = extensions.hook("schema_overlay")
    if overlay is not None:
        for prop, subschema in overlay().items():
            schema["properties"].setdefault(prop, {}).update(subschema)
    return schema


def validate_entry(frontmatter: dict) -> None:
    """Raise ValidationError with every failing field's message if the
    frontmatter dict doesn't conform to the entry schema. Never touches the
    filesystem beyond reading the schema itself."""
    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(frontmatter), key=lambda e: list(e.path))
    if errors:
        messages = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise ValidationError("; ".join(messages))
