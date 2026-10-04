"""A fresh local-store process releases its SQLite connections cleanly."""

from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def test_local_store_collection_creation_has_no_unclosed_database(
    tmp_path: Path,
) -> None:
    """Observe the first collection's safety probe in a fresh interpreter."""
    completed = subprocess.run(
        [
            sys.executable,
            "-W",
            "error",
            "-c",
            "import gc, os, sys\n"
            "from pathlib import Path\n"
            "from vaultspec_rag.tests._config_fixtures import reset_config\n"
            "from vaultspec_rag.config._types import EnvVar\n"
            "from vaultspec_rag.store_runtime import VaultStore\n"
            "os.environ[EnvVar.QDRANT_SERVER.value] = 'false'\n"
            "os.environ.pop(EnvVar.QDRANT_URL.value, None)\n"
            "reset_config()\n"
            "with VaultStore(Path(sys.argv[1])) as store:\n"
            "    store.ensure_table()\n"
            "    store.ensure_code_table()\n"
            "    store.ensure_document_table()\n"
            "gc.collect()\n"
            "print('collections closed')\n",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "collections closed"
    # The SDK's first-use in-memory safety probe used to survive store.close().
    # Its unraisable ResourceWarning must be visible even after process exit.
    assert completed.stderr == ""
