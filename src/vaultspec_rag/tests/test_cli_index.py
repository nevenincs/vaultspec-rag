"""CLI coverage for index, clean, and auto-delegation commands."""

from __future__ import annotations

import json
import typing

import pytest

from ._cli_helpers import (
    _hold_local_index_lock,
    _parsed_json_object,
    _plain_lines,
    app,
    runner,
)
from ._http_stubs import QuietHandler
from ._scaffold import make_workspace

if typing.TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestWorkspaceRequired:
    """Commands that require a workspace should fail gracefully without one."""

    def test_index_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "index"],
        )
        assert result.exit_code != 0

    def test_search_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "search", "query"],
        )
        assert result.exit_code != 0

    def test_status_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "status"],
        )
        assert result.exit_code != 0


class TestCleanCommand:
    """Tests for the wipe-only ``clean`` command."""

    def test_clean_help_renders(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0
        assert "wipe" in result.output.lower()

    def test_clean_confirm_prompt_uses_search_index_language(self, tmp_path: Path):
        root = make_workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "all"],
            input="n\n",
        )

        assert result.exit_code == 1
        assert "Delete all search index data for" in result.output
        assert "Clean cancelled." in result.output
        assert "RAG index data" not in result.output

    def test_clean_noninteractive_abort_uses_operator_language(self, tmp_path: Path):
        root = make_workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "vault"],
        )

        assert result.exit_code == 1
        assert "Clean cancelled." in result.output
        assert "Aborted!" not in result.output

    def test_clean_all_clears_collections_and_metadata(self, tmp_path: Path):
        from ..config._settings import get_config
        from ..store_runtime import VaultStore

        root = make_workspace(tmp_path)
        cfg = get_config()
        data_dir = root / str(cfg.data_dir)
        data_dir.mkdir(parents=True)
        index_metadata_file = data_dir / str(cfg.index_metadata_file)
        index_metadata_file.write_text('{"x": "y"}', encoding="utf-8")
        code_index_metadata_file = data_dir / str(cfg.code_index_metadata_file)
        code_index_metadata_file.write_text(
            '{"src/app.py": "hash"}',
            encoding="utf-8",
        )

        store = VaultStore(root)
        try:
            store.ensure_table()
            store.ensure_code_table()
        finally:
            store.close()

        result = runner.invoke(app, ["--target", str(root), "clean", "all", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Clean summary" in result.output
        assert "Vault index: empty." in result.output
        assert "Source code index: empty." in result.output
        assert "Vault: empty" not in result.output
        assert "Code: empty" not in result.output
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in result.output

        store = VaultStore(root)
        try:
            assert store.count() == 0
            assert store.count_code() == 0
        finally:
            store.close()
        assert not index_metadata_file.exists()
        assert not code_index_metadata_file.exists()

    @pytest.mark.parametrize(
        ("selection", "removed_attr", "kept_attr"),
        [
            ("vault", "index_metadata_file", "code_index_metadata_file"),
            ("codebase", "code_index_metadata_file", "index_metadata_file"),
        ],
    )
    def test_clean_one_source_removes_only_its_own_sidecar(
        self,
        tmp_path: Path,
        selection: str,
        removed_attr: str,
        kept_attr: str,
    ) -> None:
        """A selective clean must not resolve the other source's sidecar.

        Cleaning everything cannot tell a correct resolution from one with the
        two filenames transposed, because both files go either way. Only a
        single-source clean observes which name each branch resolved.
        """
        from ..config._settings import get_config

        root = make_workspace(tmp_path)
        cfg = get_config()
        data_dir = root / str(cfg.data_dir)
        data_dir.mkdir(parents=True)
        removed = data_dir / str(getattr(cfg, removed_attr))
        kept = data_dir / str(getattr(cfg, kept_attr))
        removed.write_text('{"x": "y"}', encoding="utf-8")
        kept.write_text('{"kept": "kept"}', encoding="utf-8")

        result = runner.invoke(
            app, ["--target", str(root), "clean", selection, "--yes"]
        )

        assert result.exit_code == 0, result.output
        assert not removed.exists()
        assert kept.read_text(encoding="utf-8") == '{"kept": "kept"}'

    def test_clean_document_removes_only_the_document_record(
        self, tmp_path: Path
    ) -> None:
        """The document record is named independently of the two index sidecars."""
        from ..config._settings import get_config
        from ..indexer._document_meta import document_metadata_path

        root = make_workspace(tmp_path)
        cfg = get_config()
        data_dir = root / str(cfg.data_dir)
        data_dir.mkdir(parents=True)
        survivors = [
            data_dir / str(cfg.index_metadata_file),
            data_dir / str(cfg.code_index_metadata_file),
        ]
        for survivor in survivors:
            survivor.write_text('{"kept": "kept"}', encoding="utf-8")
        record = document_metadata_path(root)
        record.write_text('{"x": "y"}', encoding="utf-8")

        result = runner.invoke(
            app, ["--target", str(root), "clean", "document", "--yes"]
        )

        assert result.exit_code == 0, result.output
        assert not record.exists()
        for survivor in survivors:
            assert survivor.read_text(encoding="utf-8") == '{"kept": "kept"}'

    def test_clean_lock_error_uses_operator_language(self, tmp_path: Path) -> None:
        root = make_workspace(tmp_path)
        lock = _hold_local_index_lock(root)
        try:
            result = runner.invoke(
                app,
                ["--target", str(root), "clean", "all", "--yes"],
            )
        finally:
            lock.release()

        assert result.exit_code == 1, result.output
        assert "Cannot clean the index because the local index is busy" in result.output
        assert "vaultspec-rag server status" in result.output
        for leaked in (
            "Qdrant",
            "Local-file-backed",
            "parallel-safe",
            "exclusive.lock",
            "another process holds the lock",
        ):
            assert leaked not in result.output


class TestIndexRebuild:
    """Tests for the drop-and-reindex flag."""

    def test_index_rebuild_parses_with_dry_run(self, tmp_path: Path):
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--rebuild",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "files would be indexed" in result.output

    def test_index_dry_run_rejects_document_indexing_in_user_language(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--type", "vault", "--dry-run"],
        )

        assert result.exit_code == 2
        lines = _plain_lines(result.output)
        assert lines == [
            "Dry run is available for code and document indexing.",
            "Run:",
            "vaultspec-rag index --type code --dry-run",
        ]
        assert "--dry-run only applies" not in result.output
        assert "codebase" not in result.output

    def test_index_dry_run_document_indexing_json_has_next_action(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "vault",
                "--dry-run",
                "--json",
            ],
        )

        assert result.exit_code == 2
        envelope = typing.cast("dict[str, object]", json.loads(result.output))
        assert envelope["ok"] is False
        assert envelope["command"] == "index"
        assert envelope["error"] == "dry_run_requires_supported_type"
        assert envelope["message"] == (
            "Dry run is available for code and document indexing."
        )
        assert envelope["remediation"] == [
            "vaultspec-rag index --type code --dry-run",
            "vaultspec-rag index --type document --dry-run",
        ]

    def test_index_dry_run_human_output_is_bounded(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        for name in ("alpha.py", "beta.py", "gamma.py"):
            (tmp_path / name).write_text("print('indexed')\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--dry-run",
                "--dry-run-limit",
                "2",
            ],
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert lines[0] == "Dry run: 3 source-code files would be indexed."
        assert "Admission summary:" in lines
        assert "Files shown:" in lines
        assert "- alpha.py" in lines
        assert "- beta.py" in lines
        assert lines[-1] == (
            "1 more file not shown. Use --dry-run-limit 3 or --json for the full list."
        )
        assert "gamma.py" not in result.output

    def test_index_dry_run_json_keeps_full_file_list(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        for name in ("alpha.py", "beta.py", "gamma.py"):
            (tmp_path / name).write_text("print('indexed')\n", encoding="utf-8")

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--dry-run",
                "--dry-run-limit",
                "1",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        envelope = typing.cast("dict[str, object]", json.loads(result.output))
        assert envelope["ok"] is True
        data_raw = envelope["data"]
        assert isinstance(data_raw, dict)
        data = typing.cast("dict[str, object]", data_raw)
        raw_files = data["files"]
        assert isinstance(raw_files, list)
        files = set(typing.cast("list[str]", raw_files))
        assert files == {"alpha.py", "beta.py", "gamma.py"}

    def test_index_dry_run_rejects_negative_limit(self, tmp_path: Path) -> None:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--dry-run",
                "--dry-run-limit",
                "-1",
            ],
        )

        assert result.exit_code == 2
        lines = _plain_lines(result.output)
        assert lines == [
            "Dry-run file limit must be zero or greater.",
            "Run:",
            "vaultspec-rag index --type code --dry-run --dry-run-limit 50",
        ]

    def test_index_rebuild_without_explicit_type_exits_2(self, tmp_path: Path):
        """--rebuild without --type is rejected.

        The audit found --rebuild silently inherited --type all from the
        default and the in-process branch destroyed both collections.
        Require explicit --type when --rebuild is set; bare `index` stays
        frictionless.
        """
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--rebuild"],
        )
        assert result.exit_code == 2
        assert "explicit --type" in result.output

    def test_index_rebuild_without_explicit_type_json_envelope(
        self,
        tmp_path: Path,
    ):
        """The same guard surfaces a rebuild_requires_explicit_type envelope."""
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--rebuild", "--json"],
        )
        assert result.exit_code == 2
        env = typing.cast("dict[str, object]", json.loads(result.output.strip()))
        assert env["ok"] is False
        assert env["command"] == "index"
        assert env["error"] == "rebuild_requires_explicit_type"
        # Remediation lists the three valid forms.
        raw_rem = env["remediation"]
        assert isinstance(raw_rem, list)
        rem = typing.cast("list[str]", raw_rem)
        assert any("--type vault" in r for r in rem)
        assert any("--type code" in r for r in rem)
        assert any("--type all" in r for r in rem)

    def test_index_bare_invocation_still_works(self, tmp_path: Path):
        """Bare `vaultspec-rag index` (no --rebuild) keeps the all default.

        Cannot fully exercise the indexers without a GPU + corpus, but the
        guard must not fire on this canonical quick-start invocation. We
        invoke with --dry-run (codebase-only path that short-circuits
        before the guard) to confirm the daily-driver pattern lands in
        the dry-run branch and does not hit the guard.
        """
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--dry-run"],
        )
        # Dry-run with default --type all picks up code only and exits
        # cleanly. The new --rebuild guard must NOT have been triggered.
        assert "explicit --type" not in result.output
        assert result.exit_code == 0, result.output


class TestCleanRequiredTarget:
    """Clean target is required (no default)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_clean_no_target_errors(self, tmp_path: Path):
        """`vaultspec-rag clean` without a target exits non-zero."""
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "clean"],
        )
        # Typer surfaces missing required argument with exit code 2
        # and "Missing argument" in stderr.
        assert result.exit_code != 0


class TestIndexSummaryCLI:
    """Human index summaries are covered through the CLI command surface."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_index_all_renders_service_summary_from_http_response(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        (tmp_path / ".vaultspec").mkdir()
        requests: list[dict[str, object]] = []

        class _IndexServiceHandler(QuietHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = _parsed_json_object(self.rfile.read(length))
                requests.append(body)

                response = {
                    "ok": True,
                    "partial": False,
                    "status": "queued",
                    "domains": {
                        source: {
                            "ok": True,
                            "job_id": f"{source}-job",
                            "error_kind": None,
                            "detail": None,
                            "outcome": {"status": "created"},
                        }
                        for source in ("vault", "code", "document")
                    },
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

        server = http.server.HTTPServer(("127.0.0.1", 0), _IndexServiceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "index",
                    "--type",
                    "all",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert [req["type"] for req in requests] == ["combined"]
        assert {req["project_root"] for req in requests} == {str(tmp_path)}
        assert {req["initiator_kind"] for req in requests} == {"cli"}
        assert {req["clean"] for req in requests} == {False}

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Vault re-index job queued on service: vault-job",
            "Source code re-index job queued on service: code-job",
            "Documents re-index job queued on service: document-job",
            "Check progress with: vaultspec-rag server jobs",
        ]

    def test_index_all_handles_sparse_service_summary_without_unknown_text(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        (tmp_path / ".vaultspec").mkdir()
        requests: list[dict[str, object]] = []

        class SparseIndexServiceHandler(QuietHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = _parsed_json_object(self.rfile.read(length))
                requests.append(body)

                response: dict[str, object] = {
                    "ok": False,
                    "partial": True,
                    "status": "partial",
                    "domains": {
                        "vault": {
                            "ok": False,
                            "job_id": None,
                            "error_kind": "busy",
                            "detail": "vault busy",
                            "outcome": None,
                        },
                        "code": {
                            "ok": True,
                            "job_id": "code-job",
                            "error_kind": None,
                            "detail": None,
                            "outcome": {"status": "created"},
                        },
                        "document": {
                            "ok": False,
                            "job_id": None,
                            "error_kind": "busy",
                            "detail": "document busy",
                            "outcome": None,
                        },
                    },
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

        server = http.server.HTTPServer(("127.0.0.1", 0), SparseIndexServiceHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "index",
                    "--type",
                    "all",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert [req["type"] for req in requests] == ["combined"]

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Vault: failed: busy: vault busy",
            "Source code re-index job queued on service: code-job",
            "Documents: failed: busy: document busy",
            "Check progress with: vaultspec-rag server jobs",
        ]

    def test_index_summary_spells_out_reported_durations(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._index import _print_index_summary

        _print_index_summary(
            [
                {
                    "source": "vault",
                    "added": 1,
                    "updated": 0,
                    "removed": 0,
                    "total": 1,
                    "duration_ms": 1000,
                },
                {
                    "source": "codebase",
                    "added": 0,
                    "updated": 1,
                    "removed": 0,
                    "total": 1,
                    "duration_ms": 1500,
                },
                {
                    "source": "vault",
                    "added": 0,
                    "updated": 0,
                    "removed": 1,
                    "total": 0,
                    "duration_ms": 10_000,
                },
            ],
            via="service",
        )

        lines = _plain_lines(capsys.readouterr().out)
        assert lines[1].endswith("finished in 1 second")
        assert lines[2].endswith("finished in 1.5 seconds")
        assert lines[3].endswith("finished in 10 seconds")
        assert not any("ms" in line for line in lines)

    def test_index_summary_humanizes_missing_source_label(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._index import _print_index_summary

        _print_index_summary(
            [{"added": 1, "updated": 2, "removed": 0, "total": 3}],
            via="service",
        )

        lines = _plain_lines(capsys.readouterr().out)
        assert lines[0] == "Indexing summary: ran in running service."
        joined = " ".join(lines[1:])
        assert "Index source not reported:" in joined
        assert "added 1; updated 2; removed 0; total 3" in joined
        assert "duration not reported" in joined
        assert "not_reported" not in joined


class TestAutoDelegation:
    """Verify CLI search and index auto-detect and delegate to a running service."""

    @staticmethod
    def _run_resolution_probe(tmp_path: Path, mode: str) -> dict[str, object]:
        """Run real discovery, search, and index routing in a fresh interpreter."""
        import subprocess
        import sys

        code = r"""
import http.server
import json
import os
import socket
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path

root = Path(sys.argv[1])
mode = sys.argv[2]
target = root / "project"
status_dir = root / "status"
storage_dir = root / "qdrant-server" / "storage"
target.mkdir(parents=True)
(target / ".vaultspec").mkdir()
status_dir.mkdir()

os.environ["VAULTSPEC_RAG_STATUS_DIR"] = str(status_dir)
os.environ["VAULTSPEC_RAG_QDRANT_STORAGE_DIR"] = str(storage_dir)
os.environ.pop("VAULTSPEC_RAG_LOCAL_ONLY", None)

from vaultspec_rag.config._settings import reset_config  # absolute-import-ok

reset_config()


from vaultspec_rag._machine_lock import (  # absolute-import-ok
    acquire_machine_lock,
    machine_discovery_path,
    release_machine_lock,
)
from vaultspec_rag.serviceclient._compat import (  # absolute-import-ok
    SERVICE_VERSION_FIELD,
    local_package_version,
)

requests = []


class CaptureHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        requests.append({"path": self.path, "body": body})
        if self.path == "/search":
            payload = {"ok": True, "results": []}
            status = 200
        elif self.path == "/reindex":
            payload = {"ok": True, "job_id": "isolated-vault-job"}
            status = 200
        else:
            payload = {"ok": False, "error": "unexpected_endpoint"}
            status = 404
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        _ = format, args


capture_server = http.server.HTTPServer(("127.0.0.1", 0), CaptureHandler)
capture_thread = threading.Thread(target=capture_server.serve_forever, daemon=True)
nonselected_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
machine_lock_acquired = False
capture_thread_started = False

try:
    nonselected_socket.bind(("127.0.0.1", 0))
    capture_port = int(capture_server.server_address[1])
    nonselected_port = int(nonselected_socket.getsockname()[1])
    assert capture_port != nonselected_port

    if mode == "machine":
        machine_port = capture_port
        fallback_port = nonselected_port
    elif mode == "fallback":
        machine_port = nonselected_port
        fallback_port = capture_port
    else:
        raise AssertionError(f"unknown probe mode: {mode}")

    (status_dir / "service.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "port": fallback_port,
                "service_token": "fallback-token",
                SERVICE_VERSION_FIELD: local_package_version(),
            }
        ),
        encoding="utf-8",
    )

    if mode == "machine":
        machine_lock_acquired, holder = acquire_machine_lock()
        assert machine_lock_acquired, holder
        pointer = machine_discovery_path()
        pointer.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": machine_port,
                    "service_token": "machine-token",
                    "last_heartbeat": datetime.now(UTC).isoformat(timespec="seconds"),
                    "stale_after_s": 60,
                    SERVICE_VERSION_FIELD: local_package_version(),
                }
            ),
            encoding="utf-8",
        )

    capture_thread.start()
    capture_thread_started = True
    expected = machine_port if mode == "machine" else fallback_port
    initial_target_tree = sorted(
        str(path.relative_to(target)) for path in target.rglob("*")
    )
    assert initial_target_tree == [".vaultspec"]

    from vaultspec_rag.cli._index import (  # absolute-import-ok
        resolve_data_plane_service as index_resolve,
    )
    from vaultspec_rag.cli._search import (  # absolute-import-ok
        resolve_data_plane_service as search_resolve,
    )

    assert search_resolve().port == expected
    assert index_resolve().port == expected

    from typer.testing import CliRunner
    from vaultspec_rag.cli import app  # absolute-import-ok

    runner = CliRunner()
    search_result = runner.invoke(
        app,
        [
            "--target",
            str(target),
            "search",
            "anything",
            "--type",
            "code",
            "--json",
        ],
    )
    search_envelope = json.loads(search_result.output)
    assert search_result.exit_code == 0, search_result.output
    assert search_envelope["command"] == "search", search_envelope
    assert search_envelope["data"]["via"] == "service", search_envelope

    index_result = runner.invoke(
        app,
        [
            "--target",
            str(target),
            "index",
            "--type",
            "vault",
            "--json",
        ],
    )
    index_envelope = json.loads(index_result.output)
    assert index_result.exit_code == 0, index_result.output
    assert index_envelope["command"] == "index", index_envelope
    assert index_envelope["data"] == {
        "via": "service",
        "source": "vault",
        "outcome": {"ok": True, "job_id": "isolated-vault-job"},
    }, index_envelope

    assert requests == [
        {
            "path": "/search",
            "body": {
                "query": "anything",
                "top_k": 10,
                "project_root": str(target),
                "type": "code",
            },
        },
        {
            "path": "/reindex",
            "body": {
                "type": "vault",
                "clean": False,
                "project_root": str(target),
                "initiator_kind": "cli",
            },
        },
    ], requests

    forbidden = (
        "torch",
        "sentence_transformers",
        "qdrant_client",
        "transformers",
        "onnxruntime",
    )
    heavy = sorted(
        module
        for module in sys.modules
        if any(module == name or module.startswith(name + ".") for name in forbidden)
    )
    assert not heavy, heavy
    final_target_tree = sorted(
        str(path.relative_to(target)) for path in target.rglob("*")
    )
    assert final_target_tree == initial_target_tree, final_target_tree
    print(
        json.dumps(
            {
                "mode": mode,
                "expected": expected,
                "machine_port": machine_port,
                "fallback_port": fallback_port,
                "capture_port": capture_port,
                "requests": requests,
                "search_via": search_envelope["data"]["via"],
                "index_via": index_envelope["data"]["via"],
                "heavy": heavy,
                "target_tree": final_target_tree,
            }
        )
    )
finally:
    if machine_lock_acquired:
        release_machine_lock()
    if capture_thread_started:
        capture_server.shutdown()
    capture_server.server_close()
    if capture_thread_started:
        capture_thread.join(timeout=5)
        assert not capture_thread.is_alive()
    nonselected_socket.close()
"""
        result = subprocess.run(
            [sys.executable, "-c", code, str(tmp_path), mode],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        return typing.cast("dict[str, object]", json.loads(result.stdout))

    @staticmethod
    def _assert_real_cli_routes(
        tmp_path: Path,
        evidence: dict[str, object],
    ) -> None:
        """Require both commands to use the selected real service endpoint."""
        assert evidence["capture_port"] == evidence["expected"]
        assert evidence["search_via"] == "service"
        assert evidence["index_via"] == "service"
        assert evidence["heavy"] == []
        assert evidence["target_tree"] == [".vaultspec"]
        requests = typing.cast("list[dict[str, object]]", evidence["requests"])
        assert [request["path"] for request in requests] == ["/search", "/reindex"]
        reindex = typing.cast("dict[str, object]", requests[1]["body"])
        assert reindex == {
            "type": "vault",
            "clean": False,
            "project_root": str(tmp_path / "project"),
            "initiator_kind": "cli",
        }

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_auto_delegates_when_service_running(self, tmp_path: Path) -> None:
        """A discovered, live daemon takes the search rather than the local path.

        Discovery is real end to end: a status record naming this process and a
        real port, a bound server answering /health with the token that record
        publishes, and the production identity check comparing the two. The
        substituted version asserted the CLI called a function someone replaced,
        which could not notice discovery moving - the sibling locked-store tests
        failed on exactly that, patching a symbol that had been relocated.

        Proven able to fail: removing the service record leaves nothing to
        discover, the CLI keeps the search local, and the request log stays
        empty (0 == 1).

        What this does NOT bind, checked rather than assumed: publishing a
        token the health server never serves still delegates. So the identity
        comparison is not exercised on this path, and claiming otherwise here
        would be a guard test asserting a branch it never reaches. That
        comparison has its own real coverage in the service-identity tests,
        which drive it against a bound /health and this process's own pid.
        """
        from ._cli_helpers import (
            _running_service_record,
            _search_output_contract_server,
        )

        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            port = server.server_address[1]
            with _running_service_record(tmp_path / "status", port):
                runner.invoke(
                    app,
                    ["--target", str(tmp_path), "search", "anything"],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert len(requests) == 1

    def test_index_auto_delegates_when_service_running(self, tmp_path: Path) -> None:
        """A discovered, live daemon takes the index rather than running locally.

        Same real discovery as the search case: a status record naming this
        process and a real port, and a bound server that records what it was
        asked to do. The substituted version asserted the CLI called a function
        someone replaced, which could not notice discovery moving.

        Proven able to fail: removing the service record leaves nothing to
        discover, the CLI indexes locally, and the request log stays empty.
        """
        from ._cli_helpers import _reindex_contract_server, _running_service_record

        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _reindex_contract_server()
        try:
            port = server.server_address[1]
            with _running_service_record(tmp_path / "status", port):
                runner.invoke(
                    app,
                    ["--target", str(tmp_path), "index", "--type", "vault"],
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert len(requests) == 1
        assert requests[0].get("type") == "vault"
        assert requests[0].get("initiator_kind") == "cli"

    def test_auto_delegation_prefers_machine_global_resolution(
        self, tmp_path: Path
    ) -> None:
        """A valid machine-global service outranks a conflicting status hint."""
        evidence = self._run_resolution_probe(tmp_path, "machine")
        self._assert_real_cli_routes(tmp_path, evidence)
        assert evidence["expected"] == evidence["machine_port"]
        assert evidence["expected"] != evidence["fallback_port"]

    def test_auto_delegation_uses_status_fallback_without_machine_service(
        self, tmp_path: Path
    ) -> None:
        """The real status file is used only when machine resolution is absent."""
        evidence = self._run_resolution_probe(tmp_path, "fallback")
        self._assert_real_cli_routes(tmp_path, evidence)
        assert evidence["expected"] == evidence["fallback_port"]
        assert evidence["expected"] != evidence["machine_port"]


# Larger than the free space on any volume a test can run against, so the
# store's own headroom check refuses rather than a rehearsed verdict standing
# in for it.
_UNSATISFIABLE_FLOOR_BYTES = 1 << 60


def _index_refused_by_the_real_disk_preflight(
    storage_path: Path,
) -> Callable[..., object]:
    """Return an index entry point that fails the production headroom check.

    The in-process index cannot be driven to a genuine out-of-disk condition
    from a unit test: reaching the preflight means loading the models and
    filling the store volume first. So the refusal is raised by the store's
    own ``ensure_disk_headroom`` against a floor no volume satisfies - the
    exception class, the classification, and the operator wording are all
    production's, and what the tests below bind is what the CLI does with
    them rather than anything written here.
    """
    from .._store_writes import ensure_disk_headroom

    def _index(*_args: object, **_kwargs: object) -> object:
        ensure_disk_headroom(storage_path, floor_bytes=_UNSATISFIABLE_FLOOR_BYTES)
        raise AssertionError(
            "the disk preflight accepted a floor no volume can satisfy"
        )

    return _index


@pytest.fixture
def project_refused_by_the_disk_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """A project whose in-process index run fails the real disk preflight.

    One trigger site shared by both refusal tests rather than one apiece. The
    setup is identical for the two, and this is the only place in this file
    that stands anything in for production, so duplicating it would have
    doubled that surface to say the same thing twice.
    """
    project = tmp_path / "project"
    (project / ".vaultspec").mkdir(parents=True)
    monkeypatch.setattr(
        "vaultspec_rag.index",
        _index_refused_by_the_real_disk_preflight(project),
    )
    return project


@pytest.mark.usefixtures("isolated_singleton_dirs")
class TestDiskPreflightRefusal:
    """The in-process index path surfaces a disk-preflight refusal as one
    structured non-zero envelope - never the GPU-error diagnosis.

    The in-process path is reached the way an operator reaches it: the
    singleton dirs are isolated and empty, so real discovery finds no daemon
    to delegate to. Nothing rehearses that verdict.
    """

    def test_json_mode_emits_disk_preflight_failed(
        self,
        project_refused_by_the_disk_preflight: Path,
    ) -> None:
        """A refused preflight is one classified envelope, exit 1.

        The real progress rendering runs; its stream is pointed at a buffer
        because Rich interleaves cursor control bytes with the envelope on
        stdout and this test parses that envelope. The reporter itself is
        the production one, built by the production call site from the
        console it reads at call time.

        Proven able to fail: deleting the ``except InsufficientDiskSpaceError``
        branch in the in-process index path drops the refusal into the
        ``(ImportError, RuntimeError)`` GPU handler, and the
        ``disk_preflight_failed`` assertion fails on a GPU diagnosis;
        restoring the branch passes.
        """

        project = project_refused_by_the_disk_preflight
        result = runner.invoke(
            app,
            ["--target", str(project), "index", "--type", "vault", "--json"],
        )
        assert result.exit_code == 1
        # No console redirect: a --json run reports no progress at all, so
        # stdout carries the envelope and nothing else. Before that, this had
        # to redirect the console to keep the progress lines out of the result
        # channel, which hid the fact that they were being written there.
        assert result.output.lstrip().startswith("{"), (
            "--json must answer with one envelope on every exit path, "
            f"got: {result.output!r}"
        )
        payload = typing.cast("dict[str, object]", json.loads(result.output))
        assert payload["ok"] is False
        assert payload["error"] == "disk_preflight_failed"
        assert "disk space" in str(payload["message"])
        remediation = typing.cast("list[str]", payload["remediation"])
        assert any("storage survey" in r for r in remediation)

    def test_human_mode_prints_the_refusal(
        self,
        project_refused_by_the_disk_preflight: Path,
    ) -> None:
        """Human mode prints the store's own wording, exit 1.

        Proven able to fail: replacing the refusal's ``_plain(f"Error: {exc}")``
        with a bare ``_plain("Error")`` fails the assertion below; restoring
        it passes.

        What this does NOT bind, checked rather than assumed: deleting the
        dedicated disk branch entirely still passes here, because on a host
        whose torch and GPU are both healthy the GPU handler's fallback
        prints the same ``Error: {exc}`` line. Human text cannot tell the two
        apart, so the classification is bound by the ``--json`` sibling and
        this test binds only the wording that reaches the operator.
        """
        project = project_refused_by_the_disk_preflight
        result = runner.invoke(
            app,
            ["--target", str(project), "index", "--type", "vault"],
        )
        assert result.exit_code == 1
        assert "not enough free disk space" in " ".join(_plain_lines(result.output))
