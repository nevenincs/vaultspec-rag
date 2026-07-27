"""CLI coverage for the search service-safety and fallback contract."""

from __future__ import annotations

import json
import os
import re
import typing

import pytest

from ._cli_helpers import (
    _assert_no_table_borders,
    _assert_record,
    _empty_search_contract_server,
    _expected_code_search_request,
    _invoke_search_contract,
    _label_values,
    _plain_lines,
    _search_output_contract_server,
    _search_records,
    _slow_search_contract_server,
    _sparse_search_output_contract_server,
    _store_locked_by_another_process,
    app,
    runner,
)

if typing.TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestSearchSafetyContract:
    """Fail-hard fast path + path indicator + tqdm suppression."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_port_dead_default_fails_hard(self, tmp_path: Path):
        """--port unreachable + no --allow-fallback exits non-zero."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--limit",
                "3",
                "--port",
                "1",
            ],
        )
        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "unreachable" in normalized.lower()
        assert "allow-fallback" in normalized.lower()
        assert "local search index" in normalized
        assert "one user only" in normalized
        assert "agents waiting" not in normalized
        assert "single-agent" not in normalized
        assert "Qdrant lock" not in normalized
        assert "in-process" not in normalized

    def test_search_port_dead_with_allow_fallback_no_warning(self, tmp_path: Path):
        """--allow-fallback does NOT emit the legacy fallthrough warning."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--port",
                "1",
                "--allow-fallback",
            ],
        )
        normalized = " ".join(result.output.split())
        assert "falling back to in-process" not in normalized

    def test_index_exclude_warning_uses_running_service_language(self, tmp_path: Path):
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--port",
                "1",
                "--exclude",
                "temp.py",
            ],
        )

        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "--exclude is ignored when using the running service." in normalized
        assert "RAG service" not in normalized

    def test_search_command_renders_numbered_results_from_http_response(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == [_expected_code_search_request(tmp_path, "service status")]
        records = _search_records(result.output)
        assert [record["number"] for record in records] == [1, 2]
        _assert_record(
            records[0],
            number=1,
            location="src/search_ui.py:12",
            text="def render_search_results():\nreturn 'full service text'",
        )
        _assert_record(
            records[1],
            number=2,
            location="docs/ops.md#service-status",
            text="Use server status for service readiness and current work.",
        )
        lines = _plain_lines(result.output)
        assert lines[0] == "1. src/search_ui.py:12"
        assert lines[1] == "def render_search_results():"
        assert lines[2] == "return 'full service text'"
        assert " - " not in lines[0]
        _assert_no_table_borders(result.output)

    def test_search_structure_filter_sends_service_node_type(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(
                tmp_path,
                server.server_port,
                "--structure",
                "function",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        expected = _expected_code_search_request(tmp_path, "service status")
        expected["node_type"] = "function"
        assert requests == [expected]
        assert "--node-type" not in result.output

    def test_search_prefer_accepts_user_facing_value_alias(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(
                tmp_path,
                server.server_port,
                "--prefer",
                "production",
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        expected = _expected_code_search_request(tmp_path, "service status")
        expected["prefer"] = "prod"
        assert requests == [expected]

    def test_search_command_humanizes_missing_result_location(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _sparse_search_output_contract_server()
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == [_expected_code_search_request(tmp_path, "service status")]
        records = _search_records(result.output)
        _assert_record(
            records[0],
            number=1,
            location="location-not-reported",
            text="result text without a source location",
        )
        assert "<unknown>" not in result.output
        assert "unknown" not in result.output.lower()
        _assert_no_table_borders(result.output)

    def test_search_command_scores_flag_uses_plain_score_label(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, _requests = _search_output_contract_server()
        try:
            result = _invoke_search_contract(tmp_path, server.server_port, "--scores")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        records = _search_records(result.output)
        _assert_record(
            records[0],
            number=1,
            location="src/search_ui.py:12",
            text="def render_search_results():\nreturn 'full service text'",
            score="0.8750",
        )
        _assert_no_table_borders(result.output)

    def test_empty_search_command_humanizes_service_diagnostics(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread, requests = _empty_search_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "missing symbol",
                    "--type",
                    "code",
                    "--limit",
                    "2",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == [_expected_code_search_request(tmp_path, "missing symbol")]
        lines = _plain_lines(result.output)
        assert lines[0].endswith("missing symbol")
        assert lines[1].startswith("Why:")
        assert "No indexed code items are available" in lines[1]
        count_match = re.fullmatch(r"Indexed source code sections: (\d+)\.", lines[2])
        assert count_match is not None
        assert int(count_match.group(1)) == 0
        assert "Project mismatch: requested project differs from indexed project." in (
            lines
        )
        assert "Requested project: current project" in lines
        assert "Indexed project: other project" in lines
        next_actions = lines[lines.index("Next actions:") + 1 :]
        assert next_actions == [
            "- vaultspec-rag index --type code --port 8766",
            "- vaultspec-rag server status",
        ]
        assert "index is for" not in result.output
        assert not any("=" in line for line in lines)

    def test_empty_local_fallback_search_is_actionable(self, tmp_path: Path) -> None:
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "missing local symbol",
                "--type",
                "vault",
                "--limit",
                "1",
                "--port",
                "1",
                "--allow-fallback",
            ],
        )

        assert result.exit_code == 0, result.output
        lines = _plain_lines(result.output)
        assert lines[0].endswith("missing local symbol")
        labels = _label_values(result.output)
        assert labels["Why"].startswith("No matching vault documents")
        assert "local index" in labels["Why"]
        assert labels["Project"] == str(tmp_path)
        next_actions = lines[lines.index("Next actions:") + 1 :]
        assert next_actions == [
            "- vaultspec-rag index --type vault",
            "- vaultspec-rag status",
        ]
        assert "No vault results found" not in result.output
        _assert_no_table_borders(result.output)

    def test_suppress_hf_progress_sets_env(self, monkeypatch: pytest.MonkeyPatch):
        """_suppress_hf_progress sets the HF env vars idempotently."""
        from ..cli._search import _suppress_hf_progress

        monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
        monkeypatch.delenv("TRANSFORMERS_VERBOSITY", raising=False)
        _suppress_hf_progress()
        assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
        assert os.environ["TRANSFORMERS_VERBOSITY"] == "error"

    def test_search_locked_store_raises_actionable_error(self, tmp_path: Path):
        """A store held by another process prints the routing-mode message.

        The lock is real and foreign. A ``VaultStore`` in this interpreter does
        not block a second open - the lock is per process - so a same-process
        holder proves nothing, and substituting the search proved only that the
        renderer can format an exception someone constructed by hand.

        Driving the real condition found a defect the substitution hid: the
        index counts taken before the search also open the store, and they sat
        outside the guard, so a genuinely busy store exited non-zero with no
        output at all and this message never reached the operator it was
        written for.

        Proven able to fail: dropping the holder lets the store open and the
        search returns an ordinary empty result on exit zero.
        """
        (tmp_path / ".vaultspec").mkdir()

        # Search is service-first: the local store is only opened under an
        # explicit local mandate, so --allow-fallback is required to reach the
        # in-process path that surfaces the locked-store message.
        with _store_locked_by_another_process(tmp_path):
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "anything",
                    "--allow-fallback",
                ],
            )
        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "local search index" in normalized
        assert "background service" in normalized
        assert "automatic index update" in normalized
        assert "vaultspec-rag server status" in normalized
        assert "vaultspec-rag server stop" in normalized
        assert "orphaned Python process" in normalized
        assert "server mcp" not in normalized
        assert "MCP" not in normalized
        assert "direct local-store search" not in normalized
        assert "RAG service" not in normalized
        assert "file watcher" not in normalized

    def test_search_locked_store_json_mode(self, tmp_path: Path):
        """A store held by another process reports local_store_locked under --json.

        The lock is real and foreign. A ``VaultStore`` in this interpreter does
        not block a second open - the lock is per process - so a same-process
        holder proves nothing, and substituting the search proved only that the
        renderer can format an exception someone constructed by hand.

        Driving the real condition found a defect the substitution hid: the
        index counts taken before the search also open the store, and they sat
        outside the guard, so a genuinely busy store exited non-zero with no
        output at all and this message never reached the operator it was
        written for.

        Proven able to fail: dropping the holder lets the store open and the
        search returns an ordinary empty result on exit zero.
        """
        (tmp_path / ".vaultspec").mkdir()

        # Search is service-first: the local store is only opened under an
        # explicit local mandate, so --allow-fallback is required to reach the
        # in-process path that surfaces the locked-store message.
        with _store_locked_by_another_process(tmp_path):
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "anything",
                    "--allow-fallback",
                    "--json",
                ],
            )
        assert result.exit_code != 0
        data = json.loads(result.output.strip())
        assert data["ok"] is False
        assert data["error"] == "local_store_locked"
        assert "local search index" in data["message"]
        assert "background service" in data["message"]
        assert "automatic index update" in data["message"]
        remediation = data["remediation"]
        assert "vaultspec-rag server status" in remediation
        assert "vaultspec-rag server stop" in remediation
        assert not any("server mcp" in item.lower() for item in remediation)
        assert "direct local-store search" not in data["message"]
        assert "RAG service" not in data["message"]
        assert "file watcher" not in data["message"]

    def test_search_mcp_timeout_diagnostics(self, tmp_path: Path):
        """A search that outlasts its bound reports http_search_timeout.

        The stall is real: a bound server accepts the request and sleeps past
        the deadline, so the timeout is raised by the transport under test
        rather than by a substitute programmed to raise it. Substituting the
        call proved the caller maps an exception someone constructed, which is
        a different claim from the transport producing one.

        Proven able to fail: raising the timeout above the server's sleep lets
        the request complete and the error is no longer http_search_timeout.
        """
        from ..serviceclient._transport import _try_http_search

        server, thread = _slow_search_contract_server()
        try:
            res = _try_http_search(
                query="test",
                search_type="vault",
                top_k=5,
                port=server.server_address[1],
                project_root=str(tmp_path),
                timeout=0.01,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        assert isinstance(res, dict)
        assert res["ok"] is False
        assert res["error"] == "http_search_timeout"
        msg = res["message"]
        assert isinstance(msg, str)
        assert "timed out after" in msg
        assert "same_project_search_strategy" not in msg

    def test_search_timeout_human_output_is_plain_diagnostic(
        self, tmp_path: Path
    ) -> None:
        """Default search timeout output is natural text, not a backend table."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server()
        port = server.server_address[1]
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "service status jobs logs timeout diagnostics",
                    "--type",
                    "code",
                    "--max-results",
                    "3",
                    "--port",
                    str(port),
                    "--timeout",
                    "0.001",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        labels = _label_values(result.output)
        folded = " ".join(_plain_lines(result.output))
        assert re.match(
            rf"Error: The search request to the service on port {port} "
            r"timed out after 0\.001 seconds",
            folded,
        )
        assert "active index jobs before retrying." in folded
        assert labels["Service"] == "reachable; requests ready; 3 projects loaded"
        assert labels["Work"] == "no active index jobs"
        lines = _plain_lines(result.output)
        next_actions = lines[lines.index("Next actions:") + 1 :]
        assert next_actions == [
            f"- vaultspec-rag server status --port {port}",
            f"- vaultspec-rag server jobs --state active --port {port}",
            "- Rerun the same search with --timeout 300",
        ]
        assert "running jobs before retrying" not in result.output
        assert "running index jobs" not in result.output
        assert "health check" not in result.output
        for forbidden in (
            "same_project_search_strategy",
            "Backend Contract",
            "Search Concurrency",
            "Cross-project Search",
            "Storage Process Model",
            "http_search_timeout",
            "┌",
            "│",
            "└",
        ):
            assert forbidden not in result.output

    def test_search_timeout_missing_health_status_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server(
            health_payload={
                "project_count": 1,
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                },
            }
        )
        port = server.server_address[1]
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "service status jobs logs timeout diagnostics",
                    "--type",
                    "code",
                    "--max-results",
                    "3",
                    "--port",
                    str(port),
                    "--timeout",
                    "0.001",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        labels = _label_values(result.output)
        assert (
            labels["Service"]
            == "reachable; request status not reported by service; 1 project loaded"
        )
        assert labels["Work"] == "no active index jobs"
        assert "unknown" not in result.output.lower()
        _assert_no_table_borders(result.output)

    def test_search_timeout_jobs_error_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server(
            jobs_payload={
                "ok": False,
                "error": "jobs_unavailable",
                "message": "Job summary is not available.",
            },
            jobs_status_code=503,
        )
        port = server.server_address[1]
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "service status jobs logs timeout diagnostics",
                    "--type",
                    "code",
                    "--max-results",
                    "3",
                    "--port",
                    str(port),
                    "--timeout",
                    "0.001",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        labels = _label_values(result.output)
        assert labels["Service"] == "reachable; requests ready; 3 projects loaded"
        assert (
            labels["Work"]
            == "jobs check not reported by service (Job summary is not available.)"
        )
        assert "unknown" not in result.output.lower()
        _assert_no_table_borders(result.output)

    def test_search_timeout_json_preserves_backend_diagnostics(
        self, tmp_path: Path
    ) -> None:
        """JSON timeout output keeps full diagnostic fields for agents."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _slow_search_contract_server()
        port = server.server_address[1]
        try:
            result = runner.invoke(
                app,
                [
                    "--target",
                    str(tmp_path),
                    "search",
                    "service status jobs logs timeout diagnostics",
                    "--type",
                    "code",
                    "--max-results",
                    "3",
                    "--port",
                    str(port),
                    "--timeout",
                    "0.001",
                    "--json",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 1, result.output
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "search"
        assert envelope["error"] == "http_search_timeout"
        assert envelope["backend_capabilities"]["same_project_search_strategy"] == (
            "serialized"
        )
        diagnostics = envelope["diagnostics"]
        assert diagnostics["backpressure"]["same_project_search_strategy"] == (
            "serialized"
        )
        assert diagnostics["health"]["status"] == "ready"
        assert diagnostics["jobs"]["running_count"] == 0


def _shortfall_contract_server(
    *,
    shortfall: dict[str, object] | None,
    results: bool,
    file_shortfall: dict[str, object] | None = None,
) -> tuple[typing.Any, typing.Any]:
    """Start a service returning one code search envelope.

    ``shortfall`` is placed on ``index_state`` exactly as the daemon places it,
    so the CLI under test reads a real wire payload rather than a hand-built
    object, and ``None`` reproduces a complete index.
    """
    import http.server
    import threading

    from ._http_stubs import QuietHandler

    index_state: dict[str, object] = {
        "source": "code",
        "indexed_count": 4,
        "indexed_target_root": "",
        "requested_target_root": "",
        "target_matches": True,
        "status": "available",
    }
    if shortfall is not None:
        index_state["shortfall"] = shortfall
    if file_shortfall is not None:
        index_state["file_shortfall"] = file_shortfall

    class _ShortfallHandler(QuietHandler):
        def do_POST(self):
            if self.path != "/search":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            payload: dict[str, object] = {
                "ok": True,
                "results": (
                    [
                        {
                            "path": "src/only_survivor.py",
                            "line_start": 3,
                            "score": 0.9,
                            "snippet": "def survivor",
                        }
                    ]
                    if results
                    else []
                ),
                "index_state": index_state,
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

    server = http.server.HTTPServer(("127.0.0.1", 0), _ShortfallHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


class TestIncompleteIndexCannotAnswerSilently:
    """A search over a demonstrably truncated index must say so.

    The latch this guards against is a code collection holding a fraction of
    its corpus while answering normally: well-formed results, a plausible
    count, no error. Because semantic search is the grounding step before code
    is written, a confident answer over that fraction is a false negative to
    "does this already exist?", which is how duplicate implementations get
    written. These tests pin that the warning appears whenever the service
    reports a shortfall - with results and without - and never otherwise.

    Proven able to fail. Suppressing the CLI's shortfall branch (making
    ``_render_breadth_shortfall`` return before printing) fails
    ``test_shortfall_warns_over_returned_results`` and
    ``test_shortfall_warns_over_an_empty_answer`` on the missing-warning
    assertion each names, not on a setup or transport error; restoring returns
    both to green. Under that mutation the empty answer reads "No source code
    results found ... Indexed source code sections: 4", which is precisely the
    silent false negative these tests exist to prevent.

    The assertions name the figures, not just the word "warning": a bare
    substring match would pass on a warning that omitted the deficit, and the
    deficit is the part an operator acts on.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    _SHORTFALL: typing.ClassVar[dict[str, object]] = {
        "published_count": 421,
        "live_count": 4,
        "missing_count": 417,
    }

    def test_shortfall_warns_over_returned_results(self, tmp_path: Path) -> None:
        """Results plus a shortfall must carry the warning and the figures."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _shortfall_contract_server(
            shortfall=self._SHORTFALL, results=True
        )
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 0, result.output
        normalized = " ".join(_plain_lines(result.output))
        assert "holds 4 of the 421 sections it published" in normalized, normalized
        assert "417 are missing" in normalized, normalized
        assert "not evidence that no such code exists" in normalized, normalized
        assert "vaultspec-rag index --type code --full" in normalized, normalized

    def test_shortfall_warns_over_an_empty_answer(self, tmp_path: Path) -> None:
        """An empty answer over a truncated index is the dangerous case.

        A confident "no results" is exactly what a caller reads as proof of
        absence, so the warning matters more here than alongside results.
        """
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _shortfall_contract_server(
            shortfall=self._SHORTFALL, results=False
        )
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 0, result.output
        normalized = " ".join(_plain_lines(result.output))
        assert "holds 4 of the 421 sections it published" in normalized, normalized
        assert "417 are missing" in normalized, normalized

    def test_complete_index_is_not_warned_about(self, tmp_path: Path) -> None:
        """No shortfall on the envelope means no warning.

        A sidecar silent on breadth also arrives as no shortfall, so warning
        here would fire on every root written by an older build and train the
        reader to ignore the warning entirely.
        """
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _shortfall_contract_server(shortfall=None, results=True)
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 0, result.output
        normalized = " ".join(_plain_lines(result.output))
        assert "sections it published" not in normalized, normalized
        assert "are missing" not in normalized, normalized

    def test_json_mode_carries_the_shortfall_verbatim(self, tmp_path: Path) -> None:
        """JSON mode must carry the service's figures, not a rendered sentence.

        This is the field the MCP adapter passes through, so a JSON consumer
        has to receive the same conclusion the human warning is built from.
        """
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _shortfall_contract_server(
            shortfall=self._SHORTFALL, results=True
        )
        try:
            result = _invoke_search_contract(tmp_path, server.server_port, "--json")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope["data"]["index_state"]["shortfall"] == self._SHORTFALL


class TestFileBreadthWarningContract:
    """The CLI warns when a publication covered fewer files than it names.

    Distinct from the section-count warning: this fires where that one is
    structurally silent, because a republished fragment stamps a point count
    that agrees with itself and only the file figures disagree.

    Proven able to fail. Making ``_render_file_breadth_shortfall`` return
    before printing fails ``test_file_shortfall_warns_over_returned_results``
    on the missing-warning assertion, not on an import or collection error.
    """

    _FILE_SHORTFALL: typing.ClassVar[dict[str, object]] = {
        "named_count": 442,
        "covered_count": 27,
        "missing_count": 415,
    }

    def test_file_shortfall_warns_over_returned_results(self, tmp_path: Path) -> None:
        """A file-breadth deficit must be named even when results come back."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _shortfall_contract_server(
            shortfall=None, results=True, file_shortfall=self._FILE_SHORTFALL
        )
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 0, result.output
        normalized = " ".join(_plain_lines(result.output))
        assert "names 442 files but holds content for only 27" in normalized, normalized
        assert "415 are missing" in normalized, normalized
        assert "not evidence that no such code exists" in normalized, normalized

    def test_complete_file_breadth_stays_silent(self, tmp_path: Path) -> None:
        """No claim means no warning; warning on absence would train it away."""
        (tmp_path / ".vaultspec").mkdir()
        server, thread = _shortfall_contract_server(shortfall=None, results=True)
        try:
            result = _invoke_search_contract(tmp_path, server.server_port)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        assert result.exit_code == 0, result.output
        assert "files but holds content for only" not in result.output, result.output
