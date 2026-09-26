"""The CLI must never import ``python-dotenv`` outside the credential gate.

Any dotenv bootstrap - ``load_dotenv()``, ``find_dotenv()``, or a bare
``import dotenv`` - registers ``"dotenv"`` in :data:`sys.modules` the instant
it runs, regardless of which ``.env`` it would have found or whether one
exists at all. That makes the module registry a sound proxy for "did any
dotenv bootstrap run", and a strictly wider one than probing for a single
sentinel variable: python-dotenv's own ``find_dotenv(usecwd=False)`` walks up
from the *calling module's* installed location, not from the process's
working directory, so a sentinel planted in a subprocess's cwd (as an earlier
version of this test did) is never on that walk and could not have failed
even while the bootstrap it meant to catch was live. Reaching the directory
the walk actually starts from would mean writing a ``.env`` into the
installed ``vaultspec_rag`` package tree itself, which is out of bounds for a
test.

This test runs in a fresh interpreter subprocess - so no prior import in this
test process can taint the result - and imports the CLI package the same way
the ``vaultspec-rag`` entry point does, then asserts ``dotenv`` never entered
:data:`sys.modules`.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit]

_CHECK = "import sys; import vaultspec_rag.cli; print('dotenv' in sys.modules)"


def test_importing_the_cli_never_imports_dotenv() -> None:
    """Importing the CLI package must not import ``dotenv``, installed or not."""
    proc = subprocess.run(
        [sys.executable, "-c", _CHECK],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False", proc.stderr
