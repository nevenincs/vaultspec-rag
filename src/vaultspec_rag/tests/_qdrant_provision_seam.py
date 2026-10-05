"""The one substitution of the Qdrant provisioner's network half.

Several suites need to know whether a command reached the provisioner at all -
the start path that provisions unattended, and every command a client
installation must never provision from - and none of them can be driven
against the real one. The reason is recorded once, here, with the single site
that acts on it.

Why the provisioner cannot be driven for real: it refuses any source that is
not https on an allowed host, and verifies the archive against a committed
digest before extracting. A locally served archive therefore fails on the
scheme, then the host, and could never match the digest anyway - the security
design makes a substitute source unusable on purpose. The one real alternative
is rejected on cost rather than on possibility: provisioning into an isolated
managed directory would download the pinned release over the network on every
run, which the integration helpers mirror an already-installed binary
precisely to avoid.

The same suites stage the states a command can find a host in - a managed
install written by hand, a binary an operator names - and those are written
here too, once, so every suite stages the same thing.
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

#: What a manifest says of an install an operator registered. Earlier
#: releases wrote it; nothing accepts it now.
OPERATOR_REGISTERED = "operator"


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


def write_managed_install(
    version_dir: Path, executable: bytes, *, source: str = "download"
) -> Path:
    """Write a managed install by hand: an executable and the manifest beside it.

    A ``download`` install is held to the committed digest of a release
    executable, which fixture bytes never match, so it resolves and then
    fails its check - the state of a tampered install. An
    ``OPERATOR_REGISTERED`` one carries the digest of these same bytes, the
    way the removed registration recorded it, and is refused on its claim.

    Returns:
        The executable's path.
    """
    from ..qdrant_runtime._resolve import binary_filename

    version_dir.mkdir(parents=True, exist_ok=True)
    target = version_dir / binary_filename()
    target.write_bytes(executable)
    manifest = {"version": version_dir.name, "source": source}
    if source == OPERATOR_REGISTERED:
        manifest["binary_sha256"] = hashlib.sha256(executable).hexdigest()
    (version_dir / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    return target


def substitute_qdrant_download(
    monkeypatch: pytest.MonkeyPatch,
    *,
    succeeds: bool,
) -> list[str]:
    """Replace the network half of provisioning, and nothing else.

    The reported lines come from the shipped ``_download_line`` renderer
    rather than from literals, so a change to how bytes are phrased travels
    into the caller's assertions instead of stranding them. On success a real
    binary and a real manifest are written into the isolated managed dir, so
    it is the real ``resolve_binary`` that confirms the install afterwards. On
    failure nothing is written and a ``failed`` report comes back, which is
    also what keeps a regressed caller from going on to spawn a daemon.

    The substitution binds to ``provision`` on the module that DEFINES it, and
    it works only because every consumer imports that name INSIDE the function
    that calls it and so resolves it once per call. Moving such an import to
    module scope would leave this interception inert while the real network
    download ran; a call-time test at each consumer is what catches that. The
    patch target must stay the defining module and match the consumers'
    import: patching a re-exporting package while a consumer imports from the
    definition (or the reverse) silently intercepts nothing.

    Returns:
        A list appended to on each call, so a test can assert the interception
        was reached - or, for a command that must not provision, that it never
        was.
    """
    from ..qdrant_runtime import _provision as _provision_module
    from ..qdrant_runtime._constants import ProvisionReport
    from ..qdrant_runtime._download import _download_line, no_progress
    from ..qdrant_runtime._resolve import qdrant_bin_dir

    calls: list[str] = []

    def _provision(
        *,
        upgrade: bool = False,
        dry_run: bool = False,
        archive: Path | None = None,
        # Defaulted exactly as the real signature defaults it. A substitute
        # that made the callback mandatory would turn "the caller stopped
        # passing it" - a regression this exists to catch - into a TypeError,
        # which reports the wrong defect and passes through any assertion the
        # test actually makes.
        on_progress: Callable[[str], None] = no_progress,
    ) -> ProvisionReport:
        del upgrade, dry_run, archive
        calls.append("provision")
        on_progress("Downloading the Qdrant server (release archive)...")
        on_progress(_download_line(4 << 20, 31 << 20))
        on_progress("Verifying the Qdrant download checksum...")
        if not succeeds:
            return ProvisionReport(
                action=ProvisionAction.FAILED,
                message="SHA256 mismatch for the release archive",
            )
        target = write_managed_install(qdrant_bin_dir(), b"not a real server")
        return ProvisionReport(action=ProvisionAction.CREATED, binary=target)

    monkeypatch.setattr(_provision_module, "provision", _provision)
    return calls
