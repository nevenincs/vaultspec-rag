"""CLI coverage for search argument validation and result rendering."""

from __future__ import annotations

import contextlib
import http.server
import json
import os
import threading
import time
import typing
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

    from typer.testing import Result

from ._cli_helpers import (
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _display_search_results,
    _display_service_error,
    app,
    get_search_timeout,
    runner,
    search_records,
    try_http_search,
)
from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]


@contextlib.contextmanager
def _misbehaving_service(
    *,
    stall_seconds: float = 0.0,
    observed_paths: list[str] | None = None,
    stall_entered: threading.Event | None = None,
    stall_release: threading.Event | None = None,
):
    """Serve a live-but-broken response, optionally after stalling.

    A live service that answers with something unusable is a different
    condition from a dead one, and the caller must not conflate them. Both are
    produced here by a real socket: a stall outlasts the client timeout, and a
    non-JSON body is exactly what an unrelated server on the port would send.
    """
    body = b"<html>not the service you are looking for</html>"

    class _Handler(QuietHandler):
        def do_GET(self) -> None:
            if observed_paths is not None:
                observed_paths.append(self.path)
            self.send_response(503)
            self.end_headers()

        def do_POST(self) -> None:
            if observed_paths is not None:
                observed_paths.append(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if stall_entered is not None:
                stall_entered.set()
            if stall_release is not None:
                stall_release.wait(timeout=5)
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


@contextlib.contextmanager
def _search_envelope_service(envelope: Mapping[str, object], *, status: int = 200):
    """Serve one canonical JSON envelope and retain the exact request payload."""
    requests: list[dict[str, object]] = []
    body = json.dumps(envelope).encode()

    class _Handler(QuietHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw_request: object = json.loads(self.rfile.read(length))
            assert isinstance(raw_request, dict)
            requests.append(typing.cast("dict[str, object]", raw_request))
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1]), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _readiness_source(
    source: str,
    *,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    fact: dict[str, object] = {
        "source": source,
        "availability": "usable",
        "freshness": "current",
        "absence_authority": "non_authoritative",
        "generation": {
            "served_generation": f"{source}-served",
            "served_revision": 1,
            "desired_generation": f"{source}-desired",
            "desired_revision": 2,
        },
        "wait_policy": "bounded",
        "waits": [
            {
                "cause": "index_transition",
                "waited_seconds": 0.25,
                "configured_bound_seconds": 1.0,
                "remaining_bound_seconds": 0.75,
            }
        ],
        "evidence": ["publication_pending"],
        "reason_code": "published_generation_current",
        "retryable": True,
    }
    if overrides is not None:
        fact.update(overrides)
    return fact


def _readiness_block(sources: list[dict[str, object]]) -> dict[str, object]:
    return {
        "sources": sources,
        "aggregate": {
            "availability": "usable",
            "freshness": "updating",
            "absence_authority": "non_authoritative",
            "source_count": len(sources),
            "usable_source_count": len(sources),
            "degraded_sources": [source["source"] for source in sources],
        },
    }


def _invoke_readiness_search(tmp_path: pathlib.Path, port: int, *extra: str) -> Result:
    (tmp_path / ".vaultspec").mkdir(exist_ok=True)
    return runner.invoke(
        app,
        [
            "--target",
            str(tmp_path),
            "search",
            "readiness",
            "--type",
            "code",
            "--port",
            str(port),
            *extra,
        ],
    )


class TestSearchTimeoutDefaults:
    """Tests for service-delegated search timeout defaults."""

    def test_default_search_timeout_is_production_budget(self) -> None:
        previous = os.environ.pop("VAULTSPEC_RAG_SEARCH_TIMEOUT", None)
        try:
            assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS
        finally:
            if previous is not None:
                os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = previous

    def test_invalid_env_timeout_uses_production_budget(self) -> None:
        previous = os.environ.get("VAULTSPEC_RAG_SEARCH_TIMEOUT")
        os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = "not-a-number"
        try:
            assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS
        finally:
            if previous is None:
                os.environ.pop("VAULTSPEC_RAG_SEARCH_TIMEOUT", None)
            else:
                os.environ["VAULTSPEC_RAG_SEARCH_TIMEOUT"] = previous

    def test_explicit_timeout_still_wins(self) -> None:
        assert get_search_timeout(0.25) == 0.25


class TestCLIReadinessContract:
    def test_cli_json_preserves_the_exact_canonical_service_payload(
        self, tmp_path: pathlib.Path
    ) -> None:
        source = _readiness_source("code")
        payload: dict[str, object] = {
            "ok": True,
            "results": [{"path": "src/a.py", "snippet": "answer"}],
            "readiness": _readiness_block([source]),
            "request_id": "request-json",
        }
        with _search_envelope_service(payload) as (port, _requests):
            result = _invoke_readiness_search(tmp_path, port, "--json")

        assert result.exit_code == 0
        emitted = json.loads(result.output)
        expected = dict(payload)
        expected.update({"query": "readiness", "search_type": "code", "via": "service"})
        # Mutation evidence: dropping readiness before JSON emission failed this
        # exact data equality (exit 1); restoration passed (exit 0).
        assert emitted == {"ok": True, "command": "search", "data": expected}

    def test_cli_defaults_and_bounded_options_reach_the_service(
        self, tmp_path: pathlib.Path
    ) -> None:
        payload: dict[str, object] = {"ok": True, "results": []}
        with _search_envelope_service(payload) as (port, requests):
            immediate = _invoke_readiness_search(tmp_path, port)
            bounded = _invoke_readiness_search(
                tmp_path,
                port,
                "--freshness-policy",
                "bounded",
                "--freshness-wait-seconds",
                "2.5",
            )

        assert immediate.exit_code == 0
        assert bounded.exit_code == 0
        assert requests[0]["freshness_policy"] == "immediate"
        assert "freshness_wait_seconds" not in requests[0]
        assert requests[1]["freshness_policy"] == "bounded"
        assert requests[1]["freshness_wait_seconds"] == 2.5

    @pytest.mark.parametrize(
        ("arguments", "error"),
        [
            (["--freshness-policy", "later"], "invalid_freshness_policy"),
            (["--freshness-wait-seconds", "1"], "invalid_freshness_wait_seconds"),
            (["--freshness-policy", "bounded"], "invalid_freshness_wait_seconds"),
            (
                [
                    "--freshness-policy",
                    "bounded",
                    "--freshness-wait-seconds",
                    "301",
                ],
                "invalid_freshness_wait_seconds",
            ),
        ],
    )
    def test_cli_rejects_invalid_freshness_options_exactly(
        self, tmp_path: pathlib.Path, arguments: list[str], error: str
    ) -> None:
        result = _invoke_readiness_search(tmp_path, 1, *arguments, "--json")

        assert result.exit_code == 2
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "search"
        # Mutation evidence: bypassing the unknown-policy predicate returned
        # the wrong error code here (exit 1); restoration passed (exit 0).
        assert envelope["error"] == error

    def test_bounded_freshness_cannot_fall_back_to_local_authority(
        self, tmp_path: pathlib.Path
    ) -> None:
        result = _invoke_readiness_search(
            tmp_path,
            1,
            "--allow-fallback",
            "--freshness-policy",
            "bounded",
            "--freshness-wait-seconds",
            "1",
            "--json",
        )

        assert result.exit_code == 2
        assert json.loads(result.output)["error"] == (
            "bounded_freshness_requires_service"
        )

    def test_human_readiness_renders_all_sources_waits_and_dedupes_remediation(
        self, tmp_path: pathlib.Path
    ) -> None:
        remediation = "wait for durable publication"
        sources = [
            _readiness_source(source, overrides={"remediation": remediation})
            for source in ("vault", "code", "document")
        ]
        payload: dict[str, object] = {
            "ok": True,
            "results": [{"path": "src/a.py", "snippet": "answer"}],
            "readiness": _readiness_block(sources),
            "remediation": remediation,
        }
        with _search_envelope_service(payload) as (port, _requests):
            result = _invoke_readiness_search(tmp_path, port)

        assert result.exit_code == 0
        # Mutation evidence: removing the nonempty-success readiness render
        # failed this exact state assertion (exit 1); restoration passed (0).
        assert "Readiness: usable / updating / non_authoritative" in result.output
        for source in ("vault", "code", "document"):
            assert f"{source}: usable, current" in result.output
        for source in ("vault", "code", "document"):
            # Mutation evidence: removing the wait's source prefix failed this
            # per-source assertion (exit 1); restoration passed (exit 0).
            assert (
                f"Wait {source} index_transition: 0.25s / 1.0s (0.75s remaining)"
            ) in result.output
        assert "reason=published_generation_current" in result.output
        assert "Evidence: publication_pending" in result.output
        # Mutation evidence: removing global source-remediation deduplication
        # rendered this action three times (exit 1); restoration passed (0).
        assert result.output.count(remediation) == 1

    def test_human_failure_renders_code_distinct_fallback_and_display_bounds(
        self, tmp_path: pathlib.Path
    ) -> None:
        long_identifier = "x" * 300
        boundary_identifier = "y" * 256
        overflow_identifier = "z" * 257
        long_source = "s" * 300
        long_generation = "g" * 300
        long_wait_cause = "w" * 300
        long_top_remediation = "r" * 1_100
        source = _readiness_source(
            long_source,
            overrides={
                "availability": "unavailable",
                "freshness": "unverifiable",
                "reason_code": "index_unverifiable",
                "remediation": "establish publication evidence",
                "evidence": [
                    boundary_identifier,
                    overflow_identifier,
                    *[f"evidence-{index}-{long_identifier}" for index in range(8)],
                ],
                "generation": {"served_generation": long_generation},
                "waits": [
                    {
                        "cause": long_wait_cause,
                        "waited_seconds": 0.25,
                        "configured_bound_seconds": 1.0,
                        "remaining_bound_seconds": 0.75,
                    }
                ],
            },
        )
        payload: dict[str, object] = {
            "ok": False,
            "error": "index_unverifiable",
            "message": "Publication evidence is unavailable.",
            "retryable": True,
            "readiness": _readiness_block([source]),
            "remediation": long_top_remediation,
        }
        with _search_envelope_service(payload, status=503) as (port, _requests):
            result = _invoke_readiness_search(tmp_path, port)

        assert result.exit_code == 1
        assert "Code: index_unverifiable" in result.output
        assert "Next action: establish publication evidence" in result.output
        assert result.output.count("Evidence:") == 1
        compact_output = "".join(result.output.split())
        assert boundary_identifier in compact_output
        assert overflow_identifier not in compact_output
        assert "z" * 255 in compact_output
        # Mutation evidence: removing evidence/item bounds exposed evidence-6
        # and 300 x's, failing both assertions (exit 1); restoration passed (0).
        assert "evidence-6" not in result.output
        assert long_identifier not in result.output
        for overlong in (
            long_source,
            long_generation,
            long_wait_cause,
            long_top_remediation,
        ):
            assert overlong not in compact_output
        assert "s" * 255 in compact_output
        assert "g" * 255 in compact_output
        assert "w" * 255 in compact_output
        # Mutation evidence: printing top-level remediation raw exposed all
        # 1,100 r characters (exit 1); restoration passed (exit 0).
        assert "r" * 1_023 in compact_output


class TestMcpFastPath:
    """Tests for MCP fast-path functions (try_http_search, _display_search_results)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_transport_propagates_default_and_bounded_freshness(self) -> None:
        success: dict[str, object] = {
            "ok": True,
            "results": [{"text": "canonical"}],
        }
        with _search_envelope_service(success) as (port, requests):
            immediate = try_http_search("q", "code", 5, port, "/tmp/proj")
            bounded = try_http_search(
                "q",
                "code",
                5,
                port,
                "/tmp/proj",
                freshness_policy="bounded",
                freshness_wait_seconds=2.5,
            )

        assert immediate == success
        assert bounded == success
        # Mutation evidence: removing freshness_policy from the wire payload
        # failed here with KeyError (exit 1); restoration passed (exit 0).
        assert requests[0]["freshness_policy"] == "immediate"
        assert "freshness_wait_seconds" not in requests[0]
        assert requests[1]["freshness_policy"] == "bounded"
        assert requests[1]["freshness_wait_seconds"] == 2.5

    def test_search_transport_preserves_canonical_failure_envelope_exactly(
        self,
    ) -> None:
        failure: dict[str, object] = {
            "ok": False,
            "error": "freshness_wait_timeout",
            "message": "canonical service refusal",
            "retryable": True,
            "request_id": "request-1",
            "readiness": {"sources": [], "aggregate": {"authoritative": False}},
            "remediation": "wait for publication",
        }
        with _search_envelope_service(failure, status=503) as (port, requests):
            result = try_http_search(
                "q",
                "vault",
                5,
                port,
                "/tmp/proj",
                freshness_policy="bounded",
                freshness_wait_seconds=1.0,
            )

        # Mutation evidence: wrapping the returned service dict with a client
        # timeout diagnosis failed this exact equality (exit 1); restoration
        # passed (exit 0). This guards adapter ownership of the canonical body.
        assert result == failure
        assert requests == [
            {
                "query": "q",
                "top_k": 5,
                "project_root": "/tmp/proj",
                "type": "vault",
                "freshness_policy": "bounded",
                "freshness_wait_seconds": 1.0,
            }
        ]

    def test_search_timeout_remains_transport_only_without_diagnostic_probes(
        self,
    ) -> None:
        observed_paths: list[str] = []
        entered = threading.Event()
        release = threading.Event()
        results: list[dict[str, object] | None] = []
        with _misbehaving_service(
            observed_paths=observed_paths,
            stall_entered=entered,
            stall_release=release,
        ) as port:
            worker = threading.Thread(
                target=lambda: results.append(
                    try_http_search("q", "code", 5, port, "/tmp/proj", timeout=1.0)
                )
            )
            worker.start()
            try:
                assert entered.wait(timeout=2), (
                    "server did not enter the response stall"
                )
                worker.join(timeout=3)
                assert not worker.is_alive(), "transport did not honor its timeout"
            finally:
                release.set()
                worker.join(timeout=2)

        [result] = results
        assert result is not None
        assert result["ok"] is False
        assert result["error"] == "http_call_failed"
        # Mutation evidence: restoring the removed timeout-diagnostics branch
        # failed on the exact error assertion above (exit 1); restoration passed
        # (exit 0), proving the client cannot recreate readiness or retry facts.
        assert "readiness" not in result
        assert "retryable" not in result
        assert "remediation" not in result
        assert "Retry-After" not in result
        assert "diagnostics" not in result
        assert observed_paths == ["/search"]

    def test_tool_map_vault(self):
        """Connection refused on port 1 returns None, no exception."""
        result = try_http_search("test query", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_tool_map_code(self):
        """search_type='code' maps to search_codebase, returns None on failure."""
        result = try_http_search("test query", "code", 5, 1, "/tmp/proj")
        assert result is None

    def test_invalid_search_type(self):
        """Unknown search types fail explicitly without a transport fallback."""
        result = try_http_search("test query", "invalid", 5, 1, "/tmp/proj")
        assert isinstance(result, dict)
        assert result["ok"] is False
        assert result["error"] == "unknown_source_type"
        assert result["received"] == "invalid"

    def test_code_filters_with_vault_returns_usage_error(self):
        """Filter kwargs with --type vault yield a structured usage error."""
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search("q", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_code_filters_with_code_attempts_call(self):
        """Filters paired with --type code reach the call path; no service → None."""
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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
        result = try_http_search(
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

        from .._search_state import (
            AbsenceAuthority,
            SearchAvailability,
            SearchFreshness,
            SearchSourceFact,
        )
        from .._source_types import IndexSource, PublicSourceType
        from ..cli._search import _InProcessRenderRequest, _render_in_process_results
        from ..search._outcomes import (
            COMBINED_SEARCH_FAILED,
            COMBINED_SEARCH_FAILED_MESSAGE,
            CombinedSearchOutcome,
            SearchDomainOutcome,
        )

        def unavailable_fact(source: IndexSource) -> SearchSourceFact:
            return SearchSourceFact(
                source=source,
                availability=SearchAvailability.UNAVAILABLE,
                freshness=SearchFreshness.UNVERIFIABLE,
                absence_authority=AbsenceAuthority.NON_AUTHORITATIVE,
                reason_code="index_unavailable",
                retryable=True,
                remediation="vaultspec-rag server status --verbose",
            )

        outcome = CombinedSearchOutcome(
            SearchDomainOutcome.failure(
                PublicSourceType.VAULT,
                "index_unavailable",
                "vault index missing",
                source_fact=unavailable_fact("vault"),
            ),
            SearchDomainOutcome.failure(
                PublicSourceType.CODE,
                "index_unavailable",
                "code index missing",
                source_fact=unavailable_fact("code"),
            ),
            SearchDomainOutcome.failure(
                PublicSourceType.DOCUMENT,
                "index_unavailable",
                "document index missing",
                source_fact=unavailable_fact("document"),
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
        result = try_http_search(
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
        from ..serviceclient._search_transport import try_http_search

        with _misbehaving_service() as port:
            result = try_http_search("q", "code", 5, port, "/tmp/proj")

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
        from ..serviceclient._search_transport import try_http_search

        with contextlib.closing(__import__("socket").socket()) as probe:
            probe.bind(("127.0.0.1", 0))
            dead_port = probe.getsockname()[1]

        result = try_http_search("q", "code", 5, dead_port, "/tmp/proj")
        assert result is None


class TestSearchResultRendering:
    """Human search results are line-oriented and never silently truncated."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _render_all(
        self,
        results: list[dict[str, object]],
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
                results,
                "code",
                via="service",
                show_scores=show_scores,
            )
        return out.getvalue()

    def _render(
        self,
        result: dict[str, object],
        *,
        show_scores: bool = False,
    ) -> str:
        return self._render_all([result], show_scores=show_scores)

    def test_default_keeps_full_snippet(self):
        """Default output renders the full snippet."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "a" * 300})
        [record] = search_records(rendered)
        assert record["text"] == "a" * 300

    def test_scores_are_hidden_by_default(self):
        """Default output shows numbering, not numeric relevance score."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "test"})
        [record] = search_records(rendered)
        assert record["number"] == 1
        assert record["location"] == "foo.py"
        assert record["score"] is None

    def test_scores_flag_renders_numeric_score(self):
        """--scores detail mode includes the relevance score."""
        rendered = self._render(
            {"path": "foo.py", "score": 0.9, "snippet": "test"},
            show_scores=True,
        )
        [record] = search_records(rendered)
        assert record["score"] == "0.9000"

    def test_display_empty_results(self) -> None:
        """No results prints nothing at all - no header, no empty record.

        Mutation this catches: emitting a header, a count line, or a blank
        record for an empty result set. The earlier version called the
        renderer and asserted nothing, so it held even for a renderer whose
        whole body was ``pass``.
        """
        rendered = self._render_all([])

        assert rendered == ""
        assert search_records(rendered) == []

    def test_display_missing_fields(self) -> None:
        """A result carrying no keys still renders, and names the gap.

        Mutation this catches: dropping the ``location-not-reported``
        fallback, or skipping a result whose fields are all absent. The
        earlier version asserted only that the call did not raise.
        """
        rendered = self._render({})

        [record] = search_records(rendered)
        assert record["number"] == 1
        assert record["location"] == "location-not-reported"
        assert record["score"] is None
        assert record["text"] == ""

    def test_display_with_line_start(self):
        """Result with line_start appends :N to location."""
        rendered = self._render(
            {"path": "foo.py", "score": 0.9, "snippet": "test", "line_start": 42},
        )
        [record] = search_records(rendered)
        assert record["location"] == "foo.py:42"

    def test_display_without_line_start(self):
        """Result without line_start renders location as bare path."""
        rendered = self._render({"path": "foo.py", "score": 0.9, "snippet": "test"})
        [record] = search_records(rendered)
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
        [record] = search_records(rendered)
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
