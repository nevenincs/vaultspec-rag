"""Every witness still identifies a server created from an open descriptor.

On Linux the managed server is created from the descriptor of the file that
was just verified, not from its path. The kernel then gives the process the
descriptor's number as its short name, so the server is listed as, say, ``3``
and not as ``qdrant``. Anything that recognised the child by that short name
would stop recognising it: a running managed server would be refused instead
of attached to, and a dead owner's child would be refused instead of reaped,
leaving the port held for good.

These tests run the real pinned binary through the real supervised start and
then ask each witness, and each decision built on them, about that process.
Nothing here can be stood in for: the property under test is what the kernel
reports about a real process image.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ..._process_probe import (
    pid_alive,
    pid_image_matches,
    pid_image_path,
    pid_listens_on_loopback_port,
)
from ...qdrant_runtime._constants import QDRANT_SERVER_VERSION, BinarySource
from ...qdrant_runtime._resolve import (
    classify_qdrant_state,
    decide_qdrant_action,
    probe_qdrant_endpoint,
    read_qdrant_identity,
    resolve_binary,
    verify_attachable,
)
from ...qdrant_runtime._supervise import (
    set_active_supervisor,
    start_supervised_from_config,
)
from ._helpers import _service_env, _wait_for_exit
from ._service_lifecycle_helpers import (
    _cleanup_forced_stop_harness,
    _spawn_posix_qdrant_owner,
)

if TYPE_CHECKING:
    from ...qdrant_runtime._resolve import QdrantIdentity

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not sys.platform.startswith("linux"),
        reason="only Linux creates the server from an open descriptor",
    ),
]


def _short_name(pid: int) -> str:
    return Path(f"/proc/{pid}/comm").read_text(encoding="utf-8").strip()


def _managed_identity() -> QdrantIdentity:
    identity = read_qdrant_identity()
    assert identity is not None
    return identity


def test_a_running_child_is_recognised_and_attached_to(
    tmp_path: Path,
    required_host_provisioned_qdrant_source: tuple[Path, Path],
) -> None:
    """The premise, each witness, and the attach decision built on them.

    The first assertion is the premise and not a requirement: if the short
    name ever reads ``qdrant`` again this test no longer exercises what it is
    for, and should say so instead of passing quietly.
    """
    with _service_env(tmp_path, qdrant_source=required_host_provisioned_qdrant_source):
        owner = start_supervised_from_config()
        try:
            pid = owner.pid
            assert pid is not None
            binary = resolve_binary()
            assert binary is not None

            assert _short_name(pid).isdigit(), "premise: the short name is a number"
            assert "qdrant" not in _short_name(pid)

            assert pid_image_path(pid) == str(binary.path)
            assert pid_image_matches(pid, "qdrant")
            assert pid_listens_on_loopback_port(pid, owner.http_port)

            identity = _managed_identity()
            assert identity.qdrant_pid == pid
            attachable, reason = verify_attachable(
                probe_qdrant_endpoint(owner.http_port),
                identity,
                expected_port=owner.http_port,
                expected_version=QDRANT_SERVER_VERSION,
                expected_storage=str(owner.storage_dir),
            )
            assert attachable, reason

            set_active_supervisor(None)
            attached = start_supervised_from_config()
            assert attached.pid is None
            assert attached.binary_source is BinarySource.ATTACHED
            assert attached.is_alive()
            # Attached, not replaced: the first child is still the server.
            assert pid_alive(pid)
        finally:
            owner.stop()
            set_active_supervisor(None)


def test_a_dead_owners_child_is_reaped_and_replaced(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    required_host_provisioned_qdrant_source: tuple[Path, Path],
) -> None:
    """An orphan holding the port is recognised as ours, reaped, and replaced.

    The reap refuses to signal a pid whose image it cannot recognise. If that
    recognition read the short name, this start would end in that refusal with
    the orphan still listening.
    """
    with _service_env(tmp_path, qdrant_source=required_host_provisioned_qdrant_source):
        owner, orphan_pid, port = _spawn_posix_qdrant_owner()
        request.addfinalizer(lambda: _cleanup_forced_stop_harness(owner, orphan_pid))
        assert _short_name(orphan_pid).isdigit()

        owner.kill()
        owner.wait(timeout=15.0)
        assert pid_alive(orphan_pid)

        probe = probe_qdrant_endpoint(port)
        identity = _managed_identity()
        assert classify_qdrant_state(probe, identity) == "managed_orphan"
        action, _reason = decide_qdrant_action(
            probe,
            identity,
            expected_port=port,
            expected_version=QDRANT_SERVER_VERSION,
            expected_storage=str(Path(os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"])),
        )
        assert action == "reap_then_spawn"

        replacement = start_supervised_from_config()
        try:
            assert _wait_for_exit(orphan_pid, timeout=15.0)
            assert replacement.pid is not None
            assert replacement.pid != orphan_pid
            assert replacement.is_alive()
            assert pid_image_matches(replacement.pid, "qdrant")
        finally:
            replacement.stop()
            set_active_supervisor(None)
