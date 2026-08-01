"""Shared test fixture for the tasklog test suite.

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

from tasklog import extensions, paths


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
