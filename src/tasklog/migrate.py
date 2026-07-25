"""Extracting dated notes already embedded in a noisy tasks.md line into
proper entries, then rewriting that line to bare form."""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from pathlib import Path

from . import extensions
from .entries import add_entry
from .schema import ValidationError

_NOTE_RE = re.compile(r"\*\*([A-Za-z]+)\s+(\d{4}-\d{2}-\d{2})\*\*:\s*")

# A dash-style connector (hyphen/en-dash/em-dash) commonly joins the task's
# base description to its first dated note (e.g. "... in foo.tsx — **Fixed
# 2026-07-16**: ..."). Stripped from the bare prefix so migration doesn't
# leave a dangling connector with nothing after it.
_TRAILING_CONNECTOR_RE = re.compile(r"\s*[-–—]\s*$")

# Maps the bold-date-prefixed clause's leading word to a schema-valid `event`.
# `correction`/`retracted` are deliberately excluded even though tasks.md
# files commonly use that pattern: the schema requires `supersedes` for
# those events, and inferring which prior entry a clause supersedes from
# prose alone would be guessing, not extraction — so they always surface as
# unmigrated instead (never guess).
_EVENT_WORD_MAP = {
    "implemented": "implemented",
    "verified": "verified",
    "fixed": "implemented",
    "reviewed": "verified",
    "gap": "gap",
    "deferred": "deferred",
    "blocked": "blocked",
    "note": "note",
    "noted": "note",
}


def _is_valid_date(date_str: str) -> bool:
    try:
        datetime.date.fromisoformat(date_str)
        return True
    except ValueError:
        return False


@dataclass
class ExtractedNote:
    event: str
    date: str
    text: str


@dataclass
class ExtractResult:
    rewritten_line: str
    notes: list[ExtractedNote]
    unmigrated: list[str]


def extract_dated_notes(line: str) -> ExtractResult:
    """Split a tasks.md line into its bare prefix plus zero or more
    bold-date-prefixed clauses (`**word YYYY-MM-DD**: prose`). A clause only
    becomes an ExtractedNote when its word maps to a known event AND its date
    is a real calendar date AND it has non-empty prose — anything else (an
    unrecognized word, an invalid date) is left untouched in `unmigrated`
    rather than guessed at."""
    matches = list(_NOTE_RE.finditer(line))
    if not matches:
        return ExtractResult(rewritten_line=line, notes=[], unmigrated=[])

    prefix = _TRAILING_CONNECTOR_RE.sub("", line[: matches[0].start()].rstrip())
    notes: list[ExtractedNote] = []
    unmigrated: list[str] = []
    kept_clauses: list[str] = []

    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
        clause_text = line[m.start():end].rstrip()
        body = line[m.end():end].strip()
        event = _EVENT_WORD_MAP.get(m.group(1).lower())
        if event and _is_valid_date(m.group(2)) and body:
            notes.append(ExtractedNote(event=event, date=m.group(2), text=body))
        else:
            unmigrated.append(clause_text)
            kept_clauses.append(clause_text)

    rewritten_line = " ".join([prefix, *kept_clauses]) if kept_clauses else prefix
    return ExtractResult(rewritten_line=rewritten_line, notes=notes, unmigrated=unmigrated)


_TASK_LINE_RE_CACHE: dict[str, re.Pattern] = {}


def _task_line_pattern(task: str) -> re.Pattern:
    pattern = _TASK_LINE_RE_CACHE.get(task)
    if pattern is None:
        # Whitespace-or-end, not \b: task IDs may contain hyphens, and \b
        # finds a boundary between "auth" and the "-" of "auth-refactor",
        # so \b would let --task auth rewrite auth-refactor's line.
        pattern = re.compile(rf"^-\s\[[ x~]\]\s+{re.escape(task)}(?=\s|$)")
        _TASK_LINE_RE_CACHE[task] = pattern
    return pattern


@dataclass
class MigrateResult:
    checklist_path: Path
    added: list[Path]
    unmigrated: list[str]


def resolve_checklist(scope: str, checklist: Path | str | None) -> Path:
    """An explicit --file always wins; otherwise only an extension that knows
    the project's layout can say where the checklist lives. The core makes no
    guess — a wrong guess would rewrite an unrelated file."""
    if checklist is not None:
        return Path(checklist)
    from_extension = extensions.hook("checklist_path")
    if from_extension is None:
        raise ValidationError(
            "file: pass --file <path> to say which checklist holds this task's line "
            "(only an --extension that knows the project layout can infer it)"
        )
    return from_extension(scope)


def migrate_task(scope: str, task: str, checklist: Path | str | None = None) -> MigrateResult:
    checklist_path = resolve_checklist(scope, checklist)
    if not checklist_path.is_file():
        raise ValidationError(f"file: no such file {checklist_path}")

    lines = checklist_path.read_text(encoding="utf-8").splitlines()
    pattern = _task_line_pattern(task)
    idx = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if idx is None:
        raise ValidationError(f"task: no line for {task} found in {checklist_path}")

    extracted = extract_dated_notes(lines[idx])

    added: list[Path] = []
    for note in extracted.notes:
        result = add_entry(scope=scope, task=task, event=note.event, summary=note.text, date=note.date)
        added.append(result.path)

    if extracted.notes:
        lines[idx] = extracted.rewritten_line
        checklist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return MigrateResult(checklist_path=checklist_path, added=added, unmigrated=extracted.unmigrated)
