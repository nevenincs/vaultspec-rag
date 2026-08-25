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
import re
from typing import TYPE_CHECKING

import pytest
import typer
from typer.testing import CliRunner

from ..cli import app
from ..cli._service_storage import _emit_or_echo_error, _require_yes_for_json
from ..storage_safety import StorageSafetyError, resolve_within

if TYPE_CHECKING:
    from pathlib import Path


pytestmark = [pytest.mark.unit]

runner = CliRunner()


@pytest.mark.parametrize(
    "command",
    [
        "server.storage.delete",
        "server.storage.prune",
        "server.storage.migrate",
        "server.storage.restore",
    ],
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
        from ..storage_reconciliation import ReconcileBatch

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
        from ..storage_reconciliation import ReconcileBatch, ReconcileResult

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
        from ..storage_reconciliation import ReconcileBatch, ReconcileResult

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
        from ..storage_reconciliation import ReconcileBatch, ReconcileResult

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
        from ..storage_reconciliation import ReconcileBatch, ReconcileResult

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
        from ..storage_reconciliation import ReconcileBatch

        _render_reconcile(
            ReconcileBatch(
                results=[], drifted_remaining=0, reclaimed_bytes=0, dry_run=False
            ),
            json_mode=False,
        )

        assert "already at the bounded geometry" in capsys.readouterr().out


class TestRestoreRefusesInOneEnvelope:
    """Restore is the verb that writes into a namespace, so it owes clarity.

    Every exit path here is one an operator or a broker can hit before any
    data moves: no archive at that path, a scripted run without ``--yes``, a
    server that is not answering, and the domain's own refusals. Each must
    exit non-zero and, in JSON mode, say so in exactly one envelope.

    The end-to-end ``destination_exists`` refusal against a populated
    destination needs a real supervised server and lives with the round trip
    in the integration suite; what is pinned here is that the refusal
    reaches the operator intact once the domain returns it.
    """

    def test_a_missing_archive_is_refused_before_any_client_opens(
        self, tmp_path: Path
    ) -> None:
        """Exit 2 and one envelope, without reaching for the server.

        Mutation: dropped the ``is_dir`` guard. Observed this fail with exit
        3 and ``service_not_running`` - the verb had gone to the server to
        ask about an archive that does not exist, turning an operator typo
        into a service-health question.
        """
        result = CliRunner().invoke(
            app,
            [
                "server",
                "storage",
                "restore",
                str(tmp_path / "no-such-archive"),
                "--root",
                str(tmp_path / "destination"),
                "--json",
                "--yes",
            ],
        )

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, result.stdout
        envelope = json.loads(lines[0])
        assert envelope["ok"] is False
        assert envelope["command"] == "server.storage.restore"
        assert envelope["error"] == "archive_not_found"
        assert result.exit_code == 2

    def test_an_unreachable_server_answers_a_real_archive_with_one_envelope(
        self,
        isolated_singleton_dirs: Path,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """A complete archive still exits 3 when nothing is listening."""
        del isolated_singleton_dirs
        from ._storage_archive import write_archive

        archive = write_archive(tmp_path / "archive")
        # A port nothing listens on: the real client performs a real
        # connection attempt and raises its real transport exception.
        monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_PORT", "59997")
        monkeypatch.setenv("VAULTSPEC_RAG_QDRANT_URL", "http://127.0.0.1:59997")
        from ..config._settings import reset_config

        reset_config()

        result = CliRunner().invoke(
            app,
            [
                "server",
                "storage",
                "restore",
                str(archive),
                "--root",
                str(tmp_path / "destination"),
                "--json",
                "--yes",
                "--dry-run",
            ],
        )

        lines = [line for line in result.stdout.splitlines() if line.strip()]
        assert len(lines) == 1, result.stdout
        envelope = json.loads(lines[0])
        assert envelope["ok"] is False
        assert envelope["error"] == "service_not_running"
        assert result.exit_code == 3

    def test_every_reason_the_domain_can_return_has_operator_wording(self) -> None:
        """No refusal may reach an operator as a bare token.

        Enumerated from the domain module rather than listed here: a reason
        added to ``restore_archive`` has to be discovered by this test, not
        remembered by whoever adds it.

        Mutation: removed the Windows entry, which is the one reason that is
        a shared constant rather than a literal in the refusal table.
        Observed this fail naming exactly that reason.
        """
        import inspect

        from .. import storage_restore
        from ..cli._service_storage import _restore_refusals

        source = inspect.getsource(storage_restore.restore_archive)
        returned = {
            literal
            for literal in re.findall(r'"([a-z_]+)"\s*\)', source)
            if literal not in {"refused", "would_restore", "restored", "rb"}
        }
        assert returned, "the reason sweep found nothing; it proves nothing"
        wording = _restore_refusals()
        assert returned <= set(wording), sorted(returned - set(wording))
        # The Windows refusal is a shared constant, so it is checked by name
        # rather than swept out of the source.
        from ..qdrant_runtime._constants import (
            WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON,
        )

        assert WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON in wording

    @pytest.mark.parametrize(
        "reason",
        [
            "destination_exists",
            "local_mode_unsupported",
            "invalid_destination_prefix",
            "invalid_archive_collection",
        ],
    )
    def test_each_domain_refusal_reaches_the_operator_by_its_own_name(
        self, capsys: pytest.CaptureFixture[str], reason: str
    ) -> None:
        """One envelope, ``ok`` false, and the domain's own reason as the error.

        The reason is asserted as the envelope's ``error`` rather than only
        inside ``data``: a broker branches on ``error``, and a refusal that
        arrives as a generic failure with the real cause buried is one the
        caller cannot act on.

        Mutation: emitted every refusal as ``ok`` true, the way the delete
        verb still renders its own failed status. Observed all four
        parametrized cases fail on the ``ok`` assertion below.
        """
        from ..cli._service_storage import _render_restore
        from ..storage_restore import RestoreResult

        _render_restore(
            RestoreResult("refused", "rdeadbeefcafe_", (), reason),
            json_mode=True,
        )

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["ok"] is False
        assert envelope["command"] == "server.storage.restore"
        assert envelope["error"] == reason
        assert envelope["data"]["status"] == "refused"
        # The operator-facing wording must be a sentence, not the bare token
        # echoed back; a refusal that only repeats its own name tells nobody
        # what to do next.
        assert envelope["message"] != reason
        assert envelope["message"].endswith(".")

    def test_a_preview_names_the_exact_destination_collections(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The dry run's whole value is the list it commits to.

        Mutation: reported the archive's own collection names instead of the
        destination's. Observed this fail on the assertion below, previewing
        the source namespace the operator is restoring *from*.
        """
        from ..cli._service_storage import _render_restore
        from ..storage_restore import RestoreResult

        _render_restore(
            RestoreResult(
                "would_restore",
                "rfeedfacefeed_",
                ("rfeedfacefeed_vault_docs", "rfeedfacefeed_code_docs"),
            ),
            json_mode=True,
        )

        lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
        assert len(lines) == 1
        envelope = json.loads(lines[0])
        assert envelope["ok"] is True
        assert envelope["data"]["status"] == "would_restore"
        assert envelope["data"]["collections"] == [
            "rfeedfacefeed_vault_docs",
            "rfeedfacefeed_code_docs",
        ]
        assert envelope["data"]["destination_prefix"] == "rfeedfacefeed_"


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
        from ..config._settings import reset_config

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
