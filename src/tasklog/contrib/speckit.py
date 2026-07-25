"""spec-kit conventions, as an opt-in extension.

Everything here was hard-wired into the core until it became clear that
projects without a `specs/` tree had no way to use the tool. It survives as
an extension rather than being deleted because these checks are genuinely
useful *when* a project does follow the convention: a typo'd scope becomes an
error instead of a silently-created directory, and `migrate` can find the
checklist without being told where it is.
"""

from __future__ import annotations

import re
from pathlib import Path

from .. import paths
from ..schema import ValidationError

SPEC_DIR_PATTERN = r"^[0-9]{3}-[a-z0-9-]+$"
TASK_ID_PATTERN = r"^T[0-9]+[a-z]?$"

_SPEC_DIR_RE = re.compile(SPEC_DIR_PATTERN)


class Extension:
    name = "speckit"

    def specs_root(self) -> Path:
        return paths.repo_root() / "specs"

    def validate_scope(self, scope: str) -> None:
        if not _SPEC_DIR_RE.match(scope):
            raise ValidationError(
                f"scope: {scope!r} is not a spec directory name (expected NNN-slug, "
                "e.g. 003-my-feature)"
            )
        if not (self.specs_root() / scope).is_dir():
            raise ValidationError(f"scope: no such directory specs/{scope}/")

    def checklist_path(self, scope: str) -> Path:
        return self.specs_root() / scope / "tasks.md"

    def schema_overlay(self) -> dict:
        # Tightens the core's deliberately-permissive identifier patterns back
        # to spec-kit's own, so a stray `--task auth-refactor` is rejected in a
        # repo whose IDs are all TNNN.
        return {
            "scope": {"pattern": SPEC_DIR_PATTERN},
            "task": {"pattern": TASK_ID_PATTERN},
        }
