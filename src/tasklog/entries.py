"""Entry file I/O and the add/query/render operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import extensions, paths
from .schema import ValidationError, validate_entry

DEFAULT_SCOPE = "default"

_UNSAFE_SCOPE_PARTS = ("/", "\\", "..")

# The task-ID group is greedy on purpose: an ID may itself end in digits
# (sprint-01 -> 2026-07-26-sprint-01-01.md), and only a greedy match
# backtracks to leave the trailing two digits as the sequence number.
_ENTRY_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)-(\d{2})\.md$")


def validate_scope_name(scope: str) -> None:
    """Reject anything that would escape the log root when joined as a path.
    Called on read paths too, not just writes: the schema only runs on
    frontmatter, so query/render would otherwise join an unchecked scope."""
    if not scope or any(part in scope for part in _UNSAFE_SCOPE_PARTS):
        raise ValidationError(f"scope: {scope!r} is not a usable directory name")


def next_seq(scope: str, task: str, date: str) -> str:
    """Next unused zero-padded sequence for this exact (scope, task, date)
    triple. Computed by globbing the target directory at call time — never
    trusted from a caller-supplied value, so two racing `add` invocations
    each recompute independently rather than trusting stale state."""
    target_dir = paths.task_log_root() / scope
    if not target_dir.is_dir():
        return "01"
    highest = 0
    for entry in target_dir.iterdir():
        m = _ENTRY_FILENAME_RE.match(entry.name)
        if m and m.group(1) == date and m.group(2) == task:
            highest = max(highest, int(m.group(3)))
    return f"{highest + 1:02d}"


def entry_path(scope: str, task: str, date: str, seq: str) -> Path:
    return paths.task_log_root() / scope / f"{date}-{task}-{seq}.md"


def serialize_entry(frontmatter: dict, body: str) -> str:
    fm = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False).strip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"


def parse_entry_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing opening frontmatter delimiter")
    _, _, rest = text.partition("---\n")
    fm_text, sep, body = rest.partition("\n---\n")
    if not sep:
        raise ValueError(f"{path}: missing closing frontmatter delimiter")
    frontmatter = yaml.safe_load(fm_text) or {}
    return {"path": path, "frontmatter": frontmatter, "body": body.strip()}


def write_entry_atomic(path: Path, frontmatter: dict, body: str) -> None:
    """Write to a temp file in the same directory, then rename into place,
    so a crash mid-write never leaves a partially-written entry visible to
    query/render. Refuses to overwrite an existing file — entries are never
    edited in place."""
    if path.exists():
        raise FileExistsError(f"{path} already exists — entries are never overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(serialize_entry(frontmatter, body), encoding="utf-8")
    tmp_path.rename(path)


@dataclass
class AddResult:
    path: Path
    created_scope: bool


def add_entry(
    *,
    scope: str,
    task: str,
    event: str,
    status: str | None = None,
    tags: list[str] | None = None,
    related: list[str] | None = None,
    refs: list[str] | None = None,
    supersedes: str | None = None,
    summary: str | None = None,
    body: str | None = None,
    date: str,
) -> AddResult:
    # A scope is just a name by default — any layout requirement (that it
    # match an existing directory, follow a naming convention) is an opt-in
    # extension's business, not the core's.
    validate_scope_name(scope)
    validate_scope = extensions.hook("validate_scope")
    if validate_scope is not None:
        validate_scope(scope)

    if supersedes is not None:
        # Cycles are structurally impossible, not just discouraged: `supersedes`
        # must name a file that already exists (checked below), entries are
        # never edited after being written, so a chain can only ever point
        # backward to something that existed before this call. No separate
        # cycle-detection is needed as long as this existence check holds.
        supersedes_path = paths.task_log_root() / scope / supersedes
        if not supersedes_path.is_file():
            raise ValidationError(
                f"supersedes: no such entry docs/task-log/{scope}/{supersedes} "
                "— an entry can only supersede/retract an entry that actually exists, "
                "in the same scope"
            )

    frontmatter = {"scope": scope, "task": task, "event": event}
    if status is not None:
        frontmatter["status"] = status
    if tags:
        frontmatter["tags"] = tags
    if related:
        frontmatter["related"] = related
    if refs:
        frontmatter["refs"] = refs
    if supersedes is not None:
        frontmatter["supersedes"] = supersedes

    validate_entry(frontmatter)

    prose_parts = [p for p in (summary, body) if p]
    if not prose_parts:
        raise ValidationError("at least one of summary/body is required")
    prose = "\n\n".join(prose_parts)

    seq = next_seq(scope, task, date)
    path = entry_path(scope, task, date, seq)
    created_scope = not path.parent.is_dir()
    write_entry_atomic(path, frontmatter, prose)
    return AddResult(path=path, created_scope=created_scope)


def query_entries(scope: str, task: str | None = None) -> list[dict]:
    validate_scope_name(scope)
    target_dir = paths.task_log_root() / scope
    if not target_dir.is_dir():
        return []
    files = sorted(target_dir.glob("*.md"))
    entries = [parse_entry_file(p) for p in files]
    if task:
        entries = [e for e in entries if e["frontmatter"].get("task") == task]
    return entries


def render_view(scope: str | None = None) -> tuple[Path, str]:
    if scope is not None:
        validate_scope_name(scope)
    task_log_root = paths.task_log_root()
    scopes = (
        [scope] if scope
        else sorted(p.name for p in task_log_root.iterdir() if p.is_dir()) if task_log_root.is_dir()
        else []
    )

    # A project that never groups its tasks logs everything under the default
    # scope; a heading naming it would be noise on every entry.
    show_scope_headings = scopes != [DEFAULT_SCOPE]

    lines = ["# Task Log", ""]
    for s in scopes:
        entries = query_entries(s)
        if not entries:
            continue
        if show_scope_headings:
            lines.append(f"## {s}")
            lines.append("")
        by_task: dict[str, list[dict]] = {}
        for e in entries:
            by_task.setdefault(e["frontmatter"].get("task", "?"), []).append(e)
        for task_id in sorted(by_task):
            lines.append(f"### {task_id}")
            lines.append("")
            for e in by_task[task_id]:
                fm = e["frontmatter"]
                date = e["path"].name[:10]
                header = f"**{date} — {fm.get('event')}**"
                if fm.get("status"):
                    header += f" ({fm['status']})"
                lines.append(header)
                if fm.get("tags"):
                    lines.append(f"tags: {', '.join(fm['tags'])}")
                if fm.get("related"):
                    lines.append(f"related: {', '.join(fm['related'])}")
                if fm.get("refs"):
                    lines.append(f"refs: {', '.join(fm['refs'])}")
                lines.append("")
                lines.append(e["body"])
                lines.append("")
        lines.append("")

    out_path = (
        (paths.repo_root() / "docs" / f"task-log-{scope}.md") if scope
        else (paths.repo_root() / "docs" / "task-log.md")
    )
    return out_path, "\n".join(lines).rstrip() + "\n"
