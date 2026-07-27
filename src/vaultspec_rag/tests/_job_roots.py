"""Absolute project roots shared by the job-management test modules.

The job records under test round-trip their project root through path
resolution, so the literal has to be genuinely absolute on whichever platform
runs the suite. A hardcoded drive-letter literal is absolute only on a host
whose current drive matches; on POSIX it is a plain relative component that
resolution rewrites against the runner's cwd. ``os.path.abspath`` over a
separator-rooted join is absolute - and therefore resolution-idempotent - on
both.
"""

from __future__ import annotations

import os

_TEST_PROJECT_ROOT = os.path.abspath(os.path.join(os.sep, "project"))
_TEST_PROJECT_ROOT_OTHER = os.path.abspath(os.path.join(os.sep, "other"))
_TEST_PROJECT_ROOT_DIFFERENT = os.path.abspath(os.path.join(os.sep, "different"))
