"""Tests for the isolated-status-dir qdrant binary mirror (plan W04.P09).

No mocks, no GPU: the mirror copies the host's real provisioned binary into the
isolated test status dir so service-lifecycle integration tests exercise the
live daemon attach/lock path instead of fast-failing on the binary guard. The
pinned-digest verification is preserved - the test asserts the mirrored binary
still hashes to the manifest's committed digest.

When the host has no provisioned binary the mirror is a no-op and the suite
falls back to local-only, so this module verifies the present-binary contract
and otherwise records the absence rather than fabricating an install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...qdrant_runtime._provision import file_sha256
from ...qdrant_runtime._resolve import qdrant_bin_dir, resolve_binary
from ._helpers import _resolve_host_provisioned_qdrant, _service_env

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]


def test_service_env_mirrors_provisioned_binary_with_verification(
    tmp_path: Path,
) -> None:
    if _resolve_host_provisioned_qdrant() is None:
        pytest.fail(
            "No provisioned qdrant binary on the host to mirror; run "
            "'vaultspec-rag server qdrant install' so server-mode lifecycle "
            "tests can exercise the live daemon path."
        )

    with _service_env(tmp_path):
        resolved = resolve_binary()
        # The daemon resolves a binary from inside the isolated status dir, not
        # the host's real managed dir.
        assert resolved is not None
        assert resolved.source == "provisioned"
        assert str(resolved.path).startswith(str(tmp_path))
        assert str(qdrant_bin_dir()).startswith(str(tmp_path))

        # The pinned-digest contract is intact: the mirrored binary still hashes
        # to the manifest's committed digest, so the supervisor's pre-execution
        # re-hash would pass against the real pin (verification not weakened).
        assert resolved.sha256
        assert file_sha256(resolved.path).lower() == resolved.sha256.lower()
