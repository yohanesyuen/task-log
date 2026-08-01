# tasklog

Append-only, per-entry dated log of task history, for any project that keeps
a checklist of work. It exists because free-text progress notes tend to
accumulate inline until each task line is an unreadable wall of
`**word YYYY-MM-DD**: ...` clauses.

Instead, every note about a task becomes its own small file —
`docs/task-log/<scope>/<date>-<task>-<seq>.md`, YAML frontmatter + prose body
— so concurrent writers for different tasks never contend for the same file,
and a task's full history is `query`-able as structured data instead of
grepped out of a paragraph.

## Why not just keep writing notes inline?

- **One shared file, N concurrent writers.** Every note about every task
  lands in the same line or file, so two people/agents editing different
  tasks still conflict.
- **No structure.** "Who wrote this, when, was it a fix or a retraction of
  an earlier claim?" — all guessable from prose, none of it queryable.
- **Corrections silently overwrite history.** There's no way to say "this
  earlier note was wrong" without editing it in place and losing the
  original.

`tasklog` fixes all three: one file per entry (no shared-file contention),
a small validated schema (`event`, `status`, `tags`, `related`, `refs`,
`supersedes`), and entries are *never* edited or deleted — a correction is a
new entry that names the one it supersedes.

## What it assumes about your project

Almost nothing:

- A **task** is any identifier you already use — `T042`, `ISSUE-123`,
  `auth-refactor`. It only has to be filename-safe.
- A **scope** is an optional namespace grouping tasks — a milestone, a
  subsystem, a spec directory. Omit it and everything lands in `default`.
- A **checklist** is any markdown file with `- [ ] <task> ...` lines, and
  only `migrate` needs one — you point it at the file with `--file`.

Anything more opinionated than that lives in an [extension](#extensions).

## Install

A normal Python package (`>=3.11`) exposing a `tasklog` console script:

```sh
uv tool install git+https://github.com/<owner>/task-log
# or, from a local checkout:
uv tool install .
```

To run it without installing:

```sh
uvx --from git+https://github.com/<owner>/task-log tasklog --help
```

For development, use an editable install in a project-local venv:

```sh
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

## Choosing which repo to log against

`tasklog` writes into a *host* repo — the repo whose task history is being
recorded, which is not the repo it was installed from. That root is resolved
in this order:

1. `--repo-root <path>`
2. `$TASKLOG_REPO_ROOT`
3. the nearest ancestor of the working directory containing a `.git`

If none resolves it exits 2 with the remedy rather than silently writing
into whatever directory you happened to be standing in.

## Usage

```sh
# Record a note. --scope is optional; without it everything lands in `default`.
tasklog add --task ISSUE-123 --event implemented \
  --summary "Wired the retry queue to the dead-letter handler."

tasklog add --scope backend --task auth-refactor --event blocked \
  --summary "Waiting on the session-store migration."

# Read back everything recorded for a task
tasklog query --scope backend --task auth-refactor

# Regenerate the human-readable rollup at docs/task-log.md (or
# docs/task-log-<scope>.md for a single scope)
tasklog render

# One-time: extract dated notes already embedded in a noisy checklist line
# into proper entries, then rewrite that line to bare form. Review the
# diff before trusting it — this rewrites the checklist in place.
tasklog migrate --task auth-refactor --file TODO.md
```

Full CLI contract (flags, exit codes, behavior per subcommand):
[`docs/cli-contract.md`](docs/cli-contract.md).

## Extensions

The core stays layout-agnostic, which means it can't catch a typo'd scope or
guess where your checklist lives. A project that *does* follow a known
convention can opt into it:

```sh
tasklog --extension speckit add --scope 003-my-feature --task T042 \
  --event implemented --summary "..."
```

The bundled `speckit` extension covers
[GitHub spec-kit](https://github.com/github/spec-kit) layouts, and does three
things the core deliberately won't:

| | Without an extension | With `--extension speckit` |
|---|---|---|
| 🏷️ Scope | any name; unknown ones are created | must be `NNN-slug` **and** an existing `specs/<scope>/` |
| 🆔 Task ID | any filename-safe identifier | must be `TNNN` / `TNNNx` |
| 📄 `migrate` | needs `--file <path>` | infers `specs/<scope>/tasks.md` |

Set `$TASKLOG_EXTENSION` to avoid passing the flag every time. An unknown
extension name is an error, never a silent fallback to generic behavior.

Extensions are discovered through the `tasklog.extensions` entry point group,
so a project can ship its own without this package knowing about it. An
extension is any class providing one or more of these — all optional:

```python
class Extension:
    name = "my-convention"

    def validate_scope(self, scope: str) -> None: ...      # raise ValidationError to reject
    def checklist_path(self, scope: str) -> Path: ...      # where `migrate` looks by default
    def schema_overlay(self) -> dict: ...                  # {property: subschema} merged over the base
    def event_verbs(self) -> list[str]: ...                # extra verbs appended to the base `event` enum
```

```toml
[project.entry-points."tasklog.extensions"]
my-convention = "mypkg.tasklog_ext:Extension"
```

### Extending the `event` vocabulary

`event` is deliberately a closed enum (`implemented`, `verified`,
`correction`, `gap`, `deferred`, `blocked`, `retracted`, `note`) so entries
stay queryable across every project. A project that needs its own verb on
top of that set has two **additive** options — both only ever append, they
never require restating (and risking silently dropping) the base list or the
`correction`/`retracted` → `supersedes` invariant that ships with it:

- **Per-repo, no extra tooling** — drop `docs/task-log.events.json`:
  ```json
  { "extra_events": ["completed", "shipped"] }
  ```
- **Reusable across repos** — an installable extension's `event_verbs()`
  hook returns the same shape as a Python list.

Don't hand-roll this by copying `src/tasklog/data/schema.json` into your own
`docs/task-log.schema.json` and editing the `event` enum in place — that
file is a **full replacement**, not a merge, and a naive copy is easy to get
subtly wrong (e.g. dropping the `allOf` block that enforces
`correction`/`retracted` require `--supersedes`). Use
`docs/task-log.schema.json` only when you actually need to *tighten* a
different field's pattern (as `speckit`'s `schema_overlay()` does for
`scope`/`task`); use the additive routes above for verbs.

## Layout in the host repo

```
docs/task-log/<scope>/      # entries land here, one file per note
docs/task-log.md            # generated rollup (never hand-edited)
docs/task-log.schema.json   # optional — fully REPLACES the packaged schema
docs/task-log.events.json   # optional — additively widens the `event` enum
```

The frontmatter schema ships with the package
([`src/tasklog/data/schema.json`](src/tasklog/data/schema.json)). A host repo
wanting stricter conventions on a field *other than* `event` can drop its own
`docs/task-log.schema.json` in place and that one wins outright (it replaces
the packaged schema, it does not merge with it); an active extension's
overlay is then applied on top of whichever schema was used. Independently of
that, `docs/task-log.events.json` and an extension's `event_verbs()` both
append to `event`'s enum wherever it ends up after the step above.

## Testing

```sh
.venv/bin/python -m pytest
```

Tests import the `tasklog` package's library layer (not the CLI) and run
against a synthetic repo under a tempdir, pointed at via
`$TASKLOG_REPO_ROOT` — so root resolution is exercised for real, and nothing
touches this repo's own `docs/task-log/`.

## Status

Extracted from an internal project once it proved generically useful.

**0.3.0** adds the additive `event`-vocabulary extension points
(`docs/task-log.events.json`, an extension's `event_verbs()`) — see
"Extending the `event` vocabulary" above. Backward compatible: a repo with no
override file behaves exactly as before.

**0.2.0 is a breaking change** from 0.1.0: `--spec` became `--scope`, the
`spec:` frontmatter field became `scope:`, and the spec-kit assumptions moved
behind `--extension speckit`. There were no installed users; existing copies
are independent forks.

## License

MIT — see [LICENSE](LICENSE).
