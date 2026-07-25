"""Opt-in extension points.

The core knows nothing about any particular project layout: a scope is just a
name, a task is just an identifier, and `migrate` is told which file to read.
Conventions that *do* assume a layout — spec-kit's `specs/<spec>/tasks.md`,
its `003-slug` directory names, its `T042` task IDs — live in an extension
instead, so a project that doesn't follow them is never asked to.

An extension is any object with a `name` attribute (used to restore the active
extension across nested CLI invocations) plus one or more of the hooks below;
the hooks are all optional and the core falls back to generic behavior when
absent:

    validate_scope(scope)      -> raise ValidationError to reject a scope
    checklist_path(scope)      -> Path `migrate` should read when --file is omitted
    schema_overlay()           -> {property: subschema} merged over the base schema

Extensions are discovered through the `tasklog.extensions` entry point group,
so a project can ship its own without this package knowing about it.
"""

from __future__ import annotations

import os
from importlib import metadata
from typing import Any

ENTRY_POINT_GROUP = "tasklog.extensions"
EXTENSION_ENV_VAR = "TASKLOG_EXTENSION"

_active: Any | None = None


class UnknownExtension(Exception):
    """Raised when a named extension isn't installed. Never falls back to the
    generic core silently — a typo'd extension name would otherwise look like
    it worked while skipping every convention it was supposed to enforce."""


def available() -> dict[str, metadata.EntryPoint]:
    return {ep.name: ep for ep in metadata.entry_points(group=ENTRY_POINT_GROUP)}


def load(name: str) -> Any:
    found = available().get(name)
    if found is None:
        known = ", ".join(sorted(available())) or "(none installed)"
        raise UnknownExtension(f"no extension named {name!r}. Available: {known}")
    extension = found.load()()
    if not getattr(extension, "name", None):
        raise UnknownExtension(
            f"extension {name!r} has no `name` attribute — it is required so the "
            "active extension can be restored after a nested invocation"
        )
    return extension


def set_active(name: str | None) -> None:
    global _active
    _active = load(name) if name else None


def active_name() -> str | None:
    return getattr(_active, "name", None) if _active is not None else None


def resolve_from_environment() -> str | None:
    return os.environ.get(EXTENSION_ENV_VAR) or None


def hook(name: str) -> Any | None:
    """The active extension's implementation of `name`, or None if there is no
    active extension or it doesn't implement that hook."""
    if _active is None:
        return None
    return getattr(_active, name, None)
