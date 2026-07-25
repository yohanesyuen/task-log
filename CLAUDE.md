# tasklog

Installable CLI tool: append-only, per-entry dated task log for any project
that keeps a checklist of work. Extracted from a private project's internal
spec once it proved generically useful.

## Core principle

The core is layout-agnostic: a scope is just a name, a task is just an
identifier, and `migrate` is told which file to read. Every assumption about
a *particular* project layout lives behind an opt-in extension. When adding a
feature, the question is always "does this belong in the core, or is it a
convention?" — if it names a directory or an ID format, it's a convention.

## Layout

- `pyproject.toml` — hatchling build, `src/` layout, `tasklog` console script
  (`tasklog.cli:main`), and the `tasklog.extensions` entry point group that
  registers bundled extensions. Dev loop is a project-local `.venv` with an
  editable install (`uv pip install --python .venv/bin/python -e ".[dev]"`).
- `src/tasklog/cli.py` — click command group. Thin: argument parsing and
  output formatting only, no business logic.
- `src/tasklog/paths.py` — host-repo root resolution (`--repo-root` →
  `$TASKLOG_REPO_ROOT` → nearest `.git` ancestor of cwd) and the layout
  derived from it. Raises `RepoRootNotFound` rather than falling back to cwd.
- `src/tasklog/extensions.py` — the extension protocol, entry-point discovery,
  and the active-extension state. Hooks: `validate_scope`, `checklist_path`,
  `schema_overlay` — all optional.
- `src/tasklog/contrib/speckit.py` — spec-kit conventions as an extension:
  `specs/<scope>/` must exist, scopes are `NNN-slug`, task IDs are `TNNN`,
  `migrate` infers `specs/<scope>/tasks.md`.
- `src/tasklog/schema.py` — frontmatter validation. Host repo's
  `docs/task-log.schema.json` wins over the packaged default; an active
  extension's `schema_overlay()` is merged on top of whichever is used.
- `src/tasklog/entries.py` — file I/O plus add/query/render.
- `src/tasklog/migrate.py` — dated-note extraction from a noisy checklist line.
- `src/tasklog/data/schema.json` — the packaged frontmatter schema
  (Draft 2020-12), shipped as package data.
- `docs/cli-contract.md` — subcommand/flag/exit-code contract.
- `docs/task-log/` — where entries land when this repo dogfoods itself
  (currently unused — it has no `.git` of its own yet, so root resolution
  walks up to the parent repo).
- `tests/test_tasklog.py` — imports the library layer (not the CLI) and runs
  against a synthetic tempdir via `$TASKLOG_REPO_ROOT`, so root resolution is
  exercised for real rather than stubbed.

## Conventions

- No comments explaining what code does — only non-obvious WHY comments.
- Entries are never edited or deleted after being written — a correction is
  a new entry with `event: correction` naming the file it supersedes via
  `supersedes`.
- Two separate guards keep user input out of path joins, and both are
  pinned by `../../evil` tests: the schema's `scope`/`task` patterns cover
  the write path (frontmatter is validated before `entry_path` is built),
  and `validate_scope_name()` covers the read paths, which never touch the
  schema at all. Loosening either without an equivalent replacement
  reintroduces traversal.
- `_ENTRY_FILENAME_RE`'s task group is greedy on purpose: an ID may itself
  end in digits (`sprint-01`), and only greedy matching backtracks to leave
  the trailing two digits as the sequence number.
- `migrate`'s task-line pattern ends in `(?=\s|$)`, not `\b`: with hyphenated
  IDs, `\b` matches between `auth` and the `-` in `auth-refactor`, so
  `--task auth` would rewrite the wrong line.
- The entry filename scheme `<date>-<task>-<seq>.md` is load-bearing:
  `query_entries` sorts by filename for chronological order, `render_view`
  slices the date back out of it, `next_seq` parses it. Changing it orphans
  every entry already written.
- `migrate` rewrites the checklist in place — treat any change to it as
  review-gated, not something to run unattended against a real file.
