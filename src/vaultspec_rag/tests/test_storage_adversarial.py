"""Adversarial / data-safety unit tests for the storage surface.

These guard the invariants that make accidental out-of-scope destruction
impossible: the destructive CLI verbs refuse a ``--json`` run without
``--yes`` (no prompt can corrupt a machine stream into an unintended
apply), an invalid migrate target is rejected before any client opens,
and path-containment rejects traversal / escape. The server-backed
out-of-scope-protection invariant (prune deletes only orphaned, never
unknown or live) lives in the integration suite.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
import typer
from qdrant_client import QdrantClient, models
from typer.testing import CliRunner

from ..cli import app
from ..cli._service_storage import _emit_or_echo_error, _require_yes_for_json
from ..storage_safety import StorageSafetyError, resolve_within

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ..storage_ops import DeleteResult

pytestmark = [pytest.mark.unit]

runner = CliRunner()


@pytest.mark.parametrize(
    "command",
    ["server.storage.delete", "server.storage.prune", "server.storage.migrate"],
)
def test_json_without_yes_is_refused(command: str) -> None:
    """Every destructive verb refuses --json unless --yes is also given."""
    with pytest.raises(typer.Exit) as exc:
        _require_yes_for_json(command, json_mode=True, yes=False)
    assert exc.value.exit_code == 2


def test_json_with_yes_is_allowed() -> None:
    # --json + --yes is the scripted apply path: no exit raised.
    _require_yes_for_json("server.storage.delete", json_mode=True, yes=True)


def test_human_mode_without_yes_is_allowed() -> None:
    # Human mode prompts/previews instead of erroring on the json guard.
    _require_yes_for_json("server.storage.delete", json_mode=False, yes=False)


def test_emit_or_echo_error_exits_with_code() -> None:
    with pytest.raises(typer.Exit) as exc:
        _emit_or_echo_error(
            "server.storage.migrate", "invalid_target", "bad", 2, json_mode=False
        )
    assert exc.value.exit_code == 2


def test_traversal_escape_is_rejected(tmp_path: object) -> None:
    from pathlib import Path

    base = Path(str(tmp_path)) / "managed"
    base.mkdir()
    with pytest.raises(StorageSafetyError):
        resolve_within(base / ".." / ".." / "etc", base)


class TestDeleteRootAddressing:
    """``server storage delete --root``: resolution parity and idempotency.

    Every collection here is a real local Qdrant collection and the removal
    is the real ``delete_prefix`` against a real manifest, so what these
    assertions read is what actually survived the verb. Only the client
    handoff is redirected: the verb opens an HTTP client to the managed
    server, and these tests hand it a local one instead, which is why the
    unreachable-server mapping is asserted elsewhere.
    """

    @pytest.fixture
    def storage(
        self,
        isolated_status_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> Generator[QdrantClient]:
        """Run the verb against a real local store and a relocated manifest."""
        del isolated_status_dir
        from ..cli import _service_storage

        client = QdrantClient(path=str(tmp_path / "storage"))

        def _direct(
            _command: str, _json_mode: bool, fn: Callable[[QdrantClient], DeleteResult]
        ) -> DeleteResult:
            return fn(client)

        monkeypatch.setattr(_service_storage, "_run_storage_op", _direct)
        try:
            yield client
        finally:
            client.close()

    @staticmethod
    def _create(client: QdrantClient, *names: str) -> None:
        for name in names:
            client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=4, distance=models.Distance.COSINE
                ),
            )

    @staticmethod
    def _live(client: QdrantClient) -> set[str]:
        return {c.name for c in client.get_collections().collections}

    @staticmethod
    def _registered_root(tmp_path: Path, name: str) -> tuple[Path, str]:
        """Create a root, record it in the manifest, return it and its prefix."""
        from ..storage_manifest import record_root
        from ..store import root_collection_prefix

        root = tmp_path / name
        root.mkdir()
        record_root(root, backend="server")
        return root, root_collection_prefix(root)

    def test_both_prefix_and_root_are_rejected(self) -> None:
        result = runner.invoke(
            app,
            ["server", "storage", "delete", "rdeadbeef0000_", "--root", ".", "-y"],
        )
        assert result.exit_code == 2

    def test_neither_prefix_nor_root_is_rejected_as_json_envelope(self) -> None:
        result = runner.invoke(app, ["server", "storage", "delete", "--json", "--yes"])
        assert result.exit_code == 2
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["error"] == "bad_request"

    def test_root_deletes_exactly_the_namespace_registration_derived(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """``--root`` reaches the registered namespace and no neighbour's.

        Both roots are registered and both hold real collections, so a
        derivation that drifted from the one registration uses would either
        miss the target or take the bystander with it - and the store is
        asked afterwards which of the two is still there.

        Proven able to fail: replacing the verb's derivation with a fixed
        canonical prefix leaves the target collection standing, failing the
        assertion that it is gone. Restored, it passes.
        """
        root, prefix = self._registered_root(tmp_path, "target")
        _, bystander = self._registered_root(tmp_path, "bystander")
        self._create(storage, f"{prefix}vault_docs", f"{bystander}vault_docs")

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes", "--json"],
        )

        assert result.exit_code == 0, result.output
        live = self._live(storage)
        assert f"{prefix}vault_docs" not in live
        assert f"{bystander}vault_docs" in live
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "removed"
        assert envelope["data"]["queried_root"]["prefix"] == prefix

    def test_absent_namespace_is_an_idempotent_success(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """A root the store never held tears down as a success, not a fault.

        The store is genuinely empty here, so ``no_such_namespace`` is the
        real gate's own finding rather than a stated one.

        Proven able to fail: dropping the remap of that finding leaves the
        raw ``skipped``/``no_such_namespace`` pair in the envelope, failing
        the ``already_absent`` assertion. Restored, it passes.
        """
        del storage
        root, _ = self._registered_root(tmp_path, "never-stored")

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes", "--json"],
        )

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "already_absent"
        assert envelope["data"]["reason"] is None

    def test_absent_namespace_exits_zero_in_human_mode_too(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """The operator reading prose is told the same thing as the broker.

        Proven able to fail: under the same mutation as the sibling test
        the line reads "Skipped ...: no_such_namespace", failing the phrase
        assertion. Restored, it passes.
        """
        del storage
        root, _ = self._registered_root(tmp_path, "never-stored")
        result = runner.invoke(
            app, ["server", "storage", "delete", "--root", str(root), "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "already absent" in result.output

    def test_unattributable_namespace_survives_the_delete(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """Data the manifest cannot vouch for is reported, never destroyed.

        The root is deliberately left out of the manifest while its
        collection really exists, which is the shape of a namespace written
        by something this installation does not know about. The load-bearing
        assertion is the survival, not the envelope: a refusal that still
        deleted would be the worst outcome and reads identically otherwise.

        Proven able to fail: dropping the manifest-attribution gate in
        ``delete_prefix`` removes the collection, failing the survival
        assertion. Restored, it passes.
        """
        from ..store import root_collection_prefix

        root = tmp_path / "unattributable"
        root.mkdir()
        prefix = root_collection_prefix(root)
        self._create(storage, f"{prefix}vault_docs")

        result = runner.invoke(
            app,
            ["server", "storage", "delete", "--root", str(root), "--yes", "--json"],
        )

        assert result.exit_code == 0, result.output
        assert f"{prefix}vault_docs" in self._live(storage)
        envelope = json.loads(result.output)
        assert envelope["data"]["status"] == "skipped"
        assert envelope["data"]["reason"] == "unknown_namespace"

    def test_prefix_form_deletes_and_reports_no_queried_root(
        self, storage: QdrantClient, tmp_path: Path
    ) -> None:
        """Addressing by prefix removes the same namespace, minus the echo.

        ``queried_root`` answers "which namespace did my path resolve to",
        a question a caller that supplied the prefix never asked; emitting
        it anyway would let a consumer read a path it never gave.
        """
        _, prefix = self._registered_root(tmp_path, "by-prefix")
        self._create(storage, f"{prefix}vault_docs")

        result = runner.invoke(
            app, ["server", "storage", "delete", prefix, "--yes", "--json"]
        )

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["data"]["status"] == "removed"
        assert "queried_root" not in envelope["data"]
        assert f"{prefix}vault_docs" not in self._live(storage)


class TestReconcileRendering:
    """The reconcile verb's structured contract.

    Reconcile is non-destructive, but it is still broker-facing: an
    already-converged backend must read as success rather than as a fault,
    and a still-converging collection must never carry a reclaim figure a
    caller could bank on.
    """

    def test_json_without_yes_is_refused(self) -> None:
        with pytest.raises(typer.Exit) as exc:
            _require_yes_for_json("server.storage.reconcile", json_mode=True, yes=False)
        assert exc.value.exit_code == 2

    def test_converged_backend_renders_as_success(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_storage import _render_reconcile
        from ..storage_ops import ReconcileBatch

        _render_reconcile(
            ReconcileBatch(
                results=[], drifted_remaining=0, reclaimed_bytes=0, dry_run=False
            ),
            json_mode=True,
        )

        payload = json.loads(capsys.readouterr().out)
        assert payload["ok"] is True
        assert payload["data"]["status"] == "already_converged"
        assert payload["data"]["results"] == []

    def test_converging_entry_carries_no_reclaim_figure(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_storage import _render_reconcile
        from ..storage_ops import ReconcileBatch, ReconcileResult

        _render_reconcile(
            ReconcileBatch(
                results=[
                    ReconcileResult(
                        "rfeedfacefeed_vault_docs",
                        "converging",
                        segments_before=8,
                        bytes_before=1_000_000,
                        reason="convergence_budget_expired",
                    )
                ],
                drifted_remaining=1,
                reclaimed_bytes=0,
                dry_run=False,
            ),
            json_mode=True,
        )

        entry = json.loads(capsys.readouterr().out)["data"]["results"][0]
        assert entry["status"] == "converging"
        assert entry["bytes_after"] is None
        assert entry["reclaimed_bytes"] == 0

    def test_preview_is_never_reported_as_applied(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A broker keys on `status`; a preview changed nothing."""
        from ..cli._service_storage import _render_reconcile
        from ..storage_ops import ReconcileBatch, ReconcileResult

        _render_reconcile(
            ReconcileBatch(
                results=[
                    ReconcileResult(
                        "rfeedfacefeed_vault_docs",
                        "would_reconcile",
                        segments_before=8,
                        bytes_before=1_000_000,
                    )
                ],
                drifted_remaining=1,
                reclaimed_bytes=0,
                dry_run=True,
            ),
            json_mode=True,
        )

        data = json.loads(capsys.readouterr().out)["data"]
        assert data["status"] == "preview"
        assert data["dry_run"] is True

    def test_unwaited_pass_reports_issued_not_applied(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Nothing converged, so nothing was reclaimed to claim."""
        from ..cli._service_storage import _render_reconcile
        from ..storage_ops import ReconcileBatch, ReconcileResult

        _render_reconcile(
            ReconcileBatch(
                results=[
                    ReconcileResult(
                        "rfeedfacefeed_vault_docs",
                        "converging",
                        segments_before=8,
                        bytes_before=1_000_000,
                        reason="not_awaited",
                    )
                ],
                drifted_remaining=1,
                reclaimed_bytes=0,
                dry_run=False,
            ),
            json_mode=True,
        )

        assert json.loads(capsys.readouterr().out)["data"]["status"] == "issued"

    def test_human_mode_does_not_claim_reconciled_when_nothing_converged(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_storage import _render_reconcile
        from ..storage_ops import ReconcileBatch, ReconcileResult

        _render_reconcile(
            ReconcileBatch(
                results=[
                    ReconcileResult(
                        "rfeedfacefeed_vault_docs",
                        "converging",
                        segments_before=8,
                        bytes_before=1_000_000,
                        reason="not_awaited",
                    )
                ],
                drifted_remaining=1,
                reclaimed_bytes=0,
                dry_run=False,
            ),
            json_mode=False,
        )

        out = capsys.readouterr().out
        assert "Reconciled 1 collections" not in out
        assert "Started reconcile on" in out

    def test_human_mode_states_a_converged_backend_plainly(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_storage import _render_reconcile
        from ..storage_ops import ReconcileBatch

        _render_reconcile(
            ReconcileBatch(
                results=[], drifted_remaining=0, reclaimed_bytes=0, dry_run=False
            ),
            json_mode=False,
        )

        assert "already at the bounded geometry" in capsys.readouterr().out


class TestUnreachableStorageStillAnswers:
    """A --json storage verb owes one envelope even when storage is gone.

    The client does not report an unreachable server with OSError; it wraps the
    transport failure in its own ResponseHandlingException, which is a plain
    Exception. While the guard caught only the builtin types that escaped, and a
    --json invocation printed a traceback to stderr and nothing at all to
    stdout - zero envelopes on an exit path, which is precisely what the
    structured-outcome contract forbids and what a broker cannot parse.

    This surfaced as a test that passed on every workstation and failed on CI,
    because a developer machine has a live Qdrant answering on the default port
    and a clean runner does not.
    """

    @pytest.mark.parametrize(
        ("argv", "command"),
        [
            (["server", "storage", "survey", "--json"], "server.storage.survey"),
            (
                ["server", "storage", "prune", "--json", "--yes", "--dry-run"],
                "server.storage.prune",
            ),
        ],
        ids=["survey", "prune"],
    )
    def test_unreachable_storage_emits_exactly_one_fault_envelope(
        self,
        isolated_singleton_dirs: Path,
        monkeypatch: pytest.MonkeyPatch,
        argv: list[str],
        command: str,
    ) -> None:
        del isolated_singleton_dirs
        # A port nothing listens on: the real client performs a real connection
        # attempt and raises its real transport exception. Nothing is stubbed.
        monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_PORT", "59997")
        monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_URL", "http://127.0.0.1:59997")
        from ..config import reset_config

        reset_config()

        result = CliRunner().invoke(app, argv)

        # Count every stdout line, not only the ones that parse: a traceback or
        # a stray human line on the result channel is the defect being pinned.
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, result.stdout
        envelope = json.loads(lines[0])
        assert envelope["ok"] is False
        assert envelope["command"] == command
        assert envelope["error"] == "service_not_running"
        assert result.exit_code == 3
