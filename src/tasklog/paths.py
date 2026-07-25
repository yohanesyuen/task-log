"""Where the schema, entries, and specs live relative to the *host* repo — the
repo whose task history is being logged, which is no longer the repo this
package is installed from."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT_ENV_VAR = "TASKLOG_REPO_ROOT"

_explicit_root: Path | None = None


class RepoRootNotFound(Exception):
    """Raised when no host repo root could be resolved. Never falls back to
    the current directory: a silent fallback would write docs/task-log/ into
    whatever directory the caller happened to be standing in."""


def set_repo_root(root: Path | str | None) -> None:
    global _explicit_root
    _explicit_root = Path(root).resolve() if root is not None else None


def repo_root_override() -> Path | None:
    """The currently-set explicit root, so a caller invoking the CLI more than
    once in a single process can restore what was there before."""
    return _explicit_root


def _walk_up_for_git(start: Path) -> Path | None:
    # Anchors on .git: it's the one marker every host repo has, regardless of
    # whether it keeps specs/, a TODO.md, or nothing but source.
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def repo_root() -> Path:
    """Resolve the host repo root: explicit override, then $TASKLOG_REPO_ROOT,
    then the nearest ancestor of the working directory containing .git."""
    if _explicit_root is not None:
        return _explicit_root

    from_env = os.environ.get(REPO_ROOT_ENV_VAR)
    if from_env:
        return Path(from_env).resolve()

    found = _walk_up_for_git(Path.cwd().resolve())
    if found is not None:
        return found

    raise RepoRootNotFound(
        f"no host repo root found: {Path.cwd()} has no .git ancestor. "
        f"Pass --repo-root <path> or set {REPO_ROOT_ENV_VAR}."
    )


def schema_override_path() -> Path:
    return repo_root() / "docs" / "task-log.schema.json"


def task_log_root() -> Path:
    return repo_root() / "docs" / "task-log"
