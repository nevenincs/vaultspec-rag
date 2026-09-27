"""CLI rendering of service index summaries."""

from __future__ import annotations

import http.server
import json
import threading
import typing

import pytest

from ._cli_helpers import (
    _parsed_json_object,
    _plain_lines,
    app,
    runner,
)
from ._http_stubs import QuietHandler

if typing.TYPE_CHECKING:
    from pathlib import Path

    from typer.testing import Result

pytestmark = [pytest.mark.unit]


def _run_index_against_service(
    target: Path,
    handler: type[http.server.BaseHTTPRequestHandler],
    source_type: str,
    *,
    rebuild: bool = False,
    join_timeout: float = 1.0,
) -> Result:
    """Run one index command against a real loopback HTTP stub."""
    (target / ".vaultspec").mkdir()
    server = http.server.HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    args = ["--target", str(target), "index", "--type", source_type]
    if rebuild:
        args.append("--rebuild")
    args.extend(["--port", str(server.server_port)])
    try:
        return runner.invoke(app, args)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=join_timeout)


class TestIndexSummaryCLI:
    """Human index summaries are covered through the CLI command surface."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_index_all_renders_service_summary_from_http_response(
        self, tmp_path: Path
    ) -> None:
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

        result = _run_index_against_service(
            tmp_path,
            _IndexServiceHandler,
            "combined",
        )

        assert result.exit_code == 0, result.output
        assert [req["type"] for req in requests] == ["combined"]
        assert {req["project_root"] for req in requests} == {str(tmp_path)}
        assert {req["initiator_kind"] for req in requests} == {"cli"}
        assert {req["clean"] for req in requests} == {False}
        assert {req["authority"] for req in requests} == {"publication"}

        lines = [line.strip() for line in result.output.splitlines() if line.strip()]
        assert lines == [
            "Vault re-index job queued on service: vault-job",
            "Source code re-index job queued on service: code-job",
            "Documents re-index job queued on service: document-job",
            "Check progress with: vaultspec-rag server jobs",
        ]

    def test_index_rebuild_delegates_with_explicit_rebuild_authority(
        self, tmp_path: Path
    ) -> None:
        """The CLI must not rely on the reindex route to infer full-work consent."""
        requests: list[dict[str, object]] = []

        class _RebuildServiceHandler(QuietHandler):
            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                requests.append(_parsed_json_object(self.rfile.read(length)))
                response = {
                    "ok": True,
                    "job_id": "code-rebuild-job",
                    "status": "queued",
                }
                encoded = json.dumps(response).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

        result = _run_index_against_service(
            tmp_path,
            _RebuildServiceHandler,
            "code",
            rebuild=True,
            join_timeout=5.0,
        )

        assert result.exit_code == 0, result.output
        assert requests == [
            {
                "type": "code",
                "clean": True,
                "authority": "rebuild",
                "project_root": str(tmp_path),
                "initiator_kind": "cli",
            }
        ]

    def test_index_all_handles_sparse_service_summary_without_unknown_text(
        self, tmp_path: Path
    ) -> None:
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

        result = _run_index_against_service(
            tmp_path,
            SparseIndexServiceHandler,
            "combined",
        )

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
