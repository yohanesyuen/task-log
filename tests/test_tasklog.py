"""
Tests for the tasklog package's library layer (the code behind the CLI).

Runs against a synthetic repo layout under a tempdir, pointed at via
$TASKLOG_REPO_ROOT rather than by stubbing paths.repo_root() — root
resolution is itself part of what's under test, so the tests go through the
real resolution path. Nothing here touches this repo's own docs/task-log/ or
specs/ directories.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tasklog import cli, entries, extensions, migrate, paths
from tasklog.schema import ValidationError, load_schema, validate_entry


class TaskLogTestCase(unittest.TestCase):
    def setUp(self):
        # Resolved up front: repo_root() resolves too, and on macOS an
        # unresolved /var/... tempdir wouldn't compare equal to /private/var/...
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        (self.tmp / "specs" / "003-fake-spec").mkdir(parents=True)
        (self.tmp / "docs").mkdir()
        paths.set_repo_root(None)
        extensions.set_active(None)
        self.patcher = mock.patch.dict(
            os.environ, {paths.REPO_ROOT_ENV_VAR: str(self.tmp)}
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        paths.set_repo_root(None)
        extensions.set_active(None)
        shutil.rmtree(self.tmp, ignore_errors=True)


class ValidateEntryTests(TaskLogTestCase):
    """T004"""

    def test_accepts_minimal_valid_entry(self):
        validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "note"})

    def test_accepts_full_entry_with_all_optional_fields(self):
        validate_entry({
            "scope": "003-fake-spec",
            "task": "T001",
            "event": "implemented",
            "status": "done",
            "tags": ["push-token"],
            "related": ["T002"],
            "refs": ["src/tasklog/cli.py", "PR#42"],
        })

    def test_rejects_unknown_event_value(self):
        with self.assertRaises(ValidationError):
            validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "bogus"})

    def test_rejects_correction_missing_supersedes(self):
        with self.assertRaises(ValidationError):
            validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "correction"})

    def test_accepts_correction_with_supersedes(self):
        validate_entry({
            "scope": "003-fake-spec", "task": "T001", "event": "correction",
            "supersedes": "2026-07-20-T001-01.md",
        })

    def test_rejects_additional_properties(self):
        with self.assertRaises(ValidationError):
            validate_entry({
                "scope": "003-fake-spec", "task": "T001", "event": "note",
                "not_a_real_field": "x",
            })

    def test_accepts_bare_same_spec_related_task_id(self):
        validate_entry({
            "scope": "003-fake-spec", "task": "T001", "event": "gap",
            "related": ["T002"],
        })

    def test_accepts_spec_prefixed_cross_spec_related_task_id(self):
        validate_entry({
            "scope": "003-fake-spec", "task": "T001", "event": "gap",
            "related": ["005-other-spec/T036"],
        })

    def test_accepts_free_form_task_id_without_an_extension(self):
        validate_entry({"scope": "backend", "task": "auth-refactor", "event": "note"})

    def test_rejects_malformed_related_reference(self):
        # At most one scope/task separator, and no traversal segments.
        for bad in ("a/b/c", "../evil", "/absolute"):
            with self.subTest(related=bad):
                with self.assertRaises(ValidationError):
                    validate_entry({
                        "scope": "003-fake-spec", "task": "T001", "event": "gap",
                        "related": [bad],
                    })


class NextSeqTests(TaskLogTestCase):
    """T005"""

    def test_no_existing_entries_returns_01(self):
        self.assertEqual(entries.next_seq("003-fake-spec", "T001", "2026-07-21"), "01")

    def test_existing_entry_same_triple_returns_02(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="first", date="2026-07-21")
        self.assertEqual(entries.next_seq("003-fake-spec", "T001", "2026-07-21"), "02")

    def test_existing_entry_different_date_does_not_interfere(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="first", date="2026-07-20")
        self.assertEqual(entries.next_seq("003-fake-spec", "T001", "2026-07-21"), "01")

    def test_existing_entry_different_task_does_not_interfere(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="first", date="2026-07-21")
        self.assertEqual(entries.next_seq("003-fake-spec", "T002", "2026-07-21"), "01")


class AddEntryTests(TaskLogTestCase):
    """T007, T008"""

    def test_add_creates_file_with_valid_frontmatter(self):
        result = entries.add_entry(
            scope="003-fake-spec", task="T001", event="implemented",
            tags=["smoke-test"], summary="did the thing", date="2026-07-21",
        )
        self.assertTrue(result.path.is_file())
        parsed = entries.parse_entry_file(result.path)
        self.assertEqual(parsed["frontmatter"]["scope"], "003-fake-spec")
        self.assertEqual(parsed["frontmatter"]["task"], "T001")
        self.assertEqual(parsed["frontmatter"]["event"], "implemented")
        self.assertEqual(parsed["frontmatter"]["tags"], ["smoke-test"])
        self.assertIn("did the thing", parsed["body"])

    def test_add_does_not_touch_any_tasks_md(self):
        tasks_md = self.tmp / "specs" / "003-fake-spec" / "tasks.md"
        tasks_md.write_text("- [ ] T001 Do the thing\n")
        before = tasks_md.read_text(encoding="utf-8")
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="x", date="2026-07-21")
        self.assertEqual(tasks_md.read_text(encoding="utf-8"), before)

    def test_add_rejects_invalid_event_before_any_write(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(scope="003-fake-spec", task="T001", event="not-a-real-event",
                               summary="x", date="2026-07-21")
        spec_dir = paths.task_log_root() / "003-fake-spec"
        self.assertFalse(spec_dir.exists())

    def test_add_accepts_any_scope_name_without_an_extension(self):
        result = entries.add_entry(scope="backend", task="auth-refactor", event="note",
                                    summary="x", date="2026-07-21")
        self.assertTrue(result.path.is_file())

    def test_add_reports_first_use_of_a_scope(self):
        first = entries.add_entry(scope="backend", task="T001", event="note",
                                   summary="x", date="2026-07-21")
        self.assertTrue(first.created_scope)
        second = entries.add_entry(scope="backend", task="T001", event="note",
                                    summary="y", date="2026-07-21")
        self.assertFalse(second.created_scope)

    def test_add_rejects_path_traversal_in_task_id(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(scope="003-fake-spec", task="../../evil", event="note",
                               summary="x", date="2026-07-21")

    def test_add_rejects_path_traversal_in_scope(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(scope="../../evil", task="T001", event="note",
                               summary="x", date="2026-07-21")

    def test_add_never_overwrites_existing_file(self):
        r1 = entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                                summary="first", date="2026-07-21")
        # Force a collision by writing directly to the seq the next add would pick.
        with self.assertRaises(FileExistsError):
            entries.write_entry_atomic(r1.path, {"scope": "x", "task": "x", "event": "note"}, "dup")

    def test_add_correction_accepts_existing_supersedes_target(self):
        r1 = entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                                summary="first", date="2026-07-21")
        r2 = entries.add_entry(
            scope="003-fake-spec", task="T001", event="correction",
            supersedes=r1.path.name, summary="actually, correction",
            date="2026-07-21",
        )
        self.assertTrue(r2.path.is_file())

    def test_add_correction_rejects_nonexistent_supersedes_target(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(
                scope="003-fake-spec", task="T001", event="correction",
                supersedes="2026-01-01-T999-01.md", summary="bogus correction",
                date="2026-07-21",
            )
        # No file should have been created for the rejected write.
        self.assertEqual(entries.query_entries("003-fake-spec", "T001"), [])


class QueryEntriesTests(TaskLogTestCase):
    """T012"""

    def test_query_rejects_path_traversal_in_scope(self):
        # The schema only validates frontmatter, so read paths need their own
        # guard — without it this globs outside the log root.
        for bad in ("../..", "a/b", ""):
            with self.subTest(scope=bad):
                with self.assertRaises(ValidationError):
                    entries.query_entries(bad)

    def test_query_returns_entries_in_chronological_order(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="gap",
                           summary="first", date="2026-07-19")
        entries.add_entry(scope="003-fake-spec", task="T001", event="implemented",
                           summary="second", date="2026-07-21")
        entries.add_entry(scope="003-fake-spec", task="T001", event="verified",
                           summary="third", date="2026-07-20")
        found = entries.query_entries("003-fake-spec", "T001")
        events = [e["frontmatter"]["event"] for e in found]
        self.assertEqual(events, ["gap", "verified", "implemented"])

    def test_query_without_task_returns_whole_spec(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="a", date="2026-07-21")
        entries.add_entry(scope="003-fake-spec", task="T002", event="note",
                           summary="b", date="2026-07-21")
        found = entries.query_entries("003-fake-spec")
        self.assertEqual(len(found), 2)

    def test_query_on_spec_with_no_entries_returns_empty(self):
        self.assertEqual(entries.query_entries("003-fake-spec"), [])


class RenderViewTests(TaskLogTestCase):
    """T013"""

    def test_render_is_reproducible_across_runs(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="a", date="2026-07-21")
        out_path1, content1 = entries.render_view("003-fake-spec")
        out_path2, content2 = entries.render_view("003-fake-spec")
        self.assertEqual(content1, content2)
        self.assertEqual(out_path1, out_path2)

    def test_render_overwrites_manual_edit(self):
        entries.add_entry(scope="003-fake-spec", task="T001", event="note",
                           summary="a", date="2026-07-21")
        out_path, _ = entries.render_view("003-fake-spec")
        out_path.write_text("MANUAL EDIT THAT SHOULD DISAPPEAR")
        _, regenerated = entries.render_view("003-fake-spec")
        self.assertNotIn("MANUAL EDIT THAT SHOULD DISAPPEAR", regenerated)


class MigrateTests(TaskLogTestCase):
    """T017, T018"""

    def _write_tasks_md(self, text: str) -> Path:
        tasks_md = self.tmp / "specs" / "003-fake-spec" / "tasks.md"
        tasks_md.write_text(text, encoding="utf-8")
        self.checklist = tasks_md
        return tasks_md

    def test_migrate_extracts_two_clean_dated_notes(self):
        tasks_md = self._write_tasks_md(
            "- [ ] T001 Do the setup\n"
            "- [x] T002 [P] Do the thing. **implemented 2026-07-19**: first note text. "
            "**verified 2026-07-20**: second note text.\n"
            "- [ ] T003 Do the other thing\n"
        )

        result = migrate.migrate_task("003-fake-spec", "T002", self.checklist)

        self.assertEqual(len(result.added), 2)
        self.assertEqual(result.unmigrated, [])
        found = entries.query_entries("003-fake-spec", "T002")
        self.assertEqual(
            sorted((e["frontmatter"]["event"], e["path"].name[:10]) for e in found),
            [("implemented", "2026-07-19"), ("verified", "2026-07-20")],
        )

        lines = tasks_md.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "- [ ] T001 Do the setup")
        self.assertEqual(lines[1], "- [x] T002 [P] Do the thing.")
        self.assertEqual(lines[2], "- [ ] T003 Do the other thing")

    def test_migrate_leaves_ambiguous_note_in_place_and_reports_it(self):
        tasks_md = self._write_tasks_md(
            "- [ ] T004 Do the thing. **implemented 2026-07-19**: clean note text. "
            "**mentioned 2026-07-20**: ambiguous note, unrecognized event word.\n"
        )

        result = migrate.migrate_task("003-fake-spec", "T004", self.checklist)

        self.assertEqual(len(result.added), 1)
        found = entries.query_entries("003-fake-spec", "T004")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["frontmatter"]["event"], "implemented")

        self.assertEqual(len(result.unmigrated), 1)
        self.assertIn("mentioned 2026-07-20", result.unmigrated[0])

        rewritten = tasks_md.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(rewritten.startswith("- [ ] T004 Do the thing."))
        self.assertIn("**mentioned 2026-07-20**", rewritten)

    def test_migrate_strips_dangling_dash_connector(self):
        # Real tasks.md lines commonly join the base description to the
        # first dated note with an em-dash: "... in foo.tsx — **implemented ...**:"
        tasks_md = self._write_tasks_md(
            "- [x] T005 [P] Do the thing in foo.tsx — **implemented 2026-07-19**: note text.\n"
        )

        migrate.migrate_task("003-fake-spec", "T005", self.checklist)

        rewritten = tasks_md.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(rewritten, "- [x] T005 [P] Do the thing in foo.tsx")

    def test_migrate_rejects_unknown_task(self):
        self._write_tasks_md("- [ ] T001 Do the setup\n")
        with self.assertRaises(ValidationError):
            migrate.migrate_task("003-fake-spec", "T999", self.checklist)


class SpeckitExtensionTests(TaskLogTestCase):
    def setUp(self):
        super().setUp()
        extensions.set_active("speckit")

    def test_rejects_scope_without_a_matching_spec_directory(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(scope="999-nonexistent", task="T001", event="note",
                               summary="x", date="2026-07-21")

    def test_rejects_non_speckit_scope_name(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(scope="backend", task="T001", event="note",
                               summary="x", date="2026-07-21")

    def test_overlay_tightens_task_ids_back_to_speckit_form(self):
        with self.assertRaises(ValidationError):
            entries.add_entry(scope="003-fake-spec", task="auth-refactor", event="note",
                               summary="x", date="2026-07-21")

    def test_accepts_speckit_shaped_scope_and_task(self):
        result = entries.add_entry(scope="003-fake-spec", task="T042", event="note",
                                    summary="x", date="2026-07-21")
        self.assertTrue(result.path.is_file())

    def test_migrate_infers_the_checklist_path(self):
        tasks_md = self.tmp / "specs" / "003-fake-spec" / "tasks.md"
        tasks_md.write_text("- [x] T001 Do it. **implemented 2026-07-19**: done.\n", encoding="utf-8")
        result = migrate.migrate_task("003-fake-spec", "T001")
        self.assertEqual(result.checklist_path, tasks_md)
        self.assertEqual(len(result.added), 1)

    def test_unknown_extension_name_is_an_error_not_a_silent_fallback(self):
        with self.assertRaises(extensions.UnknownExtension):
            extensions.set_active("no-such-extension")


class MigrateWithoutExtensionTests(TaskLogTestCase):
    def _checklist(self, text: str) -> Path:
        path = self.tmp / "TODO.md"
        path.write_text(text, encoding="utf-8")
        return path

    def test_requires_an_explicit_file(self):
        with self.assertRaises(ValidationError):
            migrate.migrate_task("default", "T001")

    def test_migrates_a_plain_todo_file(self):
        checklist = self._checklist(
            "- [x] auth-refactor Swap the token store. **implemented 2026-07-19**: done.\n"
        )
        result = migrate.migrate_task("backend", "auth-refactor", checklist)
        self.assertEqual(len(result.added), 1)
        self.assertEqual(checklist.read_text(encoding="utf-8").splitlines()[0],
                         "- [x] auth-refactor Swap the token store.")

    def test_hyphenated_task_id_does_not_match_a_longer_sibling(self):
        # \b would find a boundary between "auth" and the "-" of
        # "auth-refactor" and rewrite the wrong line.
        checklist = self._checklist(
            "- [ ] auth-refactor Do the big one. **implemented 2026-07-19**: nope.\n"
            "- [x] auth Do the small one. **implemented 2026-07-20**: yes.\n"
        )
        result = migrate.migrate_task("backend", "auth", checklist)
        self.assertEqual(len(result.added), 1)
        lines = checklist.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0],
                         "- [ ] auth-refactor Do the big one. **implemented 2026-07-19**: nope.")
        self.assertEqual(lines[1], "- [x] auth Do the small one.")


class FilenameParsingTests(TaskLogTestCase):
    def test_task_id_ending_in_digits_round_trips(self):
        first = entries.add_entry(scope="backend", task="sprint-01", event="note",
                                   summary="a", date="2026-07-26")
        self.assertEqual(first.path.name, "2026-07-26-sprint-01-01.md")
        self.assertEqual(entries.next_seq("backend", "sprint-01", "2026-07-26"), "02")


class RepoRootResolutionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        paths.set_repo_root(None)

    def tearDown(self):
        paths.set_repo_root(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_explicit_override_wins_over_env(self):
        explicit = self.tmp / "explicit"
        explicit.mkdir()
        paths.set_repo_root(explicit)
        with mock.patch.dict(os.environ, {paths.REPO_ROOT_ENV_VAR: str(self.tmp)}):
            self.assertEqual(paths.repo_root(), explicit)

    def test_env_var_wins_over_cwd_walk_up(self):
        (self.tmp / ".git").mkdir()
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        with mock.patch.dict(os.environ, {paths.REPO_ROOT_ENV_VAR: str(elsewhere)}):
            self.assertEqual(paths.repo_root(), elsewhere)

    def test_walks_up_from_cwd_to_nearest_git_ancestor(self):
        (self.tmp / ".git").mkdir()
        nested = self.tmp / "a" / "b"
        nested.mkdir(parents=True)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            Path, "cwd", return_value=nested
        ):
            self.assertEqual(paths.repo_root(), self.tmp)

    def test_raises_rather_than_falling_back_to_cwd(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            Path, "cwd", return_value=self.tmp
        ):
            with self.assertRaises(paths.RepoRootNotFound):
                paths.repo_root()


class CliRepoRootLeakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        paths.set_repo_root(None)

    def tearDown(self):
        paths.set_repo_root(None)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_repo_root_flag_does_not_leak_into_the_next_invocation(self):
        (self.tmp / "specs" / "003-fake-spec").mkdir(parents=True)
        exit_code = cli.main(["--repo-root", str(self.tmp), "query", "--scope", "003-fake-spec"])
        self.assertEqual(exit_code, 0)
        self.assertIsNone(paths.repo_root_override())


class SchemaSourceTests(TaskLogTestCase):
    def test_uses_packaged_schema_when_host_has_no_override(self):
        self.assertFalse(paths.schema_override_path().exists())
        self.assertIn("event", load_schema()["properties"])

    def test_host_override_takes_precedence(self):
        paths.schema_override_path().write_text(
            '{"type": "object", "properties": {"marker": {"type": "string"}}}',
            encoding="utf-8",
        )
        self.assertIn("marker", load_schema()["properties"])


if __name__ == "__main__":
    unittest.main()
