"""CLI workspace, rebuild admission and publication authority coverage."""

from __future__ import annotations

import inspect
import json
import typing

import pytest

from ._cli_helpers import (
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


class TestIndexAuthorityBoundary:
    def test_cli_publication_authority_is_required_and_closed(self) -> None:
        """A default or a third publication authority fails this guard."""
        from ..cli._index import _publication_authority
        from ..indexer._run_ledger_models import RunAuthority

        parameter = inspect.signature(_publication_authority).parameters["rebuild"]
        assert parameter.default is inspect.Parameter.empty
        assert {
            _publication_authority(rebuild=False),
            _publication_authority(rebuild=True),
        } == {RunAuthority.PUBLICATION, RunAuthority.REBUILD}

    @pytest.mark.parametrize("request_kind", ["local", "service"])
    def test_audit_authority_cannot_enter_publication_paths(
        self,
        tmp_path: Path,
        request_kind: str,
    ) -> None:
        """Audit uses its own non-mutating path; publication paths fail closed."""
        from .._source_types import PublicSourceType
        from ..cli._index import _IndexRunRequest, _ServiceDelegationRequest
        from ..indexer._run_ledger_models import RunAuthority

        if request_kind == "local":
            request = _IndexRunRequest(
                PublicSourceType.CODE,
                RunAuthority.AUDIT_VERIFICATION,
                None,
                None,
                tmp_path,
                False,
            )
        else:
            request = _ServiceDelegationRequest(
                8765,
                None,
                False,
                PublicSourceType.CODE,
                RunAuthority.AUDIT_VERIFICATION,
                tmp_path,
            )

        with pytest.raises(ValueError, match="audit verification"):
            _ = request.rebuild

    def test_benchmark_reindex_uses_canonical_publication_wire_contract(self) -> None:
        """Operational callers must use the same exact route vocabulary as the CLI."""
        from .benchmarks.bench_concurrency import ServiceTarget, _start_reindex

        requests: list[tuple[str, dict[str, object], float]] = []

        class _CaptureTarget(ServiceTarget):
            def post(
                self,
                path: str,
                payload: dict[str, object],
                timeout: float,
            ) -> tuple[int, dict[str, object]]:
                requests.append((path, payload, timeout))
                return 202, {"job_id": "benchmark-job"}

        job_id = _start_reindex(_CaptureTarget(port=0, token=""), "project", 4.0)

        assert job_id == "benchmark-job"
        assert requests == [
            (
                "/reindex",
                {
                    "type": "code",
                    "clean": False,
                    "authority": "publication",
                    "project_root": "project",
                    "initiator_kind": "benchmark",
                },
                4.0,
            )
        ]

    def test_benchmark_searches_use_canonical_wire_source_types(self) -> None:
        """Every benchmark request uses the strict public route vocabulary.

        Mutation proof: restoring the CLI-only ``codebase`` alias makes the
        allowed-type assertion fail before a saturation run can misreport every
        code request as a throughput error.
        """
        from .benchmarks.bench_concurrency import build_scenarios

        scenarios = build_scenarios(["project", "other"], 8, 10)
        source_types = {
            str(payload["type"])
            for _name, payloads in scenarios
            for payload in payloads
        }

        assert source_types <= {"vault", "code", "document", "combined"}
        assert "code" in source_types

    def test_full_audit_requires_explicit_type(self, tmp_path: Path) -> None:
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--full"],
        )

        assert result.exit_code == 2
        assert "--full" in result.output
        assert "explicit --type" in result.output

    @pytest.mark.parametrize(
        ("spelling", "expected"),
        [
            ("codebase", "code"),
            ("docs", "vault"),
            ("all", "combined"),
        ],
    )
    def test_full_audit_takes_the_same_spellings_the_verb_does(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        spelling: str,
        expected: str,
    ) -> None:
        """One vocabulary for --type, whatever the verb goes on to do.

        `index --type docs` and `index --full --type docs` used to disagree,
        and the refusal took `all` with it - the flag's own default spelling,
        and so the only way to name every source at once. An operator had no
        way to read that split off the help.

        The resolved source is captured at the transport rather than inferred
        from an exit code, because accepting the alias and then auditing the
        wrong corpus would satisfy a status-only assertion.
        """
        from .._source_types import PublicSourceType
        from ..cli import _index as index_module

        (tmp_path / ".vaultspec").mkdir()
        seen: list[str] = []

        def capture(
            audit_type: object, *_args: object, **_kwargs: object
        ) -> dict[str, object]:
            seen.append(PublicSourceType(audit_type).value)
            return {"ok": True, "status": "consistent", "domains": {}}

        monkeypatch.setattr(index_module, "_try_http_index_audit", capture)

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                spelling,
                "--full",
                "--port",
                "9123",
            ],
        )

        assert result.exit_code == 0, result.output
        assert seen == [expected]

    @pytest.mark.parametrize("conflict", ["--rebuild", "--dry-run", "--borrow-gpu"])
    def test_full_audit_rejects_publication_modes(
        self,
        tmp_path: Path,
        conflict: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ..cli import _index as index_module

        (tmp_path / ".vaultspec").mkdir()

        def forbidden_transport(*_args: object, **_kwargs: object) -> typing.NoReturn:
            raise AssertionError("an invalid audit request reached transport")

        monkeypatch.setattr(index_module, "_try_http_index_audit", forbidden_transport)
        monkeypatch.setattr(index_module, "_try_http_reindex", forbidden_transport)

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--full",
                conflict,
            ],
        )

        assert result.exit_code == 2
        assert "cannot be combined" in result.output

    def test_full_audit_uses_separate_service_transport_and_authority(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ..cli import _index as index_module
        from ..indexer._run_ledger_models import RunAuthority

        (tmp_path / ".vaultspec").mkdir()
        calls: list[tuple[object, int, str, RunAuthority]] = []

        def audit_call(
            source: object,
            port: int,
            project_root: str,
            *,
            authority: RunAuthority,
        ) -> dict[str, object]:
            calls.append((source, port, project_root, authority))
            return {
                "ok": True,
                "status": "consistent",
                "domains": {
                    "code": {
                        "ok": True,
                        "status": "consistent",
                        "source": "code",
                        "expected_points": 3,
                        "scanned_points": 3,
                    }
                },
            }

        monkeypatch.setattr(index_module, "_try_http_index_audit", audit_call)

        def forbidden_reindex(*_args: object, **_kwargs: object) -> typing.NoReturn:
            raise AssertionError("audit must not use publication reindex transport")

        monkeypatch.setattr(
            index_module,
            "_try_http_reindex",
            forbidden_reindex,
        )

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--full",
                "--port",
                "9123",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        assert calls == [
            (
                index_module.PublicSourceType.CODE,
                9123,
                str(tmp_path),
                RunAuthority.AUDIT_VERIFICATION,
            )
        ]
        envelope = json.loads(result.output)
        assert envelope["ok"] is True
        assert envelope["data"]["mode"] == "audit_verification"
        assert envelope["data"]["via"] == "service"

    def test_full_audit_mismatch_exits_nonzero_with_one_json_envelope(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ..cli import _index as index_module

        (tmp_path / ".vaultspec").mkdir()

        def drift_audit(
            _source: object,
            _port: int,
            _project_root: str,
            *,
            authority: object,
        ) -> dict[str, object]:
            del authority
            return {
                "ok": False,
                "status": "drift",
                "domains": {
                    "code": {
                        "ok": False,
                        "status": "drift",
                        "source": "code",
                        "missing_points": 1,
                    }
                },
            }

        monkeypatch.setattr(
            index_module,
            "_try_http_index_audit",
            drift_audit,
        )

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--full",
                "--port",
                "9123",
                "--json",
            ],
        )

        assert result.exit_code == 1
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["error"] == "audit_verification_failed"
        assert envelope["data"]["domains"]["code"]["missing_points"] == 1

    def test_full_audit_transport_sends_only_verification_authority(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from .._source_types import PublicSourceType
        from ..indexer._run_ledger_models import RunAuthority
        from ..serviceclient import _transport as transport

        calls: list[tuple[int, str, dict[str, object]]] = []

        def http_call(
            port: int,
            path: str,
            payload: dict[str, object],
            *,
            timeout: float,
        ) -> dict[str, object]:
            assert timeout > 0
            calls.append((port, path, payload))
            return {"ok": True}

        monkeypatch.setattr(transport, "_do_http_call", http_call)

        result = transport._try_http_index_audit(
            PublicSourceType.CODE,
            9123,
            str(tmp_path),
            authority=RunAuthority.AUDIT_VERIFICATION,
        )

        assert result == {"ok": True}
        assert calls == [
            (
                9123,
                "/index/audit",
                {
                    "type": "code",
                    "authority": "audit_verification",
                    "project_root": str(tmp_path),
                },
            )
        ]

    def test_full_audit_transport_rejects_publication_before_http(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from .._source_types import PublicSourceType
        from ..indexer._run_ledger_models import RunAuthority
        from ..serviceclient import _transport as transport

        def forbidden_http(*_args: object, **_kwargs: object) -> typing.NoReturn:
            raise AssertionError("publication authority must not reach audit HTTP")

        monkeypatch.setattr(transport, "_do_http_call", forbidden_http)

        with pytest.raises(ValueError, match="audit-verification"):
            transport._try_http_index_audit(
                PublicSourceType.CODE,
                9123,
                str(tmp_path),
                authority=RunAuthority.PUBLICATION,
            )
