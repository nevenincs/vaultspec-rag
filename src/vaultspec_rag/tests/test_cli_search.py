"""CLI coverage for search argument validation and result rendering."""

from __future__ import annotations

import contextlib
import http.server
import os
import threading
import time
import typing
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib

from ._cli_helpers import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _display_search_results,
    _display_service_error,
    _get_search_timeout,
    _search_records,
    _try_http_search,
    app,
    runner,
)
from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]


@contextlib.contextmanager
def _misbehaving_service(*, stall_seconds: float = 0.0):
    """Serve a live-but-broken response, optionally after stalling.

    A live service that answers with something unusable is a different
    condition from a dead one, and the caller must not conflate them. Both are
    produced here by a real socket: a stall outlasts the client timeout, and a
    non-JSON body is exactly what an unrelated server on the port would send.
    """
    body = b"<html>not the service you are looking for</html>"

    class _Handler(QuietHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if stall_seconds:
                time.sleep(stall_seconds)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestSearchTimeoutDefaults:
    """Tests for service-delegated search timeout defaults."""

    def test_default_search_timeout_is_production_budget(self) -> None:
        previous = os.environ.pop("VAULTSPEC_RAG_SEARCH_TIMEOUT", None)
        try:
            assert _get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS
        finally:
            if previous is not None:
                os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = previous

    def test_invalid_env_timeout_uses_production_budget(self) -> None:
        previous = os.environ.get("VAULTSPEC_RAG_SEARCH_TIMEOUT")
        os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = "not-a-number"
        try:
            assert _get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS
        finally:
            if previous is None:
                os.environ.pop("VAULTSPEC_RAG_SEARCH_TIMEOUT", None)
            else:
                os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = previous

    def test_explicit_timeout_still_wins(self) -> None:
        assert _get_search_timeout(0.25) == 0.25


class TestMcpFastPath:
    """Tests for MCP fast-path functions (_try_http_search, _display_search_results)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_tool_map_vault(self):
        """Connection refused on port 1 returns None, no exception."""
        result = _try_http_search("test query", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_tool_map_code(self):
        """search_type='code' maps to search_codebase, returns None on failure."""
        result = _try_http_search("test query", "code", 5, 1, "/tmp/proj")
        assert result is None

    def test_invalid_search_type(self):
        """Unknown search types fail explicitly without a transport fallback."""
        result = _try_http_search("test query", "invalid", 5, 1, "/tmp/proj")
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert result["error"] == "unknown_source_type"
        assert result["received"] == "invalid"

    def test_code_filters_with_vault_returns_usage_error(self):
        """Filter kwargs with --type vault yield a structured usage error."""
        result = _try_http_search(
            "test query",
            "vault",
            5,
            1,
            "/tmp/proj",
            function_name="foo",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--function-name" in str(result.get("message", ""))

    def test_code_filters_with_all_reach_combined_transport(self):
        """The explicit all alias accepts code filters for combined search."""
        result = _try_http_search(
            "q",
            "all",
            5,
            1,
            "/tmp/proj",
            language="python",
            class_name="Foo",
        )
        assert result is None

    def test_code_filters_unset_dont_short_circuit(self):
        """All filters None must not trigger the usage error path."""
        # No service running on port 1 → expect transport None, NOT usage-error dict.
        result = _try_http_search("q", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_code_filters_with_code_attempts_call(self):
        """Filters paired with --type code reach the call path; no service → None."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            language="python",
            function_name="foo",
        )
        # No live service → transport failure → None (not a usage-error dict).
        assert result is None

    # The corpus-specific flags and the type they belong to. Each row asserts the
    # usage exit AND the sentence that names the right --type, because the two
    # directions render different remediation and a shared-prefix match would
    # stop telling them apart.
    @pytest.mark.parametrize(
        ("corpus", "flag", "required_type"),
        [
            ("vault", ["--function-name", "foo"], "code"),
            ("code", ["--feature", "auth"], "vault"),
            ("vault", ["--include-path", "src/**"], "code"),
            ("vault", ["--exclude-path", "locales/*.yml"], "code"),
            ("vault", ["--dedup-locales"], "code"),
            ("vault", ["--prefer", "production"], "code"),
        ],
        ids=[
            "function-name",
            "feature",
            "include-path",
            "exclude-path",
            "dedup-locales",
            "prefer",
        ],
    )
    def test_search_cmd_rejects_a_flag_for_the_other_corpus(
        self,
        corpus: str,
        flag: list[str],
        required_type: str,
    ) -> None:
        result = runner.invoke(
            app,
            ["search", "anything", "--type", corpus, *flag],
        )
        assert result.exit_code == 2
        assert f"require --type {required_type}" in result.output

    def test_search_cmd_rejects_unknown_option_with_plain_language(self):
        result = runner.invoke(app, ["search", "anything", "--bogus-option"])

        assert result.exit_code == 2
        assert "Unexpected search options: --bogus-option" in result.output
        assert "option(s)" not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["search", "anything", "--type", "code", "--node-type", "function"],
            ["search", "anything", "--type", "code", "--no-truncate"],
        ],
    )
    def test_search_removed_legacy_flags_are_not_supported(self, argv: list[str]):
        result = runner.invoke(app, argv)

        assert result.exit_code == 2
        assert "Unexpected search options:" in result.output
        assert "Searching code" not in result.output

    def test_path_filter_with_vault_returns_usage_error(self):
        """--path is a code filter; pairing it with vault must error."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            path="src/foo.py",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "path" in str(result.get("message", ""))

    def test_vault_filter_with_code_returns_usage_error(self):
        """doc_type/feature/date/tag with --type code must error."""
        result = _try_http_search(
            "test",
            "code",
            5,
            1,
            "/tmp/proj",
            doc_type="adr",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--doc-type" in str(result.get("message", ""))

    def test_vault_filters_with_code_attempt_call(self):
        """doc_type/feature/date/tag with --type vault reach the call path."""
        result = _try_http_search(
            "q",
            "vault",
            5,
            1,
            "/tmp/proj",
            doc_type="adr",
            feature="auth",
            date="2026-05-28",
            tag="auth",
        )
        # No live service → ConnectionRefused → None.
        assert result is None

    def test_include_path_with_vault_returns_usage_error(self):
        """--include-path is a code filter; --type vault must error."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            include_paths=["src/foo/**"],
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--include-path" in str(result.get("message", ""))

    def test_exclude_path_with_vault_returns_usage_error(self):
        """--exclude-path with --type vault errors out symmetrically."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            exclude_paths=["locales/*.yml"],
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--exclude-path" in str(result.get("message", ""))

    def test_glob_filters_with_code_attempt_call(self):
        """--include-path/--exclude-path with --type code reach the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            include_paths=["src/**"],
            exclude_paths=["tests/**"],
        )
        assert result is None

    def test_dedup_locales_with_vault_returns_usage_error(self):
        """--dedup-locales is a code-only post-process flag."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            dedup_locales=True,
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--dedup-locales" in str(result.get("message", ""))

    def test_prefer_with_vault_returns_usage_error(self):
        """--prefer is a code-only post-process flag."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            prefer="prod",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--prefer" in str(result.get("message", ""))

    def test_postproc_flags_with_code_attempt_call(self):
        """dedup_locales/prefer with --type code reach the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            dedup_locales=True,
            prefer="tests",
        )
        assert result is None

    def test_search_cmd_rejects_invalid_prefer_value(self):
        """CLI: --prefer reports user-facing supported values."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--prefer",
                "bogus",
            ],
        )
        assert result.exit_code == 2
        assert "production, tests, or documentation" in result.output
        assert "prod|tests|docs" not in result.output

    def test_cli_prefer_refusal_is_the_search_domains_own_sentence(self):
        """The CLI must show the validator's wording, not a second copy of it.

        Compared against the owning error's rendering rather than a literal, so
        the assertion cannot pass while the two wordings drift apart - which is
        the whole failure mode a restated message causes for an operator.
        """
        import json as _json

        from ..search import InvalidPreferValueError

        result = runner.invoke(
            app,
            ["search", "anything", "--type", "code", "--prefer", "bogus", "--json"],
        )
        assert result.exit_code == 2
        payload = _json.loads(result.output)
        assert payload["error"] == "invalid_prefer_value"
        assert payload["value"] == "bogus"
        assert payload["message"] == str(InvalidPreferValueError("bogus"))

    @pytest.mark.parametrize("prefer", ["prod", "docs"])
    def test_search_cmd_rejects_internal_prefer_values(self, prefer: str):
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--prefer",
                prefer,
            ],
        )

        assert result.exit_code == 2
        assert "production, tests, or documentation" in result.output
        assert prefer in result.output

    def test_in_process_combined_failure_derives_the_service_vocabulary(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The local render path reports the search domain's own kind, message
        and per-domain status - not a hand-built copy of any of the three.

        ``domains`` is compared against the outcome's own payload rather than a
        literal, so a rebuilt dict that drifts in a key name or a value fails
        here instead of reaching an operator as a differently-shaped report.
        """
        import json as _json

        import typer

        from .._source_types import PublicSourceType
        from ..cli._search import _InProcessRenderRequest, _render_in_process_results
        from ..search._outcomes import (
            COMBINED_SEARCH_FAILED,
            COMBINED_SEARCH_FAILED_MESSAGE,
            CombinedSearchOutcome,
            SearchDomainOutcome,
        )

        outcome = CombinedSearchOutcome(
            SearchDomainOutcome.failure(
                PublicSourceType.VAULT, "index_unavailable", "vault index missing"
            ),
            SearchDomainOutcome.failure(
                PublicSourceType.CODE, "index_unavailable", "code index missing"
            ),
            SearchDomainOutcome.failure(
                PublicSourceType.DOCUMENT, "index_unavailable", "document index missing"
            ),
            top_k=5,
        )
        with pytest.raises(typer.Exit) as raised:
            _render_in_process_results(
                _InProcessRenderRequest(
                    results=outcome,
                    query="anything",
                    search_type=PublicSourceType.COMBINED,
                    json_mode=True,
                    show_scores=False,
                    target=tmp_path,
                )
            )

        assert raised.value.exit_code == 1
        emitted = capsys.readouterr().out.strip().splitlines()
        assert len(emitted) == 1, "JSON mode must emit exactly one envelope"
        payload = _json.loads(emitted[0])
        assert payload["ok"] is False
        assert payload["error"] == COMBINED_SEARCH_FAILED
        assert payload["message"] == COMBINED_SEARCH_FAILED_MESSAGE
        assert payload["domains"] == outcome.domain_status_payload()

    def test_path_filter_with_code_attempts_call(self):
        """--path with --type code reaches the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            path="src/foo.py",
        )
        assert result is None

    def test_live_but_broken_returns_structured_error(self) -> None:
        """A live-but-unusable service yields ok=False, never None.

        Without this discrimination the caller treats a broken service the
        same as a dead one and silently relanes to the unsafe in-process path.
        The server here is genuinely listening and genuinely answering with
        something unusable, which is the condition being discriminated.
        """
        from ..serviceclient._transport import _try_http_search

        with _misbehaving_service() as port:
            result = _try_http_search("q", "code", 5, port, "/tmp/proj")

        assert isinstance(result, dict)
        assert result.get("ok") is False
        # The real code for a live server answering with something unusable.
        # The substituted version raised RuntimeError and so asserted
        # http_call_failed - a code this condition does not actually produce.
        assert result.get("error") == "invalid_service_response"

    def test_live_but_broken_reindex_returns_structured_error(self) -> None:
        """Same discrimination for _try_http_reindex."""
        from ..serviceclient._transport import _try_http_reindex

        with _misbehaving_service() as port:
            result = _try_http_reindex(
                "vault", False, port, "/tmp/proj", initiator_kind="cli"
            )

        assert isinstance(result, dict)
        assert result.get("ok") is False

    def test_connection_refused_still_returns_none(self) -> None:
        """A refused connection must keep the dead-service path.

        Nothing is bound on this port, so the refusal comes from the operating
        system rather than a substituted transport - which is the only way to
        know the caller still reads a real refusal as a dead service.
        """
        from ..serviceclient._transport import _try_http_search

        with contextlib.closing(__import__("socket").socket()) as probe:
            probe.bind(("127.0.0.1", 0))
            dead_port = probe.getsockname()[1]

        result = _try_http_search("q", "code", 5, dead_port, "/tmp/proj")
        assert result is None


class TestSearchResultRendering:
    """Human search results are line-oriented and never silently truncated."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _render(
        self,
        result: dict[str, object],
        *,
        show_scores: bool = False,
    ) -> str:
        from io import StringIO

        from rich.console import Console

        out = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "vaultspec_rag.cli.console",
                Console(file=out, force_terminal=False, width=400),
            )
            _display_search_results(
                [result],
                "code",
                via="service",
                show_scores=show_scores,
            )
        return out.getvalue()

    def test_default_keeps_full_snippet(self):
        """Default output renders the full snippet."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "a" * 300})
        [record] = _search_records(rendered)
        assert record["text"] == "a" * 300

    def test_scores_are_hidden_by_default(self):
        """Default output shows numbering, not numeric relevance score."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "test"})
        [record] = _search_records(rendered)
        assert record["number"] == 1
        assert record["location"] == "foo.py"
        assert record["score"] is None

    def test_scores_flag_renders_numeric_score(self):
        """--scores detail mode includes the relevance score."""
        rendered = self._render(
            {"path": "foo.py", "score": 0.9, "snippet": "test"},
            show_scores=True,
        )
        [record] = _search_records(rendered)
        assert record["score"] == "0.9000"

    def test_display_empty_results(self):
        """Empty results list renders without raising."""
        _display_search_results([], "vault")

    def test_display_missing_fields(self):
        """Dict with no keys renders without raising."""
        _display_search_results([{}], "vault")

    def test_display_with_line_start(self):
        """Result with line_start appends :N to location."""
        rendered = self._render(
            {"path": "foo.py", "score": 0.9, "snippet": "test", "line_start": 42},
        )
        [record] = _search_records(rendered)
        assert record["location"] == "foo.py:42"

    def test_display_without_line_start(self):
        """Result without line_start renders location as bare path."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "test"})
        [record] = _search_records(rendered)
        assert record["location"] == "foo.py"

    def test_display_with_anchor_prefers_deep_link(self):
        """Anchor locators stay mechanically grabbable."""
        rendered = self._render(
            {
                "path": "report.pdf",
                "anchor": "report.pdf#page=4",
                "line_start": 12,
                "score": 0.9,
                "snippet": "test",
            }
        )
        [record] = _search_records(rendered)
        assert record["location"] == "report.pdf#page=4"

    def test_display_service_lock_error_hides_backend_contract(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Default service errors do not render backend contract tables."""
        _display_service_error(
            {
                "ok": False,
                "error": "local_store_locked",
                "message": "Route concurrent searches through one service.",
                "db_path": "/tmp/qdrant",
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                    "cross_project_search_strategy": "parallel",
                    "local_storage_process_model": "exclusive",
                },
            },
        )

        out = capsys.readouterr().out
        assert "Route concurrent searches through one service." in out
        assert "local_store_locked" in out
        assert "Index data: /tmp/qdrant" in out
        assert "DB path:" not in out
        assert "same-project local backend access" not in out
        assert "same_project_search_strategy" not in out
        assert "serialized" not in out
        for forbidden in ("┌", "└", "│"):
            assert forbidden not in out

    def test_display_service_error_fallback_uses_plain_service_name(
        self, capsys: pytest.CaptureFixture[str]
    ):
        _display_service_error({"ok": False, "error": "service_error"})

        out = capsys.readouterr().out
        assert "Search service returned an error." in out
        assert "RAG service" not in out

    def test_display_search_timeout_error_humanizes_diagnostics(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Search timeout errors answer readiness/work status without raw keys."""
        _display_service_error(
            {
                "ok": False,
                "error": "http_search_timeout",
                "message": (
                    "HTTP search on port 8766 timed out after 180.0s. "
                    "The service may still be processing the request. "
                    "Service status=unknown; running_jobs=unknown; "
                    "same_project_search_strategy=serialized."
                ),
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                    "cross_project_search_strategy": "parallel",
                    "local_storage_process_model": "exclusive",
                },
                "diagnostics": {
                    "health": {
                        "available": False,
                        "error": "TimeoutError",
                        "message": "timed out",
                    },
                    "jobs": {
                        "available": True,
                        "running_count": 2,
                    },
                },
                "remediation": [
                    "vaultspec-rag search ... --port 8766 --timeout 360",
                    "vaultspec-rag server status",
                    "vaultspec-rag server jobs --state active --port 8766",
                ],
            },
        )

        out = capsys.readouterr().out
        assert "HTTP search on port 8766 timed out after 180.0s." in out
        assert "Service: request check timed out" in out
        assert "Work: 2 active index jobs" in out
        assert "vaultspec-rag server jobs --state active --port 8766" in out
        assert "same_project_search_strategy" not in out
        assert "serialized" not in out
        for forbidden in ("┌", "└", "│"):
            assert forbidden not in out

    def test_display_search_timeout_missing_job_count_uses_absence_language(
        self, capsys: pytest.CaptureFixture[str]
    ):
        _display_service_error(
            {
                "ok": False,
                "error": "http_search_timeout",
                "message": "HTTP search on port 8766 timed out after 180.0s.",
                "diagnostics": {
                    "health": {
                        "available": True,
                        "status": "ready",
                    },
                    "jobs": {
                        "available": True,
                    },
                },
            },
        )

        out = capsys.readouterr().out
        assert "Service: reachable; requests ready" in out
        assert "Work: active job count not reported by service" in out
        assert "running work status unknown" not in out
        assert "unknown" not in out
        assert "health check" not in out


class TestArgvPathPatterns:
    """A quoted path pattern must reach the parser exactly as typed.

    Click and Typer simulate Unix shell expansion on Windows: arguments read
    from ``sys.argv`` pass through ``glob``, ``expanduser``, and
    ``expandvars`` before parsing. These filters match indexed
    project-relative paths, not files on disk, so that expansion turns one
    pattern into a run of filenames, and every match past the first reaches
    the parser as an unexpected positional argument.

    Both tests drive the real command object over a patched ``sys.argv``,
    because the expansion runs only on the ``sys.argv`` branch: a runner that
    hands ``main`` an explicit argument list never reaches it, and so cannot
    observe this defect at all.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @staticmethod
    def _run_over_argv(argv: list[str]) -> None:
        import sys

        import typer

        from ..cli import app as root_app

        command = typer.main.get_command(root_app)
        original = sys.argv
        sys.argv = argv
        try:
            command.main(args=None, prog_name="vaultspec-rag")
        finally:
            sys.argv = original

    @staticmethod
    def _require_expandable_cwd(pattern: str) -> None:
        """Fail loudly when the working directory cannot exercise expansion.

        Without this the guard could pass for the wrong reason: a pattern
        matching nothing on disk survives argv untouched even with expansion
        fully enabled, so the test would report success over a regressed CLI.
        """
        from click.utils import _expand_args

        assert len(_expand_args([pattern])) > 1, (
            f"{pattern!r} must match several files in the working directory "
            "for this guard to exercise filesystem expansion"
        )

    @pytest.mark.parametrize("flag", ["--include-path", "--exclude-path"])
    def test_a_path_pattern_is_not_filesystem_expanded(
        self,
        flag: str,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        import json

        self._require_expandable_cwd("src/**")

        # Reaching the dead port proves the pattern parsed as a single option
        # value. Restore the expansion - drop windows_expand_args=False from
        # the root command group - and this exits 2 from the extra-argument
        # check instead, on the "Unexpected search options" branch.
        with pytest.raises(SystemExit) as exit_info:
            self._run_over_argv(
                [
                    "vaultspec-rag",
                    "search",
                    "reopen a drifted indexed path",
                    "--type",
                    "code",
                    flag,
                    "src/**",
                    "--port",
                    "1",
                    "--json",
                ]
            )

        assert exit_info.value.code == 1
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["error"] == "port_unreachable"

    def test_the_query_argument_is_not_filesystem_expanded(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The expansion was argv-wide, so the query text was exposed too."""
        import json

        self._require_expandable_cwd("*.toml")

        with pytest.raises(SystemExit) as exit_info:
            self._run_over_argv(
                [
                    "vaultspec-rag",
                    "search",
                    "*.toml",
                    "--type",
                    "code",
                    "--port",
                    "1",
                    "--json",
                ]
            )

        assert exit_info.value.code == 1
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["error"] == "port_unreachable"
