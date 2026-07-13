"""Unit tests for the ``preprocess`` CLI verb group (no GPU).

Exercises the inspection verbs (``list`` / ``check`` / ``run-one``, D13) plus the
trust-on-first-use surface (``trust`` / ``untrust`` / ``status`` and the
``server start`` mode flags, index-drift-hardening ADR D7/D8) over a real tmp
workspace with a real ``.vaultragpreprocess.toml`` and a real extractor script
(no mocks). The trust store is isolated to a per-test status dir via
``VAULTSPEC_RAG_STATUS_DIR`` because that is where the sidecar is written.
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
from ..cli._index import _apply_preprocess_env
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
    """Isolate the trust store and default the mode for the inspection verbs.

    The trust store writes under the managed status dir, so it is isolated to a
    per-test tmp path (``managed-singleton-paths-isolate-storage-dir-in-tests``
    sibling). ``trust_all`` is the default here so ``list`` / ``run-one`` see a
    root's rules without a per-root trust act - the tri-state equivalent of the
    removed enable knob. Tests that exercise the default (TOFU) or off modes call
    :func:`_default_mode` / :func:`_off_mode` to override.
    """
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    # Snapshot the mode keys before the test: the index/server-start flags
    # mutate os.environ in-process by design (the short-lived CLI contract),
    # and monkeypatch does not track mutations made by the command under test,
    # so teardown must force-restore both keys or an ``off`` set by one test
    # leaks into every later module (off wins over trust_all).
    mode_keys = (EnvVar.PREPROCESS.value, EnvVar.PREPROCESS_TRUST_ALL.value)
    snapshot = {key: os.environ.get(key) for key in mode_keys}
    monkeypatch.setenv(EnvVar.STATUS_DIR.value, str(status_dir))
    monkeypatch.setenv(EnvVar.PREPROCESS_TRUST_ALL.value, "1")
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


def _default_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the current test to the default (trust-on-first-use) mode."""
    monkeypatch.delenv(EnvVar.PREPROCESS_TRUST_ALL.value, raising=False)
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    reset_config()


def _off_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch the current test to the off (kill-switch) mode."""
    monkeypatch.delenv(EnvVar.PREPROCESS_TRUST_ALL.value, raising=False)
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
        ["preprocess", "trust", "--help"],
        ["preprocess", "untrust", "--help"],
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


def test_run_one_human_output_uses_plain_result_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    # Trusted default mode: the loader runs the rules without the trust-all
    # warning that would otherwise pollute the field-exact human output.
    _default_mode(monkeypatch)
    trust = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust", "--yes", "--json"]
    )
    assert trust.exit_code == 0, trust.output
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


# --- trust-on-first-use: status ------------------------------------------------


def test_status_untrusted_default_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _json(result.output)["data"]
    assert data["mode"] == "default"
    assert data["config_present"] is True
    assert data["rule_count"] == 1
    assert data["rule_set_hash"]
    assert data["trust_record_present"] is False
    assert data["trust_state"] == "absent"
    assert data["would_run"] is False


def test_status_no_config_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _json(result.output)["data"]
    assert data["config_present"] is False
    assert data["rule_count"] == 0
    assert data["trust_state"] == "not_applicable"
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


# --- trust-on-first-use: trust -------------------------------------------------


def test_trust_yes_persists_and_status_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)

    trust = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust", "--yes", "--json"]
    )
    assert trust.exit_code == 0, trust.output
    tdata = _json(trust.output)["data"]
    assert tdata["trusted"] is True
    assert tdata["rule_count"] == 1
    assert tdata["rule_set_hash"]
    assert tdata["trusted_at"]
    assert tdata["commands"][0]["pattern"] == "*.pdf"

    status = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert status.exit_code == 0, status.output
    sdata = _json(status.output)["data"]
    assert sdata["trust_state"] == "match"
    assert sdata["trusted_hash"] == tdata["rule_set_hash"]
    assert sdata["would_run"] is True


def test_trust_confirm_accepts_via_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert "Trusted 1 preprocess rule(s)" in result.output
    # The reviewable command set is printed before the prompt.
    assert "Files: *.pdf" in result.output
    assert "run with your privileges" in result.output


def test_trust_confirm_declined_does_not_persist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust"], input="n\n"
    )
    assert result.exit_code == 1
    assert "Trust cancelled." in result.output
    status = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert _json(status.output)["data"]["trust_state"] == "absent"


def test_trust_refuses_when_no_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust", "--yes", "--json"]
    )
    assert result.exit_code == 1
    envelope = _json(result.output)
    assert envelope["ok"] is False
    assert envelope["error"] == "no-rules"


def test_trust_json_requires_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust", "--json"]
    )
    assert result.exit_code == 2
    assert _json(result.output)["error"] == "json_requires_yes"


def test_trust_then_run_one_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    _default_mode(monkeypatch)

    # Untrusted: run-one reports the gated state with the trust remediation.
    gated = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )
    assert gated.exit_code == 0, gated.output
    gdata = _json(gated.output)["data"]
    assert gdata["matched"] is False
    assert gdata["gated"] is True
    assert gdata["mode"] == "default"

    trust = runner.invoke(
        app, ["--target", str(root), "preprocess", "trust", "--yes", "--json"]
    )
    assert trust.exit_code == 0, trust.output

    # Trusted: the same file now preprocesses.
    ran = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )
    assert ran.exit_code == 0, ran.output
    rdata = _json(ran.output)["data"]
    assert rdata["matched"] is True
    assert rdata["status"] == "ok"


def test_run_one_gated_human_message_names_trust_verb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf"]
    )
    assert result.exit_code == 0, result.output
    assert "not trusted" in result.output
    assert "preprocess trust" in result.output


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


# --- trust-on-first-use: untrust -----------------------------------------------


def test_untrust_removes_existing_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)
    runner.invoke(
        app, ["--target", str(root), "preprocess", "trust", "--yes", "--json"]
    )
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "untrust", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert _json(result.output)["data"]["removed"] is True
    status = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert _json(status.output)["data"]["trust_state"] == "absent"


def test_untrust_when_absent_reports_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _workspace(tmp_path)
    _config_with_rule(root)
    _default_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "untrust", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert _json(result.output)["data"]["removed"] is False


# --- server start mode flags ---------------------------------------------------


def test_server_start_preprocess_flags_conflict() -> None:
    result = runner.invoke(
        app,
        ["server", "start", "--no-preprocess", "--preprocess-trust-all", "--json"],
    )
    assert result.exit_code == 1
    envelope = _json(result.output)
    assert envelope["ok"] is False
    assert envelope["error"] == "preprocess_flags_conflict"


def test_child_env_forwards_no_preprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An inherited trust-all must be overridden by the forwarded off flag.
    monkeypatch.setenv(EnvVar.PREPROCESS_TRUST_ALL.value, "1")
    monkeypatch.delenv(EnvVar.PREPROCESS.value, raising=False)
    env = _service_child_env(preprocess_mode="off")
    assert env[EnvVar.PREPROCESS.value] == "off"
    assert EnvVar.PREPROCESS_TRUST_ALL.value not in env


def test_child_env_forwards_trust_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An inherited off must be overridden by the forwarded trust-all flag.
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    monkeypatch.delenv(EnvVar.PREPROCESS_TRUST_ALL.value, raising=False)
    env = _service_child_env(preprocess_mode="trust_all")
    assert env[EnvVar.PREPROCESS_TRUST_ALL.value] == "1"
    assert EnvVar.PREPROCESS.value not in env


def test_child_env_leaves_operator_preprocess_env_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No flag: an operator-set preprocess env survives into the daemon.
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    monkeypatch.delenv(EnvVar.PREPROCESS_TRUST_ALL.value, raising=False)
    env = _service_child_env(preprocess_mode=None)
    assert env[EnvVar.PREPROCESS.value] == "off"


def test_removed_enable_knob_is_gone() -> None:
    # The removed enable knob must not resurface: the enum no longer defines it,
    # so no code path can read or write VAULTSPEC_RAG_PREPROCESS_ENABLED.
    assert not hasattr(EnvVar, "PREPROCESS_ENABLED")
    assert all(member.value != "VAULTSPEC_RAG_PREPROCESS_ENABLED" for member in EnvVar)


# --- index verb mode flags -----------------------------------------------------


def test_index_preprocess_flags_conflict(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    result = runner.invoke(
        app,
        [
            "--target",
            str(root),
            "index",
            "--type",
            "code",
            "--no-preprocess",
            "--preprocess-trust-all",
            "--json",
        ],
    )
    assert result.exit_code == 2
    envelope = _json(result.output)
    assert envelope["ok"] is False
    assert envelope["error"] == "preprocess_flags_conflict"


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


def test_apply_preprocess_env_off_selects_off_mode() -> None:
    _apply_preprocess_env("off")
    assert os.environ[EnvVar.PREPROCESS.value] == "off"
    assert EnvVar.PREPROCESS_TRUST_ALL.value not in os.environ
    reset_config()
    assert get_config().preprocess_mode == "off"


def test_apply_preprocess_env_trust_all_selects_trust_all_mode() -> None:
    _apply_preprocess_env("trust_all")
    assert os.environ[EnvVar.PREPROCESS_TRUST_ALL.value] == "1"
    assert EnvVar.PREPROCESS.value not in os.environ
    reset_config()
    assert get_config().preprocess_mode == "trust_all"
