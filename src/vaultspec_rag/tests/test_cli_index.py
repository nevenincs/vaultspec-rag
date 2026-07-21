"""CLI coverage for index, clean, and auto-delegation commands."""

from __future__ import annotations

import json
import typing

import pytest

from ._cli_helpers import (
    _hold_local_index_lock,
    _plain_lines,
    app,
    runner,
)

if typing.TYPE_CHECKING:
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

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        return tmp_path

    def test_clean_help_renders(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0
        assert "wipe" in result.output.lower()

    def test_clean_confirm_prompt_uses_search_index_language(self, tmp_path: Path):
        root = self._workspace(tmp_path)
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
        root = self._workspace(tmp_path)
        result = runner.invoke(
            app,
            ["--target", str(root), "clean", "vault"],
        )

        assert result.exit_code == 1
        assert "Clean cancelled." in result.output
        assert "Aborted!" not in result.output

    def test_clean_all_clears_collections_and_metadata(self, tmp_path: Path):
        from ..config import get_config
        from ..store import VaultStore

        root = self._workspace(tmp_path)
        cfg = get_config()
        data_dir = root / cfg.data_dir
        data_dir.mkdir(parents=True)
        (data_dir / cfg.index_metadata_file).write_text('{"x": "y"}', encoding="utf-8")
        (data_dir / cfg.code_index_metadata_file).write_text(
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
        assert not (data_dir / cfg.index_metadata_file).exists()
        assert not (data_dir / cfg.code_index_metadata_file).exists()

    def test_clean_lock_error_uses_operator_language(self, tmp_path: Path) -> None:
        root = self._workspace(tmp_path)
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
            "Dry run is available for source-code indexing only.",
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
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "index"
        assert envelope["error"] == "dry_run_requires_code"
        assert (
            envelope["message"] == "Dry run is available for source-code indexing only."
        )
        assert envelope["remediation"] == ["vaultspec-rag index --type code --dry-run"]

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
        assert lines == [
            "Dry run: 3 source-code files would be indexed.",
            "Files shown:",
            "- alpha.py",
            "- beta.py",
            (
                "1 more file not shown. Use --dry-run-limit 3 "
                "or --json for the full list."
            ),
        ]
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
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        files = set(envelope["data"]["files"])
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
        env = json.loads(result.output.strip())
        assert env["ok"] is False
        assert env["command"] == "index"
        assert env["error"] == "rebuild_requires_explicit_type"
        # Remediation lists the three valid forms.
        rem = env["remediation"]
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

        class _IndexServiceHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                requests.append(body)

                response_by_type = {
                    "vault": {
                        "ok": True,
                        "added": 1,
                        "updated": 2,
                        "removed": 3,
                        "total": 6,
                        "duration_ms": 1234,
                    },
                    "codebase": {
                        "ok": True,
                        "added": "4",
                        "updated": "5",
                        "removed": "6",
                        "total": "15",
                        "duration_ms": "50",
                    },
                }
                response = response_by_type.get(
                    body.get("type"),
                    {"ok": False, "error": "unexpected_type"},
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

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
        assert [req["type"] for req in requests] == ["vault", "codebase"]
        assert {req["project_root"] for req in requests} == {str(tmp_path)}
        assert {req["initiator_kind"] for req in requests} == {"cli"}
        assert {req["clean"] for req in requests} == {False}

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Indexing summary: ran in running service.",
            "Vault: added 1; updated 2; removed 3; total 6; finished in 1.2 seconds",
            (
                "Source code: added 4; updated 5; removed 6; total 15; "
                "finished in 50 milliseconds"
            ),
        ]

    def test_index_all_handles_sparse_service_summary_without_unknown_text(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        (tmp_path / ".vaultspec").mkdir()
        requests: list[dict[str, object]] = []

        class SparseIndexServiceHandler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                requests.append(body)

                response_by_type: dict[str, dict[str, object]] = {
                    "vault": {
                        "ok": True,
                        "added": "not-a-number",
                        "updated": "2",
                        "removed": None,
                        "total": [],
                        "duration_ms": "not-a-duration",
                    },
                    "codebase": {
                        "ok": True,
                        "added": "4",
                        "updated": "5",
                        "removed": "6",
                        "total": "15",
                        "duration_ms": "50",
                    },
                }
                response = response_by_type.get(
                    body.get("type"),
                    {"ok": False, "error": "unexpected_type"},
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

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
        assert [req["type"] for req in requests] == ["vault", "codebase"]

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Indexing summary: ran in running service.",
            "Vault: added 0; updated 2; removed 0; total 0; duration not reported",
            (
                "Source code: added 4; updated 5; removed 6; total 15; "
                "finished in 50 milliseconds"
            ),
        ]
        assert "unknown" not in result.output.lower()
        assert "finished in not reported" not in result.output.lower()

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

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_auto_delegates_when_service_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If service is running, search auto-delegates to it."""
        (tmp_path / ".vaultspec").mkdir()

        def _stub_read_status() -> dict[str, object]:
            return {"pid": 12345, "port": 8766, "service_token": "token123"}

        def _stub_is_our_service_search(
            _pid: int, _port: int, _expected_token: str | None
        ) -> bool:
            return True

        # Stub _read_service_status to return active port and pid.
        # _default_service_port reads through the serviceclient discovery
        # module after the service-client factoring, so patch it there.
        monkeypatch.setattr(
            "vaultspec_rag.serviceclient._discovery._read_service_status",
            _stub_read_status,
        )
        # Mock _is_our_service to return True
        monkeypatch.setattr(
            "vaultspec_rag.cli._is_our_service",
            _stub_is_our_service_search,
        )

        # Mock _try_http_search to return dummy results (so we know it got called)
        called: list[int] = []

        def mock_try_search(*args: object, **_kwargs: object) -> dict[str, object]:
            # args: query, search_type, max_results, port, target
            called.append(int(typing.cast("str | int", args[3])))
            return {"ok": True, "results": []}

        monkeypatch.setattr(
            "vaultspec_rag.cli._search._try_http_search", mock_try_search
        )

        runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
            ],
        )
        assert len(called) == 1
        assert called[0] == 8766

    def test_index_auto_delegates_when_service_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If service is running, index auto-delegates to it."""
        (tmp_path / ".vaultspec").mkdir()

        def _stub_read_status_idx() -> dict[str, object]:
            return {"pid": 12345, "port": 8766, "service_token": "token123"}

        def _stub_is_our_service_idx(
            _pid: int, _port: int, _expected_token: str | None
        ) -> bool:
            return True

        monkeypatch.setattr(
            "vaultspec_rag.serviceclient._discovery._read_service_status",
            _stub_read_status_idx,
        )
        monkeypatch.setattr(
            "vaultspec_rag.cli._is_our_service",
            _stub_is_our_service_idx,
        )

        called: list[tuple[str, int]] = []

        def mock_try_reindex(
            tool_name: str, _rebuild: bool, port: int, _target: str
        ) -> dict[str, object]:
            called.append((tool_name, port))
            return {
                "ok": True,
                "added": 1,
                "updated": 0,
                "removed": 0,
                "total": 1,
                "duration_ms": 10,
            }

        monkeypatch.setattr(
            "vaultspec_rag.cli._index._try_http_reindex", mock_try_reindex
        )

        runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "vault",
            ],
        )
        assert len(called) == 1
        assert called[0] == ("reindex_vault", 8766)


class TestDiskPreflightRefusal:
    """The in-process index path surfaces a disk-preflight refusal as one
    structured non-zero envelope - never the GPU-error diagnosis."""

    def test_json_mode_emits_disk_preflight_failed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from .._store_writes import InsufficientDiskSpaceError

        (tmp_path / ".vaultspec").mkdir()
        monkeypatch.setattr(
            "vaultspec_rag.cli._index._default_service_port", lambda: None
        )

        def _raise_preflight(*_args: object, **_kwargs: object) -> object:
            msg = (
                "not enough free disk space for the vector store "
                "(No space left on device imminent)"
            )
            raise InsufficientDiskSpaceError(msg)

        monkeypatch.setattr("vaultspec_rag.index", _raise_preflight)

        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--type", "vault", "--json"],
        )
        assert result.exit_code == 1
        # The progress reporter writes platform-dependent rendering
        # (control sequences, brace-bearing bar text) before the
        # envelope; strip control characters and anchor on the
        # envelope's own opening tokens, which are always last.
        cleaned = "".join(ch for ch in result.output if ch >= " ")
        decoded, _ = json.JSONDecoder().raw_decode(
            cleaned, cleaned.rindex('{"ok"')
        )
        payload = typing.cast("dict[str, object]", decoded)
        assert payload["ok"] is False
        assert payload["error"] == "disk_preflight_failed"
        assert "disk space" in payload["message"]
        assert any("storage survey" in r for r in payload["remediation"])

    def test_human_mode_prints_the_refusal(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from .._store_writes import InsufficientDiskSpaceError

        (tmp_path / ".vaultspec").mkdir()
        monkeypatch.setattr(
            "vaultspec_rag.cli._index._default_service_port", lambda: None
        )

        def _raise_preflight(*_args: object, **_kwargs: object) -> object:
            raise InsufficientDiskSpaceError("not enough free disk space")

        monkeypatch.setattr("vaultspec_rag.index", _raise_preflight)

        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--type", "vault"],
        )
        assert result.exit_code == 1
        assert "not enough free disk space" in " ".join(_plain_lines(result.output))
