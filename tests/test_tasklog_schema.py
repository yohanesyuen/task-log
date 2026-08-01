"""
Tests for tasklog's frontmatter schema: base validation, the `event`
vocabulary and how it can be widened, and the speckit extension. Split out
of test_tasklog.py once that file crossed the machine's 500-line convention.
"""

from __future__ import annotations

import json
from importlib import resources
from unittest import mock

from tasklog import entries, extensions, migrate, paths
from tasklog.schema import ValidationError, load_schema, validate_entry

from _base import TaskLogTestCase


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


class EventVerbExtensionTests(TaskLogTestCase):
    """docs/task-log.events.json and an extension's event_verbs() both widen
    the `event` enum additively -- neither should require (or risk) restating
    the base list or dropping the correction/retracted->supersedes
    invariant, the exact footgun a hand-copied docs/task-log.schema.json has."""

    def test_events_override_file_widens_the_enum(self):
        paths.events_override_path().write_text(
            '{"extra_events": ["completed"]}', encoding="utf-8",
        )
        self.assertIn("completed", load_schema()["properties"]["event"]["enum"])
        validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "completed"})

    def test_events_override_preserves_base_verbs_and_supersedes_invariant(self):
        paths.events_override_path().write_text(
            '{"extra_events": ["completed"]}', encoding="utf-8",
        )
        validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "note"})
        with self.assertRaises(ValidationError):
            validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "correction"})

    def test_events_override_does_not_duplicate_an_existing_verb(self):
        paths.events_override_path().write_text(
            '{"extra_events": ["note", "note"]}', encoding="utf-8",
        )
        enum = load_schema()["properties"]["event"]["enum"]
        self.assertEqual(enum.count("note"), 1)

    def test_no_events_override_file_leaves_enum_unchanged(self):
        self.assertFalse(paths.events_override_path().exists())
        base_enum = json.loads(
            resources.files("tasklog").joinpath("data/schema.json").read_text()
        )["properties"]["event"]["enum"]
        self.assertEqual(load_schema()["properties"]["event"]["enum"], base_enum)

    def test_extension_event_verbs_hook_widens_the_enum(self):
        with mock.patch.object(extensions, "_active", _FakeEventVerbExtension()):
            self.assertIn("shipped", load_schema()["properties"]["event"]["enum"])
            validate_entry({"scope": "003-fake-spec", "task": "T001", "event": "shipped"})

    def test_extra_verbs_are_a_noop_against_a_full_override_without_an_event_enum(self):
        paths.schema_override_path().write_text(
            '{"type": "object", "properties": {"marker": {"type": "string"}}}',
            encoding="utf-8",
        )
        paths.events_override_path().write_text(
            '{"extra_events": ["completed"]}', encoding="utf-8",
        )
        load_schema()  # must not raise


class _FakeEventVerbExtension:
    name = "fake-event-verb-extension"

    def event_verbs(self) -> list[str]:
        return ["shipped"]
