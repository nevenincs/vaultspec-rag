"""Corrupt-collection resilience for the shared Qdrant store (real FS, real subprocess).

Exercises the detect-quarantine-retry recovery from the
Store-resilience tests with no mocks: quarantine is a real directory
move, detection runs against a real on-disk collection set, and the bounded
retry drives a real ``QdrantSupervisor`` against a fake binary that always aborts
after naming a collection - so the loop quarantines under its bound and then
fails loudly, exactly as a pathological store should.

The recovery is gated on the store proving which server version wrote it,
because a binary that cannot read the on-disk format aborts naming the
collection it choked on and is otherwise indistinguishable from one corrupt
collection. Trusting that shape quarantines healthy indexes while the daemon
still comes up ready, which is the silent loss these guards exist to prevent.

Every guard here has been observed failing for the reason it names: the trust
gate removed (the skew and unstamped starts quarantine, and the refusal message
degrades to a plain readiness timeout), the health branches dropped (a
quarantined store reports ready), the migration relabelling dropped (a carried
store still reads as a match), an absent record defaulted to the running version
(unverifiable becomes a match), and each remediation stem reworded so the
service's own sentence goes out unclaimed beside a second generic line. The
mutation each test catches is named in its own docstring.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._status_labels import (
    QUARANTINED_COLLECTIONS_FAMILY,
    STORE_FORMAT_FAMILY,
    DegradedFinding,
    degradation_findings,
)
from ..config import EnvVar, reset_config
from ..qdrant_runtime._constants import QDRANT_SERVER_VERSION, QdrantRuntimeState
from ..qdrant_runtime._resolve import (
    STORE_FORMAT_MATCH,
    STORE_FORMAT_MIGRATED,
    STORE_FORMAT_SKEW,
    STORE_FORMAT_UNVERIFIABLE,
    evaluate_store_format,
    read_store_format,
    store_format_path,
    write_store_format,
)
from ..qdrant_runtime._supervise import (
    _MAX_QUARANTINES_PER_START,  # pyright: ignore[reportPrivateUsage]
    QdrantSupervisor,
    _corrupt_collection_from_output,  # pyright: ignore[reportPrivateUsage]
    _list_on_disk_collections,  # pyright: ignore[reportPrivateUsage]
    _quarantine_collection,  # pyright: ignore[reportPrivateUsage]
)
from ..server._lifespan import _service_health_status

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..service import ServiceHealth

pytestmark = [pytest.mark.unit]


#: The version every fixture treats as "the binary that wrote this store".
_WROTE_THE_STORE = "1.18.2"
#: A different pinned version, standing in for an upgraded server binary.
_UPGRADED = "1.19.0"


def _make_collection(storage: Path, name: str) -> Path:
    """Create a non-empty collection directory under ``collections/``."""
    col = storage / "collections" / name
    col.mkdir(parents=True, exist_ok=True)
    (col / "segment.bin").write_bytes(b"data")
    return col


def _stamp_store(storage: Path, version: str) -> None:
    """Record *version* as the server that last opened *storage*."""
    storage.mkdir(parents=True, exist_ok=True)
    write_store_format(storage, qdrant_version=version)


class TestQuarantine:
    """The quarantine primitive moves a collection aside reversibly."""

    def test_quarantine_moves_collection_out_of_the_load_set(
        self, tmp_path: Path
    ) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        healthy = _make_collection(tmp_path, "r0def_vault_docs")

        dest = _quarantine_collection(tmp_path, "r0abc_vault_docs")

        assert dest.exists()
        assert dest.parent == tmp_path / "quarantine"
        assert (dest / "segment.bin").read_bytes() == b"data"  # preserved, not deleted
        assert not (tmp_path / "collections" / "r0abc_vault_docs").exists()
        assert healthy.exists()  # the healthy collection is untouched

    def test_quarantine_dir_is_a_sibling_of_collections(self, tmp_path: Path) -> None:
        """The quarantine dir must be a sibling of collections/ (Qdrant loads it)."""
        _make_collection(tmp_path, "r0abc_vault_docs")
        dest = _quarantine_collection(tmp_path, "r0abc_vault_docs")
        assert dest.parent == tmp_path / "quarantine"
        assert "collections" not in dest.relative_to(tmp_path).parts


class TestDetection:
    """Detection keys on the on-disk set, and abstains when unsure."""

    def test_names_the_on_disk_collection_on_a_load_panic(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        tail = (
            "thread 'main' panicked: cannot load collection "
            "r0abc_vault_docs: corrupt segment"
        )
        assert _corrupt_collection_from_output(tail, tmp_path) == "r0abc_vault_docs"

    def test_abstains_without_a_load_failure_marker(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        # Names the collection but no load-failure marker -> do not quarantine.
        tail = "INFO serving collection r0abc_vault_docs on port 6333"
        assert _corrupt_collection_from_output(tail, tmp_path) is None

    def test_abstains_when_no_on_disk_collection_is_named(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        # A bind failure: has a marker word but names no on-disk collection.
        tail = "panicked: address already in use; failed to bind 127.0.0.1:6333"
        assert _corrupt_collection_from_output(tail, tmp_path) is None

    def test_prefers_the_longest_matching_name(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        _make_collection(tmp_path, "r0abc_vault_docs_codebase")
        tail = "panic: corrupt segment in r0abc_vault_docs_codebase"
        # The shorter name is a substring of the longer; the longer is the culprit.
        assert (
            _corrupt_collection_from_output(tail, tmp_path)
            == "r0abc_vault_docs_codebase"
        )

    def test_empty_tail_is_no_culprit(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        assert _corrupt_collection_from_output("   ", tmp_path) is None

    def test_list_excludes_dot_dirs(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        (tmp_path / "collections" / ".quarantine").mkdir(parents=True, exist_ok=True)
        assert _list_on_disk_collections(tmp_path) == {"r0abc_vault_docs"}


# Fake binary that dies after naming the first on-disk collection on one panic
# line (detection identifies a real culprit). It never becomes ready, so a
# supervised start quarantines under its bound and then fails.
_FAKE_CORRUPT_NAMED = """
import os, pathlib, sys

storage = pathlib.Path(os.environ["QDRANT__STORAGE__STORAGE_PATH"])
cols = sorted(
    p.name
    for p in (storage / "collections").iterdir()
    if p.is_dir() and not p.name.startswith(".")
)
if cols:
    sys.stdout.write(
        "thread 'main' panicked: cannot load collection %s: corrupt segment\\n"
        % cols[0]
    )
    sys.stdout.flush()
sys.exit(1)
"""

# Fake binary that dies on a global fault naming no collection - detection must
# abstain, so the start fails with zero quarantines.
_FAKE_CORRUPT_UNNAMED = """
import sys
sys.stdout.write("thread 'main' panicked: corrupt raft_state.json; aborting\\n")
sys.stdout.flush()
sys.exit(1)
"""


def _free_loopback_ports() -> tuple[int, int]:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as http_sock,
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as grpc_sock,
    ):
        http_sock.bind(("127.0.0.1", 0))
        grpc_sock.bind(("127.0.0.1", 0))
        return int(http_sock.getsockname()[1]), int(grpc_sock.getsockname()[1])


def _fake_binary(tmp_path: Path, source: str, name: str = "fake_qdrant") -> Path:
    """Write a fake qdrant 'binary' the supervisor can exec as ``[binary]``."""
    script = tmp_path / f"{name}.py"
    script.write_text(source, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / f"{name}.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}"\r\n', encoding="utf-8")
        return launcher
    launcher = tmp_path / f"{name}.sh"
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8"
    )
    launcher.chmod(0o755)
    return launcher


class TestBoundedRetry:
    """The supervised start quarantines under its bound, then fails loudly."""

    def test_perpetually_corrupt_store_quarantines_up_to_the_bound_then_raises(
        self, tmp_path: Path
    ) -> None:
        storage = tmp_path / "qdrant-server" / "storage"
        # More collections than the quarantine bound, so the loop must stop.
        for i in range(_MAX_QUARANTINES_PER_START + 2):
            _make_collection(storage, f"r{i:04d}_vault_docs")
        # The recovery path is only reachable once the store proves this exact
        # binary wrote it; without the stamp the abstention below would be the
        # format gate rather than the bound this test is about.
        _stamp_store(storage, _WROTE_THE_STORE)

        binary = _fake_binary(tmp_path, _FAKE_CORRUPT_NAMED)
        sup = QdrantSupervisor(
            binary,
            http_port=8990,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_WROTE_THE_STORE,
        )
        try:
            with pytest.raises(RuntimeError, match="failed to become ready"):
                sup.start(timeout=10.0)
        finally:
            sup.stop()

        # Exactly the bound's worth of collections were quarantined, no more.
        quarantined = list((storage / "quarantine").iterdir())
        assert len(quarantined) == _MAX_QUARANTINES_PER_START
        remaining = _list_on_disk_collections(storage)
        assert len(remaining) == 2  # the two beyond the bound are untouched

    def test_dead_child_naming_no_collection_abstains_with_zero_quarantines(
        self, tmp_path: Path
    ) -> None:
        """A global panic naming no on-disk collection quarantines nothing."""
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        # Stamped, so the abstention proven here is the detector's own and not
        # the store-format gate standing in for it.
        _stamp_store(storage, _WROTE_THE_STORE)
        binary = _fake_binary(tmp_path, _FAKE_CORRUPT_UNNAMED, name="unnamed")
        sup = QdrantSupervisor(
            binary,
            http_port=8992,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_WROTE_THE_STORE,
        )
        try:
            with pytest.raises(RuntimeError, match="failed to become ready"):
                sup.start(timeout=10.0)
        finally:
            sup.stop()
        assert not (storage / "quarantine").exists()
        assert _list_on_disk_collections(storage) == {"r0000_vault_docs"}

    @pytest.mark.integration
    def test_readiness_timeout_with_a_live_child_quarantines_nothing(
        self,
        tmp_path: Path,
        required_host_provisioned_qdrant_source: tuple[Path, Path],
    ) -> None:
        """A healthy-but-slow child that times out must not be read as corrupt."""
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        binary, _manifest = required_host_provisioned_qdrant_source
        # Stamped with the version actually being run, so the liveness guard is
        # what abstains here rather than the store-format gate.
        _stamp_store(storage, QDRANT_SERVER_VERSION)
        http_port, grpc_port = _free_loopback_ports()
        sup = QdrantSupervisor(
            binary,
            http_port=http_port,
            grpc_port=grpc_port,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=QDRANT_SERVER_VERSION,
        )
        try:
            # A zero readiness budget makes the real child hit the timeout path
            # while it is still alive, before startup can report readiness.
            with pytest.raises(RuntimeError, match="failed to become ready"):
                sup.start(timeout=0.0)
        finally:
            sup.stop()
        assert not (storage / "quarantine").exists()
        assert _list_on_disk_collections(storage) == {"r0000_vault_docs"}

    def test_auto_quarantine_disabled_never_touches_the_store(
        self, tmp_path: Path
    ) -> None:
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        # Stamped and matching, so the flag is the only thing holding the
        # quarantine back.
        _stamp_store(storage, _WROTE_THE_STORE)
        binary = _fake_binary(tmp_path, _FAKE_CORRUPT_NAMED)
        sup = QdrantSupervisor(
            binary,
            http_port=8991,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_WROTE_THE_STORE,
        )
        try:
            with pytest.raises(RuntimeError, match="failed to become ready"):
                sup.start(timeout=10.0, auto_quarantine=False)
        finally:
            sup.stop()
        assert not (storage / "quarantine").exists()
        assert _list_on_disk_collections(storage) == {"r0000_vault_docs"}


class TestStoreFormatRecord:
    """The store carries the server version that wrote it, or nothing at all."""

    def test_absent_record_is_unverifiable_never_a_match(self, tmp_path: Path) -> None:
        """An unstamped store must never be read as proof of a match.

        Mutation it catches: defaulting the recorded version to the running one
        when no record exists. That would hand the quarantine path a forged
        match on exactly the stores that have never been verified.
        """
        verdict = evaluate_store_format(tmp_path, _WROTE_THE_STORE)

        assert verdict.status == STORE_FORMAT_UNVERIFIABLE
        assert not verdict.quarantine_trustworthy

    def test_matching_record_is_a_match(self, tmp_path: Path) -> None:
        _stamp_store(tmp_path, _WROTE_THE_STORE)

        verdict = evaluate_store_format(tmp_path, _WROTE_THE_STORE)

        assert verdict.status == STORE_FORMAT_MATCH
        assert verdict.quarantine_trustworthy

    def test_differing_record_is_skew(self, tmp_path: Path) -> None:
        """The condition the whole guard turns on.

        Mutation it catches: comparing only the major/minor line, which is the
        coupling the pinned version already has to the client and which says
        nothing about the on-disk format.
        """
        _stamp_store(tmp_path, _WROTE_THE_STORE)

        verdict = evaluate_store_format(tmp_path, _UPGRADED)

        assert verdict.status == STORE_FORMAT_SKEW
        assert not verdict.quarantine_trustworthy
        assert _WROTE_THE_STORE in verdict.reason
        assert _UPGRADED in verdict.reason

    def test_unknown_running_version_is_unverifiable(self, tmp_path: Path) -> None:
        """An operator-supplied binary carries no version to compare."""
        _stamp_store(tmp_path, _WROTE_THE_STORE)

        verdict = evaluate_store_format(tmp_path, "")

        assert verdict.status == STORE_FORMAT_UNVERIFIABLE
        assert not verdict.quarantine_trustworthy

    def test_unknown_version_is_never_recorded(self, tmp_path: Path) -> None:
        """An empty stamp would read back as a record and prove nothing."""
        assert write_store_format(tmp_path, qdrant_version="") is None
        assert not store_format_path(tmp_path).exists()
        assert read_store_format(tmp_path) == ""

    def test_the_record_is_not_mistaken_for_a_collection(self, tmp_path: Path) -> None:
        """The record lives in the store, so it must stay out of the load set."""
        _make_collection(tmp_path, "r0abc_vault_docs")
        _stamp_store(tmp_path, _WROTE_THE_STORE)

        assert store_format_path(tmp_path).parent == tmp_path
        assert _list_on_disk_collections(tmp_path) == {"r0abc_vault_docs"}

    def test_a_malformed_record_reads_as_no_record(self, tmp_path: Path) -> None:
        """Unreadable evidence is missing evidence, not a crash and not a pass."""
        store_format_path(tmp_path).write_text("{not json", encoding="utf-8")

        assert read_store_format(tmp_path) == ""
        assert evaluate_store_format(tmp_path, _WROTE_THE_STORE).status == (
            STORE_FORMAT_UNVERIFIABLE
        )


class TestVersionSkewNeverQuarantines:
    """A server-version change must not be misread as per-collection corruption.

    An incompatible binary aborts naming the collection it choked on, which is
    the same shape a genuinely corrupt collection produces. Trusting that shape
    walks a healthy store into quarantine three collections at a time while the
    daemon still comes up. These are the guards against that.
    """

    def test_skewed_store_refuses_to_quarantine_a_named_collection(
        self, tmp_path: Path
    ) -> None:
        """The issue reproduction: an upgraded binary must not eat the store.

        Mutation it catches: removing the ``quarantine_trustworthy`` gate from
        ``start``. Without it the panic below names a real on-disk collection
        and the collection is moved out of the load set - silently, because the
        retry then continues and the daemon still reports healthy.
        """
        storage = tmp_path / "qdrant-server" / "storage"
        for i in range(_MAX_QUARANTINES_PER_START + 2):
            _make_collection(storage, f"r{i:04d}_vault_docs")
        _stamp_store(storage, _WROTE_THE_STORE)
        before = _list_on_disk_collections(storage)

        binary = _fake_binary(tmp_path, _FAKE_CORRUPT_NAMED)
        sup = QdrantSupervisor(
            binary,
            http_port=8993,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_UPGRADED,
        )
        try:
            with pytest.raises(RuntimeError, match="NOT being quarantined"):
                sup.start(timeout=10.0)
        finally:
            sup.stop()

        assert not (storage / "quarantine").exists()
        assert _list_on_disk_collections(storage) == before

    def test_the_refusal_names_both_versions_and_the_manual_verb(
        self, tmp_path: Path
    ) -> None:
        """The operator has to learn what changed and what to run next."""
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        _stamp_store(storage, _WROTE_THE_STORE)

        binary = _fake_binary(tmp_path, _FAKE_CORRUPT_NAMED)
        sup = QdrantSupervisor(
            binary,
            http_port=8994,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_UPGRADED,
        )
        try:
            with pytest.raises(RuntimeError) as caught:
                sup.start(timeout=10.0)
        finally:
            sup.stop()

        message = str(caught.value)
        assert _WROTE_THE_STORE in message
        assert _UPGRADED in message
        assert "server qdrant quarantine r0000_vault_docs" in message

    def test_unstamped_store_refuses_to_quarantine(self, tmp_path: Path) -> None:
        """Every store predating the record is unverifiable, so none is eaten.

        Mutation it catches: treating an absent record as permission to
        quarantine. That is the state every existing store is in on the first
        start after this guard ships, so it is the one that must fail closed.
        """
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")

        binary = _fake_binary(tmp_path, _FAKE_CORRUPT_NAMED)
        sup = QdrantSupervisor(
            binary,
            http_port=8995,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_WROTE_THE_STORE,
        )
        try:
            with pytest.raises(RuntimeError, match="NOT being quarantined"):
                sup.start(timeout=10.0)
        finally:
            sup.stop()

        assert not (storage / "quarantine").exists()
        assert _list_on_disk_collections(storage) == {"r0000_vault_docs"}


# A fake that actually serves, so a successful open - and the record it writes -
# is exercised end to end rather than asserted about. It answers /readyz and
# reports its version on the root route exactly as the real server does, and
# bounds its own life so a missed terminate cannot hold the port.
_FAKE_READY_SERVER_BODY = """
import http.server
import json
import os
import threading

PORT = int(os.environ["QDRANT__SERVICE__HTTP_PORT"])


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path.startswith("/readyz"):
            body = b"all shards are ready"
        else:
            body = json.dumps({"title": "qdrant", "version": VERSION}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        return


threading.Timer(20.0, os._exit, args=(0,)).start()
http.server.HTTPServer(("127.0.0.1", PORT), _Handler).serve_forever()
"""


def _fake_ready_source(version: str) -> str:
    """A serving fake that reports *version* on its root route."""
    return f'VERSION = "{version}"\n{_FAKE_READY_SERVER_BODY}'


class TestSuccessfulOpenRecordsTheVersion:
    """A store that opened records what opened it, and says when that changed."""

    def test_a_successful_start_records_the_running_version(
        self, tmp_path: Path
    ) -> None:
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        http_port, grpc_port = _free_loopback_ports()
        binary = _fake_binary(tmp_path, _fake_ready_source(_UPGRADED), name="ready")
        sup = QdrantSupervisor(
            binary,
            http_port=http_port,
            grpc_port=grpc_port,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_UPGRADED,
        )
        try:
            sup.start(timeout=30.0)
        finally:
            sup.stop()

        assert read_store_format(storage) == _UPGRADED

    def test_a_version_change_that_opens_is_reported_as_migrated(
        self, tmp_path: Path
    ) -> None:
        """A carried-forward store is a fact the operator has to be handed.

        Mutation it catches: overwriting the record on a successful open and
        leaving the verdict at ``match``. The store would then be silently
        unreadable by the binary that wrote it, with nothing on any surface
        saying so.
        """
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        _stamp_store(storage, _WROTE_THE_STORE)
        http_port, grpc_port = _free_loopback_ports()
        binary = _fake_binary(tmp_path, _fake_ready_source(_UPGRADED), name="ready")
        sup = QdrantSupervisor(
            binary,
            http_port=http_port,
            grpc_port=grpc_port,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
            binary_version=_UPGRADED,
        )
        try:
            sup.start(timeout=30.0)
            verdict = sup.store_format_verdict()
            reported = sup.state().to_dict()
        finally:
            sup.stop()

        assert verdict is not None
        assert verdict.status == STORE_FORMAT_MIGRATED
        assert verdict.recorded == _WROTE_THE_STORE
        assert verdict.running == _UPGRADED
        assert reported["store_format"] == verdict.to_dict()
        assert read_store_format(storage) == _UPGRADED


def _health(**overrides: object) -> ServiceHealth:
    """Build a registry health dict with nothing wrong in it."""
    base: dict[str, object] = {
        "model_loaded": True,
        "reranker_loaded": True,
        "cuda": True,
        "project_count": 1,
        "projects": ["/proj"],
        "nonconforming": [],
    }
    base.update(overrides)
    return cast("ServiceHealth", base)


def _server_qdrant(**extra: object) -> QdrantRuntimeState:
    """A live supervised runtime state carrying *extra* observations."""
    return QdrantRuntimeState(mode="server", alive=True, extra=dict(extra))


class TestStoreLossReachesTheOperator:
    """Whatever startup did to the data has to leave the daemon log.

    A quarantined collection answers no query and raises no error - the root
    behind it simply returns nothing. Every probe stays green, so the health
    surface saying so is the only thing between an operator and a search index
    that quietly lost a third of itself.
    """

    def test_a_clean_supervised_store_reports_nothing(self) -> None:
        status, reasons = _service_health_status(_health(), _server_qdrant())

        assert status == "ready"
        assert reasons == []

    def test_quarantined_collections_degrade_the_service(self) -> None:
        """The defect this fix exists to remove: quarantined, still healthy.

        Mutation it catches: dropping the quarantine branch from
        ``_qdrant_storage_reasons``. The service then reports ready with
        collections moved out of the store, which is the silent loss the whole
        feature is about.
        """
        status, reasons = _service_health_status(
            _health(),
            _server_qdrant(quarantined_collections=["r0000_vault_docs"]),
        )

        assert status == "degraded"
        assert any("quarantined" in reason for reason in reasons)
        assert any("r0000_vault_docs" in reason for reason in reasons)

    def test_a_migrated_store_degrades_the_service(self) -> None:
        """Mutation it catches: reporting the migration only to the log."""
        status, reasons = _service_health_status(
            _health(),
            _server_qdrant(
                store_format={
                    "status": STORE_FORMAT_MIGRATED,
                    "recorded": _WROTE_THE_STORE,
                    "running": _UPGRADED,
                    "reason": "carried forward",
                }
            ),
        )

        assert status == "degraded"
        assert any("storage format" in reason for reason in reasons)
        assert any(_WROTE_THE_STORE in reason for reason in reasons)

    def test_an_unverifiable_store_format_is_not_a_degradation(self) -> None:
        """Unverifiable withholds the quarantine; it never fails the service.

        Mutation it catches: degrading on any status other than ``match``. Every
        store predating the record is unverifiable, so that would report every
        existing install as degraded forever with nothing an operator can do.
        """
        status, reasons = _service_health_status(
            _health(),
            _server_qdrant(
                store_format={
                    "status": STORE_FORMAT_UNVERIFIABLE,
                    "recorded": None,
                    "running": _WROTE_THE_STORE,
                    "reason": "no record",
                }
            ),
        )

        assert status == "ready"
        assert reasons == []


def _findings_for(qdrant: QdrantRuntimeState) -> list[DegradedFinding]:
    """Render the operator findings the service would report for *qdrant*."""
    status, reasons = _service_health_status(_health(), qdrant)
    return degradation_findings(
        {"status": status, "degraded_reasons": reasons, "qdrant": qdrant.to_dict()}
    )


class TestStoreLossPairsWithItsRemedy:
    """Each reason reaches the operator carrying the verb that inspects it.

    Every assertion here requires the service's OWN sentence to have claimed the
    remedy. A finding the renderer emitted on its own would satisfy a check on
    the family alone while the reason beside it went out unpaired, so the count
    and the identity of the cause are both load-bearing.
    """

    def test_the_quarantine_reason_pairs_with_the_quarantine_verb(self) -> None:
        """Mutation it catches: a stem the authored reason does not contain.

        The reason then goes out unclaimed and the renderer emits its own
        generic cause beside it - two lines for one problem, and the operator's
        sentence carries no command.
        """
        _, reasons = _service_health_status(
            _health(), _server_qdrant(quarantined_collections=["r0000_vault_docs"])
        )

        findings = _findings_for(
            _server_qdrant(quarantined_collections=["r0000_vault_docs"])
        )

        assert len(findings) == 1
        assert findings[0].family == QUARANTINED_COLLECTIONS_FAMILY
        assert findings[0].cause in reasons
        assert findings[0].command == "vaultspec-rag server qdrant quarantine"

    def test_the_migration_reason_pairs_with_the_qdrant_status_verb(self) -> None:
        """Mutation it catches: the same unclaimed-stem split for the migration."""
        store_format = {
            "status": STORE_FORMAT_MIGRATED,
            "recorded": _WROTE_THE_STORE,
            "running": _UPGRADED,
            "reason": "carried forward",
        }
        _, reasons = _service_health_status(
            _health(), _server_qdrant(store_format=store_format)
        )

        findings = _findings_for(_server_qdrant(store_format=store_format))

        assert len(findings) == 1
        assert findings[0].family == STORE_FORMAT_FAMILY
        assert findings[0].cause in reasons
        assert findings[0].command == "vaultspec-rag server qdrant status"
        assert _UPGRADED in findings[0].detail


_runner = CliRunner()


@pytest.fixture
def isolated_storage(tmp_path: Path) -> Iterator[Path]:
    """Point VAULTSPEC_RAG_QDRANT_STORAGE_DIR at a temp store for the CLI verb."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    prev = os.environ.get(key)
    storage = tmp_path / "qdrant-server" / "storage"
    os.environ[key] = str(storage)
    reset_config()
    try:
        yield storage
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


class TestQuarantineCli:
    """The `server qdrant quarantine` escape-hatch verb lists and moves."""

    def test_list_dry_run_refuse_then_quarantine(self, isolated_storage: Path) -> None:
        _make_collection(isolated_storage, "r0abc_vault_docs")
        _make_collection(isolated_storage, "r0def_codebase_docs")

        listing = _runner.invoke(app, ["server", "qdrant", "quarantine", "--json"])
        assert listing.exit_code == 0
        names = json.loads(listing.stdout)["data"]["collections"]
        assert set(names) == {"r0abc_vault_docs", "r0def_codebase_docs"}

        # --dry-run does not move the collection.
        preview = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "r0abc_vault_docs", "--dry-run"]
        )
        assert preview.exit_code == 0
        assert (isolated_storage / "collections" / "r0abc_vault_docs").exists()

        # Without --yes the move is refused.
        refused = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "r0abc_vault_docs"]
        )
        assert refused.exit_code == 1
        assert (isolated_storage / "collections" / "r0abc_vault_docs").exists()

        # With --yes it is quarantined; the healthy collection stays.
        moved = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "r0abc_vault_docs", "--yes"]
        )
        assert moved.exit_code == 0
        assert not (isolated_storage / "collections" / "r0abc_vault_docs").exists()
        assert list((isolated_storage / "quarantine").iterdir())
        assert _list_on_disk_collections(isolated_storage) == {"r0def_codebase_docs"}

    def test_unknown_collection_exits_nonzero(self, isolated_storage: Path) -> None:
        _make_collection(isolated_storage, "r0abc_vault_docs")
        result = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "does_not_exist", "--yes"]
        )
        assert result.exit_code == 1
        assert not (isolated_storage / "quarantine").exists()
