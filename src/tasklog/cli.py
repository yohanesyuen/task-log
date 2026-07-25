"""Command-line surface. Argument parsing and output formatting only — every
operation lives in entries/migrate so tests can exercise them without going
through click."""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

import click

from . import entries, extensions, migrate, paths
from .schema import ValidationError


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


@click.group()
@click.option(
    "--extension",
    help=f"Opt-in convention pack (e.g. speckit). Defaults to ${extensions.EXTENSION_ENV_VAR}. "
         "Without one, a scope is just a name and `migrate` needs --file.",
)
@click.option(
    "--repo-root",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help=f"Host repo to log against. Defaults to ${paths.REPO_ROOT_ENV_VAR}, "
         "else the nearest .git ancestor of the working directory.",
)
@click.version_option(package_name="tasklog")
def cli(repo_root: Path | None, extension: str | None) -> None:
    """Append-only, per-entry dated log of task history."""
    paths.set_repo_root(repo_root)
    extensions.set_active(extension or extensions.resolve_from_environment())


@cli.command("add", help="Record one new task log entry.")
@click.option("--scope", default=entries.DEFAULT_SCOPE, show_default=True)
@click.option("--task", required=True)
@click.option("--event", required=True)
@click.option("--status")
@click.option("--tags", help="Comma-separated.")
@click.option("--related", help="Comma-separated.")
@click.option("--refs", help="Comma-separated.")
@click.option("--supersedes", help="Filename of the entry this one corrects/retracts.")
@click.option("--summary")
@click.option("--body")
@click.option("--body-file", type=click.Path(exists=True, dir_okay=False))
@click.option("--date", help="YYYY-MM-DD, defaults to today. Only used to backdate a migrated entry.")
def cmd_add(
    scope: str,
    task: str,
    event: str,
    status: str | None,
    tags: str | None,
    related: str | None,
    refs: str | None,
    supersedes: str | None,
    summary: str | None,
    body: str | None,
    body_file: str | None,
    date: str | None,
) -> None:
    resolved_date = date or datetime.date.today().isoformat()
    if body_file:
        body = Path(body_file).read_text(encoding="utf-8")
    try:
        result = entries.add_entry(
            scope=scope,
            task=task,
            event=event,
            status=status,
            tags=_csv(tags),
            related=_csv(related),
            refs=_csv(refs),
            supersedes=supersedes,
            summary=summary,
            body=body,
            date=resolved_date,
        )
    except ValidationError as e:
        click.echo(f"error: {e}", err=True)
        raise SystemExit(2)
    if result.created_scope:
        click.echo(f"note: created new scope directory {result.path.parent}", err=True)
    click.echo(str(result.path))


@cli.command("query", help="Read back a task's or scope's entries.")
@click.option("--scope", default=entries.DEFAULT_SCOPE, show_default=True)
@click.option("--task")
@click.option("--format", "fmt", type=click.Choice(["json", "md"]), default="md")
def cmd_query(scope: str, task: str | None, fmt: str) -> None:
    found = entries.query_entries(scope, task)
    if fmt == "json":
        click.echo(json.dumps(
            [{"path": str(e["path"]), **e["frontmatter"], "body": e["body"]} for e in found],
            indent=2,
        ))
        return
    if not found:
        click.echo("(no entries)")
    for e in found:
        fm = e["frontmatter"]
        click.echo(f"## {fm.get('task')} — {fm.get('event')} ({e['path'].name})")
        for key in ("status", "tags", "related", "refs", "supersedes"):
            if key in fm:
                click.echo(f"- {key}: {fm[key]}")
        click.echo("")
        click.echo(e["body"])
        click.echo("")


@cli.command("render", help="Regenerate the human-readable summary.")
@click.option("--scope")
def cmd_render(scope: str | None) -> None:
    out_path, content = entries.render_view(scope)
    out_path.write_text(content, encoding="utf-8")
    click.echo(str(out_path))


@cli.command("migrate", help="Extract embedded prose from one checklist line.")
@click.option("--scope", default=entries.DEFAULT_SCOPE, show_default=True)
@click.option("--task", required=True)
@click.option("--file", "checklist", type=click.Path(dir_okay=False, path_type=Path),
              help="Checklist file holding the task's line. Required unless an "
                   "--extension can infer it.")
def cmd_migrate(scope: str, task: str, checklist: Path | None) -> None:
    try:
        result = migrate.migrate_task(scope, task, checklist)
    except ValidationError as e:
        click.echo(f"error: {e}", err=True)
        raise SystemExit(2)
    for path in result.added:
        click.echo(f"added: {path}")
    if result.unmigrated:
        click.echo("unmigrated (left in place, needs human review):", err=True)
        for clause in result.unmigrated:
            click.echo(f"  {clause}", err=True)


def main(argv: list[str] | None = None) -> int:
    # Entries and tasks.md routinely contain non-ASCII prose (em dashes,
    # curly quotes); Windows terminals default stdio to the system codepage
    # (cp1252), which can't represent them and would otherwise crash `print`.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    # main() is importable and may be called more than once in one process;
    # --repo-root sets module-global state, so restore whatever was there
    # rather than leaking one invocation's root into the next.
    prior_root = paths.repo_root_override()
    prior_extension = extensions.active_name()
    try:
        cli.main(args=argv, prog_name="tasklog", standalone_mode=False)
    except click.ClickException as e:
        e.show()
        return e.exit_code
    except (paths.RepoRootNotFound, extensions.UnknownExtension) as e:
        click.echo(f"error: {e}", err=True)
        return 2
    except SystemExit as e:
        return int(e.code or 0)
    finally:
        paths.set_repo_root(prior_root)
        extensions.set_active(prior_extension)
    return 0


if __name__ == "__main__":
    sys.exit(main())
