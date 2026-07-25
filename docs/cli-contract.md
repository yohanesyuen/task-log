# CLI Contract: `tasklog`

CLI-only tool — no HTTP/API surface. This documents its subcommands,
inputs, outputs, and exit codes as the interface exposed to other systems
(other tooling, CI, and agents driving it).

## Global options

Available on every subcommand, before the subcommand name:

- `--repo-root <path>` — the host repo to log against. Falls back to
  `$TASKLOG_REPO_ROOT`, then to the nearest ancestor of the working
  directory containing `.git`. If none resolves, exit 2 — never a silent
  fallback to the working directory.
- `--extension <name>` — an opt-in convention pack (bundled: `speckit`).
  Falls back to `$TASKLOG_EXTENSION`. An unknown name is exit 2, never a
  silent fallback to generic behavior. Extensions may add scope validation,
  supply `migrate`'s default checklist path, and tighten the schema.
- `--version`, `--help`

## `tasklog add`

**Purpose**: Create exactly one new Task Log Entry file. Never edits or
overwrites an existing file.

**Inputs** (flags, all validated before any file write):
- `--scope <name>` (optional, default `default`) — a namespace grouping
  related tasks. Free-form unless an extension constrains it.
- `--task <task-id>` (required)
- `--event <event>` (required, must be one of the schema's enum)
- `--status <status>` (optional)
- `--tags <csv>` (optional)
- `--related <csv>` (optional)
- `--refs <csv>` (optional)
- `--supersedes <filename>` (required iff `--event` is `correction` or
  `retracted`, per the schema's conditional requirement)
- `--summary <string>` and/or `--body <string>` / `--body-file <path>`
  (at least one required — this becomes the prose body)
- `--date <YYYY-MM-DD>` (optional, defaults to today — only used to
  backdate an entry when migrating historical notes, see `migrate` below)

**Behavior**:
1. Give the active extension (if any) a chance to reject `--scope`. With no
   extension, any filename-safe scope name is accepted.
2. Build the frontmatter object from flags; validate against
   the entry schema. Any failure → exit 2, print the specific
   field(s) and reason(s), no file created.
3. Compute the target filename: `<date>-<task>-<seq>.md` where `<seq>` is
   the next unused zero-padded integer (starting `01`) for that exact
   `(scope, date, task)` triple, determined by globbing the target directory
   — never by trusting a caller-supplied sequence number.
4. Create `docs/task-log/<scope>/` if it doesn't exist, printing a note to
   stderr when that scope is being used for the first time — without an
   extension to validate scopes, that note is the only signal of a typo.
5. Write the file atomically (write to a temp file in the same directory,
   `os.rename` into place) so a crash mid-write never leaves a
   partially-written entry visible to `query`/`render`.
6. On success: exit 0, print the created file's path.

**Idempotency**: none by design — every successful `add` creates a new,
distinct file. Calling `add` twice with identical flags (and no explicit
`--date`) on the same day produces two entries (`-01`, `-02`), not one
overwritten entry. This is intentional: the tool has no way to know two
calls describe "the same" event rather than two real events on the same
day, and guessing wrong in the overwrite direction would lose history.

## `tasklog query`

**Purpose**: Read back entries for a task or a scope, in chronological order.

**Inputs**:
- `--scope <name>` (optional, default `default`)
- `--task <task-id>` (optional — omit to return every entry for the scope)
- `--format json|md` (optional, default `md` for human reading; `json`
  emits an array of the parsed frontmatter+body objects for scripting)

**Behavior**: Glob `docs/task-log/<scope>/`, filter by `--task` if given,
sort by filename (chronological by construction — the date prefix), parse
each file's frontmatter + body, and print in the requested format. Exit 0
even if zero entries are found (prints an empty result, not an error) —
"no history yet" is a normal state, not a failure.

## `tasklog render`

**Purpose**: Regenerate the human-readable summary document(s) from every
entry currently on disk.

**Inputs**:
- `--scope <name>` (optional — omit to render the repo-wide
  `docs/task-log.md`; provide to render just that scope's own file,
  `docs/task-log-<scope>.md`)

**Behavior**: Deterministic — same entry set always produces byte-identical
output. Overwrites the target rendered file completely (never merges with
or preserves prior manual edits). Exit 0 on success.

## `tasklog migrate`

**Purpose**: Convert one existing checklist line's embedded dated prose
into Task Log Entries, then rewrite that line to bare form.

**Inputs**:
- `--scope <name>` (optional, default `default`)
- `--task <task-id>` (required) — identifies the exact line in the checklist
- `--file <path>` — the checklist to read. Required unless the active
  extension supplies a default (`speckit` infers `specs/<scope>/tasks.md`).
  The core never guesses: a wrong guess would rewrite an unrelated file.

**Behavior**:
1. Locate the line matching `- [ ]`/`- [x]` + the given task ID, requiring
   whitespace or end-of-line after the ID so a hyphenated ID can't match a
   longer sibling. Not found → exit 2, no changes.
2. Parse embedded dated notes from the line's trailing prose (the tool's
   own extraction heuristic — bounded to recognizable date-prefixed
   sentences/bold-date markers matching the patterns actually observed in
   real checklist files). Any note whose date or boundary is
   ambiguous is *not* silently guessed — it is left in place in the
   rewritten line's own trailing note (not extracted), and the tool reports
   what it left behind so a human can finish the extraction manually —
   ambiguous notes are surfaced, never guessed.
3. For each cleanly-extracted note: `add` an entry with `--date` set to the
   note's original date and `--event note` (or a more specific inferred
   event where the prose makes it unambiguous, e.g. text starting
   "**implemented**" → `event implemented`), preserving the checkbox's
   current `[ ]`/`[x]` state as the entry's `status` field only —
   **never** altering the checkbox itself.
4. Rewrite the source line in place to
   `- [ ]`/`- [x] <ID> <original plain description>`, leaving every other
   line in the checklist byte-for-byte untouched.
5. Exit 0 and print: how many entries were created, and (if any) which
   notes were left behind as ambiguous for manual follow-up.

**Non-goals**: no repo-wide sweep mode — `migrate` always operates on
exactly one `(scope, task)` pair per invocation. A future wrapper
script that calls it in a loop across many tasks is explicitly out of scope
for this feature.

## Exit codes (all subcommands)

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Validation or not-found error — no filesystem mutation occurred |
| 1 | Unexpected error (I/O failure, etc.) |
