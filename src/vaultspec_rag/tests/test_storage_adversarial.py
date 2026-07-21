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
from typer.testing import CliRunner

from ..cli import app
from ..cli._service_storage import _emit_or_echo_error, _require_yes_for_json
from ..storage_ops import DeleteResult
from ..storage_safety import StorageSafetyError, resolve_within

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

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

    The client and server-mode gate are bypassed (``_run_storage_op`` calls
    the operation directly) so these tests exercise only the verb's
    addressing, outcome mapping, and envelope - the real ``delete_prefix``
    gates have their own coverage.
    """

    @pytest.fixture(autouse=True)
    def _bypass_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from ..cli import _service_storage

        def _direct(
            _command: str, _json_mode: bool, fn: Callable[[None], DeleteResult]
        ) -> DeleteResult:
            return fn(None)

        monkeypatch.setattr(_service_storage, "_run_storage_op", _direct)

    def _record_delete(
        self, monkeypatch: pytest.MonkeyPatch, result_status: str, reason: str | None
    ) -> list[str]:
        from .. import storage_ops

        seen: list[str] = []

        def _fake(_client: object, prefix: str, **_kwargs: object) -> DeleteResult:
            seen.append(prefix)
            return DeleteResult(prefix, result_status, reason=reason)

        monkeypatch.setattr(storage_ops, "delete_prefix", _fake)
        return seen

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

    def test_root_resolves_exactly_like_registration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from ..store import root_collection_prefix

        seen = self._record_delete(monkeypatch, "removed", None)
        result = runner.invoke(
            app,
            [
                "server",
                "storage",
                "delete",
                "--root",
                str(tmp_path),
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        assert seen == [root_collection_prefix(tmp_path)]
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["queried_root"]["prefix"] == seen[0]

    def test_absent_namespace_is_an_idempotent_success(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._record_delete(monkeypatch, "skipped", "no_such_namespace")
        result = runner.invoke(
            app,
            [
                "server",
                "storage",
                "delete",
                "--root",
                str(tmp_path),
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "already_absent"
        assert envelope["data"]["reason"] is None

    def test_absent_namespace_exits_zero_in_human_mode_too(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._record_delete(monkeypatch, "skipped", "no_such_namespace")
        result = runner.invoke(
            app, ["server", "storage", "delete", "--root", str(tmp_path), "--yes"]
        )
        assert result.exit_code == 0, result.output
        assert "already absent" in result.output

    def test_unknown_namespace_refusal_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        self._record_delete(monkeypatch, "skipped", "unknown_namespace")
        result = runner.invoke(
            app,
            [
                "server",
                "storage",
                "delete",
                "--root",
                str(tmp_path),
                "--yes",
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["data"]["status"] == "skipped"
        assert envelope["data"]["reason"] == "unknown_namespace"

    def test_prefix_form_is_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen = self._record_delete(monkeypatch, "removed", None)
        result = runner.invoke(
            app,
            ["server", "storage", "delete", "rdeadbeef0000_", "--yes", "--json"],
        )
        assert result.exit_code == 0, result.output
        assert seen == ["rdeadbeef0000_"]
        envelope = json.loads(result.output)
        assert "queried_root" not in envelope["data"]


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
