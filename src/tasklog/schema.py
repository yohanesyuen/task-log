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

    _apply_extra_event_verbs(schema, _collect_extra_event_verbs())
    return schema


def _collect_extra_event_verbs() -> list[str]:
    """Verbs to append to `event`'s enum, gathered additively so a project
    can widen the vocabulary without restating (and risking dropping) the
    base list or the correction/retracted->supersedes invariant that goes
    with it. Two sources, both optional: a host repo's
    docs/task-log.events.json (`{"extra_events": [...]}`) and the active
    extension's `event_verbs()` hook, for a reusable convention shipped as
    an installable package."""
    verbs: list[str] = []

    override = paths.events_override_path()
    if override.is_file():
        data = json.loads(override.read_text(encoding="utf-8"))
        verbs.extend(data.get("extra_events", []))

    extra_from_extension = extensions.hook("event_verbs")
    if extra_from_extension is not None:
        verbs.extend(extra_from_extension())

    return verbs


def _apply_extra_event_verbs(schema: dict, extra_verbs: list[str]) -> None:
    """Append `extra_verbs` to schema["properties"]["event"]["enum"] in
    place, deduplicated and order-preserving. A no-op if the effective
    schema (e.g. after a full docs/task-log.schema.json replacement) has no
    `event` enum to extend -- there is nothing sane to append to."""
    if not extra_verbs:
        return
    enum = schema.get("properties", {}).get("event", {}).get("enum")
    if not isinstance(enum, list):
        return
    for verb in extra_verbs:
        if verb not in enum:
            enum.append(verb)


def validate_entry(frontmatter: dict) -> None:
    """Raise ValidationError with every failing field's message if the
    frontmatter dict doesn't conform to the entry schema. Never touches the
    filesystem beyond reading the schema itself."""
    validator = Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(frontmatter), key=lambda e: list(e.path))
    if errors:
        messages = [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]
        raise ValidationError("; ".join(messages))
