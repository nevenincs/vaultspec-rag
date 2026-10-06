"""A live process's image is readable on every platform, or says it is not.

The image check is what stands between a recorded pid and a hard kill, and
between a recorded server and an attach. Linux reads the image out of
``/proc``. macOS and the BSDs have no such entry, so the same read fails there
for every process, and "unreadable" for every process turns into "not ours"
for every process: a healthy managed server is refused and an orphan is never
reaped. Those platforms are asked through psutil instead.

The psutil route is exercised here directly, against a real child of the test,
because it answers on every platform while the branch that selects it is taken
only where ``/proc`` has no image link. The public checks are exercised as
well, so a platform whose selected route cannot name a live process fails
here whichever route that is.

MUTATION PROOF, each run in one uninterrupted sequence and restored:

- ``_psutil_image_path`` made to return ``None`` for every pid - what a
  platform without the ``/proc`` link answered before it was asked through
  psutil - fails ``test_the_psutil_route_names_a_live_process_image`` on
  ``assert image is not None`` and nothing else in this file.
- ``_psutil_image_path`` made to read the process name in place of its
  executable path fails the same test on its path comparison.
- ``_psutil_image_path`` made to catch ``psutil.AccessDenied`` alone fails
  ``test_the_psutil_route_reads_a_departed_process_as_unreadable`` with
  ``psutil.NoSuchProcess`` raised out of the call under test.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from .._process_probe import (
    _psutil_image_name,
    _psutil_image_path,
    kill_child_tree,
    pid_image_matches,
    pid_image_path,
)

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]

#: The trailing comment puts a second program's name in the child's argument
#: vector and nowhere in its image.
_SLEEP = "import time; time.sleep(30)  # qdrant"


@contextlib.contextmanager
def _sleeping_child() -> Generator[subprocess.Popen[bytes]]:
    """Run a real interpreter that only sleeps, and end its whole tree after."""
    child = subprocess.Popen(
        [sys.executable, "-c", _SLEEP],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        # The tree: a Windows virtual environment's interpreter is a launcher
        # that starts the real one as its own child.
        kill_child_tree(child, confirm_seconds=10.0)


def _interpreter() -> Path:
    return Path(sys.executable).resolve()


def test_the_psutil_route_names_a_live_process_image() -> None:
    with _sleeping_child() as child:
        image = _psutil_image_path(child.pid)

        assert image is not None, "a live child of this process read as unreadable"
        assert Path(image).resolve() == _interpreter()


def test_the_psutil_route_names_a_live_process_by_its_short_name() -> None:
    with _sleeping_child() as child:
        name = _psutil_image_name(child.pid)

        assert name is not None, "a live child of this process read as unnamed"
        assert "python" in name.lower()


def test_the_psutil_route_reads_a_departed_process_as_unreadable() -> None:
    """A process that is gone is unknown, and asking about it does not raise."""
    with _sleeping_child() as child:
        pass
    assert child.returncode is not None, "premise: the child has been ended"

    assert _psutil_image_path(child.pid) is None
    assert _psutil_image_name(child.pid) is None


def test_a_live_process_image_is_readable_on_this_platform() -> None:
    """The route this platform selects names a live process.

    The case that fails where the image is asked of a filesystem the platform
    does not have: every live pid then reads as unreadable.
    """
    with _sleeping_child() as child:
        image = pid_image_path(child.pid)

        assert image is not None, "a live child of this process read as unreadable"
        assert Path(image).resolve() == _interpreter()


def test_the_image_check_matches_a_live_process_on_its_image_alone() -> None:
    with _sleeping_child() as child:
        assert pid_image_matches(child.pid, "python")
        # Named in the argument vector, not the image: a process that merely
        # mentions a server is not that server.
        assert not pid_image_matches(child.pid, "qdrant")
