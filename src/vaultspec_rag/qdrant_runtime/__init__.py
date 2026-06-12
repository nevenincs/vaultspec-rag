"""Qdrant server runtime: pinning, provisioning, and supervision.

This package owns everything needed to run the real Rust qdrant
server as a supervised child of the resident service: the committed
version/digest pin (``_constants``), platform asset mapping and
binary resolution (``_resolve``), download-on-first-use provisioning
(``_provision``), and child-process supervision with readiness
polling and the Windows kill-on-close Job Object (``_supervise``).

Stdlib-only by design: the CLI imports this package at startup, so it
must never pull torch, qdrant-client, or any other heavy dependency.
"""

from __future__ import annotations

from ._constants import (
    ALLOWED_DOWNLOAD_HOSTS,
    QDRANT_ASSET_SHA256,
    QDRANT_RELEASE_BASE_URL,
    QDRANT_SERVER_VERSION,
    ProvisionReport,
    QdrantProvisionAction,
    QdrantRuntimeState,
    ResolvedBinary,
)
from ._provision import (
    ChecksumMismatchError,
    clean_provisioned,
    extract_verified_archive,
    file_sha256,
    provision,
    provisioned_versions,
)
from ._resolve import (
    asset_for_platform,
    binary_filename,
    qdrant_bin_dir,
    read_manifest,
    resolve_binary,
)
from ._supervise import (
    QdrantSupervisor,
    active_supervisor,
    runtime_state,
    set_active_supervisor,
)

__all__ = [
    "ALLOWED_DOWNLOAD_HOSTS",
    "QDRANT_ASSET_SHA256",
    "QDRANT_RELEASE_BASE_URL",
    "QDRANT_SERVER_VERSION",
    "ChecksumMismatchError",
    "ProvisionReport",
    "QdrantProvisionAction",
    "QdrantRuntimeState",
    "QdrantSupervisor",
    "ResolvedBinary",
    "active_supervisor",
    "asset_for_platform",
    "binary_filename",
    "clean_provisioned",
    "extract_verified_archive",
    "file_sha256",
    "provision",
    "provisioned_versions",
    "qdrant_bin_dir",
    "read_manifest",
    "resolve_binary",
    "runtime_state",
    "set_active_supervisor",
]
