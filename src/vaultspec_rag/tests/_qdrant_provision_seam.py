"""A recorder in front of the Qdrant provisioner, and the states a host is found in.

Several suites need to know whether a command reached the provisioner at all:
every command a client installation must never provision from, and every
start that must not fetch a server - one switched off, one using the on-disk
store, one whose operator named a binary. For those the provisioner is
replaced by a recorder that notes the call and reports a failure, so a
regressed command shows up as a recorded call and can never go on to reach a
release source or spawn a daemon.

It is not used to stage a successful install. A whole provisioning call is
driven for real against a stand-in release that a loopback source serves; see
``_stand_in_release``.

The same suites stage the states a command can find a host in - a managed
install whose executable is not the pinned release, a binary an operator
names - and those are written here too, once, so every suite stages the same
thing.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

from .._sync_vocabulary import ProvisionAction
from ..config._types import EnvVar
from ..qdrant_runtime._constants import MANIFEST_FILENAME

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    import pytest

#: What the recorder reports in place of an install.
RECORDED_FAILURE = "SHA256 mismatch for the release archive"


def operator_pair(binary: Path) -> dict[str, str]:
    """The two settings that name *binary* as the operator's own, as it stands.

    The digest is taken from the file now, so a test that rewrites the file
    afterwards has staged a binary that is no longer the one declared.
    """
    return {
        EnvVar.QDRANT_BINARY.value: str(binary),
        EnvVar.QDRANT_BINARY_SHA256.value: hashlib.sha256(
            binary.read_bytes()
        ).hexdigest(),
    }


def write_unpinned_install(version_dir: Path, executable: bytes) -> Path:
    """Write a managed install whose executable is not the pinned release.

    The executable is fixture bytes, which hash to no committed digest, with
    a manifest beside it that claims a download. That is the state of a
    tampered or corrupted install: what the manifest says changes nothing,
    because an install is judged by its executable's bytes alone.

    Returns:
        The executable's path.
    """
    from ..qdrant_runtime._resolve import binary_filename

    version_dir.mkdir(parents=True, exist_ok=True)
    target = version_dir / binary_filename()
    target.write_bytes(executable)
    manifest = {"version": version_dir.name, "source": "download"}
    (version_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    return target


def record_qdrant_provisioning(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the provisioner with a recorder that reports a failure.

    The recorder binds to ``provision`` on the module that DEFINES it, and it
    works only because every consumer imports that name INSIDE the function
    that calls it and so resolves it once per call. Moving such an import to
    module scope would leave this interception inert while the real
    provisioner ran; a call-time test at each consumer is what catches that.
    The patch target must stay the defining module and match the consumers'
    import: patching a re-exporting package while a consumer imports from the
    definition (or the reverse) silently intercepts nothing.

    Returns:
        A list appended to on each call, so a test can assert the provisioner
        was reached - or, for a command that must not provision, that it never
        was.
    """
    from ..qdrant_runtime import _provision as _provision_module
    from ..qdrant_runtime._constants import ProvisionReport
    from ..qdrant_runtime._download import no_progress

    calls: list[str] = []

    def _provision(
        *,
        upgrade: bool = False,
        dry_run: bool = False,
        archive: Path | None = None,
        # Defaulted exactly as the real signature defaults it. A recorder
        # that made the callback mandatory would turn "the caller stopped
        # passing it" into a TypeError, which reports the wrong defect and
        # passes through any assertion the test actually makes.
        on_progress: Callable[[str], None] = no_progress,
    ) -> ProvisionReport:
        del upgrade, dry_run, archive
        calls.append("provision")
        on_progress("Downloading the Qdrant server (release archive)...")
        return ProvisionReport(action=ProvisionAction.FAILED, message=RECORDED_FAILURE)

    monkeypatch.setattr(_provision_module, "provision", _provision)
    return calls
