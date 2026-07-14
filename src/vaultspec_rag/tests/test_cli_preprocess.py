"""Unit tests for the ``preprocess`` CLI verb group (no GPU).

Exercises the inspection verbs (``list`` / ``check`` / ``run-one``, D13) plus the
amended ``status`` surface and the ``server start`` / ``index`` ``--no-preprocess``
flag over a real tmp workspace with a real ``.vaultragpreprocess.toml`` and a real
extractor script (no mocks). The OS sandbox and its ``--preprocess-unsandboxed``
escape hatch were removed (preprocess-sandbox-removal ADR): rules resolve for any
root and run directly, gated only by the ``off`` kill switch.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._index import _apply_preprocess_off_env
from ..cli._process import _service_child_env
from ..config import EnvVar, get_config, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _preprocess_env(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Isolate the status dir and resolve the ``default`` mode.

    The managed status dir is isolated to a per-test tmp path
    (``managed-singleton-paths-isolate-storage-dir-in-tests`` sibling). Clearing
    the mode env var leaves the resolved mode at ``default``, so ``list`` /
    ``run-one`` see a root's rules for any root - no per-root trust act. The
    off-mode tests call :func:`_off_mode` to override.
    """
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    # Snapshot the mode key before the test: the index/server-start flag mutates
    # os.environ in-process by design (the short-lived CLI contract), and
    # monkeypatch does not track mutations made by the command under test, so
    # teardown must force-restore the key or an ``off`` set by one test leaks
    # into every later module (off wins over the default).
    snapshot = {EnvVar.PREPROCESS.value: os.environ.get(EnvVar.PREPROCESS.value)}
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status_dir))
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    reset_config()
    try:
        yield
    finally:
        for key, prev in snapshot.items():
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev
        reset_config()


def _off_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the current test to the off (kill-switch) mode."""
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    reset_config()


def _workspace(tmp_path: Path) -> Path:
    (tmp_path / ".vault").mkdir()
    (tmp_path / ".vaultspec").mkdir()
    return tmp_path


def _write_extractor(root: Path) -> Path:
    script = root / "extractor.py"
    script.write_text(
        textwrap.dedent("""
            import json, sys
            src = sys.argv[1]
            print(json.dumps({
                "schema_version": 1,
                "preprocessor_id": "fake",
                "preprocessor_version": "1.0",
                "source_path": src,
                "units": [{"text": "extracted body",
                           "anchor": src + "#page=1",
                           "locator": {"kind": "page", "value": 1}}],
            }))
        """),
        encoding="utf-8",
    )
    return script


def _config_with_rule(root: Path) -> None:
    script = _write_extractor(root)
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"
    # TOML triple-single-quoted literal: backslashes in Windows paths are not
    # escape sequences and the embedded single quotes from shlex.quote are safe.
    body = (
        '[[rule]]\npattern = "*.pdf"\n'
        f"command = '''{command}'''\n"
        'on_error = "skip"\n'
    )
    (root / ".vaultragpreprocess.toml").write_text(body, encoding="utf-8")


def _json(output: str) -> dict[str, Any]:
    # The runner may mix a stray log line into the captured output; the JSON
    # envelope is the last line that parses as an object.
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    msg = f"no JSON envelope in output: {output!r}"
    raise AssertionError(msg)


def _human_fields(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in output.splitlines():
        if not line.strip():
            continue
        label, sep, value = line.partition(": ")
        assert sep, f"expected labeled CLI line, got {line!r}"
        fields[label] = value
    return fields


@pytest.mark.parametrize(
    "argv",
    [
        ["preprocess", "list", "--help"],
        ["preprocess", "check", "--help"],
        ["preprocess", "run-one", "--help"],
        ["preprocess", "status", "--help"],
    ],
)
def test_preprocess_json_help_uses_script_language(argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert "Emit JSON for scripts" in result.output
    assert "JSON envelope" not in result.output
    assert "non-zero" not in result.output.lower()
    if argv[:2] == ["preprocess", "check"]:
        assert "report configuration problems" in result.output


def test_trust_verbs_are_removed() -> None:
    # The trust/untrust verbs were deleted (ADR D7); no such subcommands exist.
    for verb in ("trust", "untrust"):
        result = runner.invoke(app, ["preprocess", verb, "--help"])
        assert result.exit_code != 0


def test_list_empty(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "list", "--json"])
    assert result.exit_code == 0
    assert _json(result.output)["data"]["rules"] == []


def test_list_shows_rule(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "list", "--json"])
    assert result.exit_code == 0
    rules = _json(result.output)["data"]["rules"]
    assert len(rules) == 1
    assert rules[0]["pattern"] == "*.pdf"
    assert rules[0]["on_error"] == "skip"


def test_list_human_output_uses_plain_labels(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "list"])
    assert result.exit_code == 0
    assert "Preprocess rules: 1" in result.output
    assert "Files: *.pdf" in result.output
    assert "Failure handling: skip file on failure" in result.output
    # H1: an omitted timeout_s now resolves to the bounded default, not "none".
    assert "Timeout: 120s" in result.output
    assert "Command:" in result.output
    assert "pattern=" not in result.output
    assert "on_error" not in result.output
    assert "timeout_s" not in result.output


def test_check_valid(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "check", "--json"]
    )
    assert result.exit_code == 0
    data = _json(result.output)["data"]
    assert data["valid"] is True
    assert data["rule_count"] == 1


def test_check_valid_human_output_is_user_facing(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "check"])
    assert result.exit_code == 0
    assert "Preprocess config is valid: 1 rule." in result.output
    assert "OK -" not in result.output
    assert "rule(s)" not in result.output


def test_check_valid_zero_rules_uses_plain_absence_language(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "check"])

    assert result.exit_code == 0, result.output
    assert (
        "Preprocess config is valid. No preprocess rules configured." in result.output
    )
    assert "0 rules" not in result.output
    assert "rule(s)" not in result.output


def test_check_invalid_exits_nonzero(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    (root / ".vaultragpreprocess.toml").write_text(
        "not = = valid [[[", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "check", "--json"]
    )
    assert result.exit_code == 1
    assert _json(result.output)["ok"] is False


def test_check_invalid_rule_exits_nonzero(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    # A rule with neither command nor entry_point is invalid.
    (root / ".vaultragpreprocess.toml").write_text(
        '[[rule]]\npattern = "*.pdf"\non_error = "skip"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["--target", str(root), "preprocess", "check"])
    assert result.exit_code == 1


def test_run_one_no_match(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "notes.txt", "--json"]
    )
    assert result.exit_code == 0
    assert _json(result.output)["data"]["matched"] is False


def test_run_one_matches_and_runs(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )
    assert result.exit_code == 0
    data = _json(result.output)["data"]
    assert data["matched"] is True
    assert data["status"] == "ok"
    assert data["unit_count"] == 1
    assert data["output"]["preprocessor_id"] == "fake"


def test_run_one_human_output_uses_plain_result_language(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    # Default mode resolves the rules for any root - no trust act is needed, and
    # no warning pollutes the field-exact human output.
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf"]
    )
    assert result.exit_code == 0
    fields = _human_fields(result.output)
    assert fields == {
        "Matched rule": "*.pdf",
        "Outcome": "preprocessed",
        "Preprocessor": "fake 1.0",
        "Output": "1 extracted text section",
    }


def test_run_one_gated_off_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    _off_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf"]
    )
    assert result.exit_code == 0, result.output
    assert "Preprocessing is off" in result.output


def test_run_one_gated_off_json_reports_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    _off_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _json(result.output)["data"]
    assert data["matched"] is False
    assert data["gated"] is True
    assert data["mode"] == "off"


# --- status --------------------------------------------------------------------


def test_status_default_mode_reports_would_run(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _json(result.output)["data"]
    assert data["mode"] == "default"
    assert data["config_present"] is True
    assert data["config_valid"] is True
    assert data["rule_count"] == 1
    assert data["would_run"] is True
    # The removed sandbox and trust surfaces must not resurface in the envelope.
    assert "sandbox_backend" not in data
    assert "trust_state" not in data
    assert "rule_set_hash" not in data


def test_status_no_config_reports_no_rules(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _json(result.output)["data"]
    assert data["config_present"] is False
    assert data["rule_count"] == 0
    assert data["would_run"] is False


def test_status_off_mode_reports_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _off_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _json(result.output)["data"]
    assert data["mode"] == "off"
    assert data["rule_count"] == 1
    assert data["would_run"] is False


def test_status_human_output_reports_direct_execution(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "status"])
    assert result.exit_code == 0, result.output
    assert "Preprocess mode: default" in result.output
    assert "Rules: 1" in result.output
    # The effect line now states direct execution, not a sandbox backend.
    assert "run directly" in result.output
    assert "Sandbox:" not in result.output


# --- server start mode flags ---------------------------------------------------


def test_server_start_rejects_removed_unsandboxed_flag() -> None:
    # The --preprocess-unsandboxed escape hatch was removed; the parser must
    # reject it as an unknown option rather than accept it.
    result = runner.invoke(
        app,
        ["server", "start", "--preprocess-unsandboxed", "--json"],
    )
    assert result.exit_code == 2


def test_child_env_forwards_no_preprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The forwarded off flag sets the kill switch in the daemon env.
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    env = _service_child_env(preprocess_mode="off")
    assert env[EnvVar.PREPROCESS.value] == "off"


def test_child_env_leaves_operator_preprocess_env_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No flag: an operator-set preprocess env survives into the daemon.
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    env = _service_child_env(preprocess_mode=None)
    assert env[EnvVar.PREPROCESS.value] == "off"


def test_removed_enable_knob_is_gone() -> None:
    # The removed enable knob must not resurface: the enum no longer defines it,
    # so no code path can read or write VAULTSPEC_RAG_PREPROCESS_ENABLED.
    assert not hasattr(EnvVar, "PREPROCESS_ENABLED")
    assert all(member.value != "VAULTSPEC_RAG_PREPROCESS_ENABLED" for member in EnvVar)


def test_removed_trust_all_knob_is_gone() -> None:
    # The retired trust-all knob must not resurface (ADR D8).
    assert not hasattr(EnvVar, "PREPROCESS_TRUST_ALL")
    assert all(
        member.value != "VAULTSPEC_RAG_PREPROCESS_TRUST_ALL" for member in EnvVar
    )


# --- index verb mode flags -----------------------------------------------------


def test_index_rejects_removed_unsandboxed_flag(tmp_path: Path) -> None:
    # The --preprocess-unsandboxed escape hatch was removed from `index`; the
    # parser must reject it as an unknown option.
    root = _workspace(tmp_path)
    result = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "index",
            "--type",
            "code",
            "--preprocess-unsandboxed",
            "--json",
        ],
    )
    assert result.exit_code == 2


def test_index_preprocess_flag_warns_when_service_targeted(tmp_path: Path) -> None:
    # An explicit --port means a service will handle the index. The in-process
    # flag does not apply to a delegated run, so the CLI warns loudly (rather
    # than silently accepting it) and still proceeds to delegation - which then
    # fails against the unreachable fake port (exit 1, no fallback).
    root = _workspace(tmp_path)
    result = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "index",
            "--type",
            "code",
            "--port",
            "9999",
            "--no-preprocess",
        ],
    )
    assert result.exit_code == 1
    assert "does not apply to a delegated index run" in result.output


def test_apply_preprocess_off_env_selects_off_mode() -> None:
    _apply_preprocess_off_env()
    assert os.environ[EnvVar.PREPROCESS.value] == "off"
    reset_config()
    assert get_config().preprocess_mode == "off"
