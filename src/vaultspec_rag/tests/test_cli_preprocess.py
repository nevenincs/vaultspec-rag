"""Unit tests for the ``preprocess`` CLI verb group (no GPU).

Exercises the inspection verbs (``list`` / ``check`` / ``run-one``), the
``approve`` / ``revoke`` verbs, the ``status`` surface and the ``server start``
/ ``index`` ``--no-preprocess`` flag over a real tmp workspace with a real
``.vaultragpreprocess.toml`` and a real extractor script (no mocks). Rules
resolve for any root; they run directly, with no sandbox, once the operator
has approved the root's exact policy and the ``off`` kill switch is not thrown.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING, cast

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..cli._index import _apply_preprocess_off_env
from ..cli._process import _build_service_child_env, _ServiceChildEnvRequest
from ..cli._service_start import _print_preprocess_start_notice
from ..config._settings import get_config
from ..config._types import EnvVar
from ._config_fixtures import reset_config
from ._preprocess_approval import approve_preprocess_policy
from ._scaffold import make_workspace

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

    The managed status dir is isolated to a per-test tmp path, so each test
    starts with an empty approval store. Clearing the mode env var leaves the
    resolved mode at ``default``. The off-mode tests call :func:`_off_mode` to
    override.
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
        'version = 2\n\n[[rule]]\npattern = "*.pdf"\n'
        'target = "document"\n'
        'extractor_version = "1.0.0"\n'
        f"command = '''{command}'''\n"
        'on_error = "skip"\n'
    )
    (root / ".vaultragpreprocess.toml").write_text(body, encoding="utf-8")


def _sentinel_rule(root: Path) -> Path:
    """Write a rule whose extractor proves it ran by creating a sentinel file."""
    sentinel = root / "EXECUTED.flag"
    script = root / "sentinel_extractor.py"
    script.write_text(
        textwrap.dedent(f"""
            import json, pathlib, sys
            pathlib.Path({str(sentinel)!r}).write_text("executed")
            print(json.dumps({{
                "schema_version": 1,
                "preprocessor_id": "sentinel",
                "preprocessor_version": "1.0",
                "source_path": sys.argv[1],
                "units": [{{"text": "sentinel output"}}],
            }}))
        """),
        encoding="utf-8",
    )
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"
    (root / ".vaultragpreprocess.toml").write_text(
        'version = 2\n\n[[rule]]\npattern = "*.pdf"\n'
        'target = "document"\n'
        'extractor_version = "1.0.0"\n'
        f"command = '''{command}'''\n"
        'on_error = "skip"\n',
        encoding="utf-8",
    )
    return sentinel


def _json(output: str) -> dict[str, object]:
    # The runner may mix a stray log line into the captured output; the JSON
    # envelope is the last line that parses as an object.
    for line in reversed(output.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return cast("dict[str, object]", json.loads(line))
    msg = f"no JSON envelope in output: {output!r}"
    raise AssertionError(msg)


def _data(payload: dict[str, object]) -> dict[str, object]:
    """Return the ``data`` block a preprocess envelope carries."""
    return cast("dict[str, object]", payload["data"])


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
        ["preprocess", "approve", "--help"],
        ["preprocess", "revoke", "--help"],
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


# --- approve / revoke ----------------------------------------------------------


def test_approve_records_the_policy_and_reports_what_it_runs(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "approve", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["status"] == "approved"
    assert data["rule_count"] == 1
    assert str(data["policy_digest"]).startswith("sha256:")
    rules = cast("list[dict[str, object]]", data["rules"])
    assert rules[0]["pattern"] == "*.pdf"
    assert "extractor.py" in str(rules[0]["invocation"])

    status = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    status_data = _data(_json(status.output))
    assert status_data["approved"] is True
    assert status_data["policy_digest"] == data["policy_digest"]
    assert status_data["hooks"] == "active"
    assert status_data["would_run"] is True


def test_approve_human_output_shows_the_commands_and_the_next_step(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)

    result = runner.invoke(app, ["--target", str(root), "preprocess", "approve"])

    assert result.exit_code == 0, result.output
    assert "Approved: 1 preprocess rule for" in result.output
    assert "Files: *.pdf" in result.output
    assert "Invocation:" in result.output
    assert "Policy digest: sha256:" in result.output
    assert "needs approval again" in result.output
    assert "vaultspec-rag index" in result.output


def test_approve_is_idempotent(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    args = ["--target", str(root), "preprocess", "approve", "--json"]

    first = _data(_json(runner.invoke(app, args).output))
    second_result = runner.invoke(app, args)

    assert second_result.exit_code == 0, second_result.output
    second = _data(_json(second_result.output))
    assert first["status"] == "approved"
    assert second["status"] == "already_approved"
    assert second["policy_digest"] == first["policy_digest"]


def test_approve_without_rules_has_nothing_to_approve(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "approve", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["status"] == "no_rules"
    assert data["policy_digest"] is None


def test_approve_refuses_an_invalid_config(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    (root / ".vaultragpreprocess.toml").write_text(
        "not = = valid [[[", encoding="utf-8"
    )

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "approve", "--json"]
    )

    assert result.exit_code == 1
    assert _json(result.output)["ok"] is False


def test_revoke_withdraws_an_approval(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    approve_preprocess_policy(root)

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "revoke", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert _data(_json(result.output))["status"] == "revoked"
    status = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    status_data = _data(_json(status.output))
    assert status_data["approved"] is False
    assert status_data["hooks"] == "unapproved"


def test_revoke_of_an_unapproved_root_is_already_done(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "revoke", "--json"]
    )

    assert result.exit_code == 0, result.output
    assert _data(_json(result.output))["status"] == "not_approved"


def test_list_empty(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "list", "--json"])
    assert result.exit_code == 0
    assert _data(_json(result.output))["rules"] == []


def test_list_shows_rule(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "list", "--json"])
    assert result.exit_code == 0
    rules = cast("list[dict[str, object]]", _data(_json(result.output))["rules"])
    assert len(rules) == 1
    assert rules[0]["pattern"] == "*.pdf"
    assert rules[0]["on_error"] == "skip"
    assert rules[0]["target"] == "document"
    assert rules[0]["extractor_version"] == "1.0.0"
    assert rules[0]["path_independent"] is False


def test_list_human_output_uses_plain_labels(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "list"])
    assert result.exit_code == 0
    assert "Preprocess rules: 1" in result.output
    assert "Files: *.pdf" in result.output
    assert "Failure handling: skip file on failure" in result.output
    # An omitted timeout_s now resolves to the bounded default, not "none".
    assert "Timeout: 120s" in result.output
    assert "Target: document" in result.output
    assert "Extractor version: 1.0.0" in result.output
    assert "Cross-path cache reuse: disabled" in result.output
    assert "Invocation:" in result.output
    assert "pattern=" not in result.output
    assert "on_error" not in result.output
    assert "timeout_s" not in result.output


def test_check_valid(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "check", "--json"]
    )
    assert result.exit_code == 0
    data = _data(_json(result.output))
    assert data["valid"] is True
    assert data["rule_count"] == 1
    assert data["schema_version"] == 2
    assert data["targets"] == ["document"]
    assert data["extractor_versions"] == ["1.0.0"]
    assert data["path_independent_rules"] == 0


def test_check_valid_human_output_is_user_facing(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "check"])
    assert result.exit_code == 0
    assert "Preprocess config is valid: 1 rule." in result.output
    assert "OK -" not in result.output
    assert "rule(s)" not in result.output


def test_check_valid_zero_rules_uses_plain_absence_language(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "check"])

    assert result.exit_code == 0, result.output
    assert (
        "Preprocess config is valid. No preprocess rules configured." in result.output
    )
    assert "0 rules" not in result.output
    assert "rule(s)" not in result.output


def test_check_invalid_exits_nonzero(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    (root / ".vaultragpreprocess.toml").write_text(
        "not = = valid [[[", encoding="utf-8"
    )
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "check", "--json"]
    )
    assert result.exit_code == 1
    assert _json(result.output)["ok"] is False


def test_check_invalid_rule_exits_nonzero(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    # A rule with neither command nor entry_point is invalid.
    (root / ".vaultragpreprocess.toml").write_text(
        '[[rule]]\npattern = "*.pdf"\non_error = "skip"\n', encoding="utf-8"
    )
    result = runner.invoke(app, ["--target", str(root), "preprocess", "check"])
    assert result.exit_code == 1


def test_run_one_no_match(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    approve_preprocess_policy(root)
    (root / "notes.txt").write_text("hello", encoding="utf-8")
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "notes.txt", "--json"]
    )
    assert result.exit_code == 0
    data = _data(_json(result.output))
    assert data["matched"] is False
    assert "gated" not in data


def test_run_one_matches_and_runs(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    approve_preprocess_policy(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )
    assert result.exit_code == 0
    data = _data(_json(result.output))
    assert data["matched"] is True
    assert data["status"] == "ok"
    assert data["unit_count"] == 1
    assert cast("dict[str, object]", data["output"])["preprocessor_id"] == "fake"


def test_run_one_human_output_uses_plain_result_language(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    approve_preprocess_policy(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    # An approved root's rule runs, and no warning pollutes the field-exact
    # human output.
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
    root = make_workspace(tmp_path)
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
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    _off_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["matched"] is False
    assert data["gated"] is True
    assert data["mode"] == "off"
    assert data["hooks"] == "disabled"


def test_run_one_does_not_execute_an_unapproved_rule(tmp_path: Path) -> None:
    """The authoring verb obeys the same gate as indexing.

    Mutation check: skipping the hook-state gate in ``run-one`` creates the
    sentinel and fails here on its absence; restoring the gate passes.
    """
    root = make_workspace(tmp_path)
    sentinel = _sentinel_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert not sentinel.exists()
    assert data["matched"] is False
    assert data["gated"] is True
    assert data["mode"] == "default"
    assert data["hooks"] == "unapproved"
    assert data["rule_count"] == 1


def test_run_one_runs_once_the_rule_is_approved_and_stops_when_it_changes(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    sentinel = _sentinel_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")
    args = ["--target", str(root), "preprocess", "run-one", "report.pdf", "--json"]

    approve = runner.invoke(app, ["--target", str(root), "preprocess", "approve"])
    assert approve.exit_code == 0, approve.output
    ran = runner.invoke(app, args)
    assert _data(_json(ran.output))["matched"] is True
    assert sentinel.exists()

    sentinel.unlink()
    config = root / ".vaultragpreprocess.toml"
    config.write_text(
        config.read_text(encoding="utf-8") + "timeout_s = 30\n", encoding="utf-8"
    )
    held = runner.invoke(app, args)
    assert not sentinel.exists()
    assert _data(_json(held.output)).get("hooks") == "unapproved"


def test_run_one_unapproved_message_names_the_approval_command(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    (root / "report.pdf").write_bytes(b"\x00\x01binary")

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "run-one", "report.pdf"]
    )

    assert result.exit_code == 0, result.output
    assert "Preprocess rules are not approved" in result.output
    assert "vaultspec-rag preprocess approve" in result.output


# --- status --------------------------------------------------------------------


def test_status_reports_an_unapproved_root_will_not_run(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)

    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )

    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["mode"] == "default"
    assert data["rule_count"] == 1
    assert data["approved"] is False
    assert str(data["policy_digest"]).startswith("sha256:")
    assert data["hooks"] == "unapproved"
    assert data["would_run"] is False


def test_status_human_output_tells_an_unapproved_root_how_to_approve(
    tmp_path: Path,
) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)

    result = runner.invoke(app, ["--target", str(root), "preprocess", "status"])

    assert result.exit_code == 0, result.output
    assert "Approval: not approved" in result.output
    assert "configured but not approved" in result.output
    assert "vaultspec-rag preprocess approve" in result.output


def test_status_default_mode_reports_would_run(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    approve_preprocess_policy(root)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["mode"] == "default"
    assert data["config_present"] is True
    assert data["config_valid"] is True
    assert data["rule_count"] == 1
    assert data["schema_version"] == 2
    assert data["targets"] == ["document"]
    assert data["extractor_versions"] == ["1.0.0"]
    assert data["path_independent_rules"] == 0
    assert data["approved"] is True
    assert data["hooks"] == "active"
    assert data["would_run"] is True
    # The removed sandbox surface must not resurface in the envelope.
    assert "sandbox_backend" not in data


def test_status_no_config_reports_no_rules(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["config_present"] is False
    assert data["rule_count"] == 0
    assert data["schema_version"] is None
    assert data["would_run"] is False


def test_status_off_mode_reports_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    _off_mode(monkeypatch)
    result = runner.invoke(
        app, ["--target", str(root), "preprocess", "status", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = _data(_json(result.output))
    assert data["mode"] == "off"
    assert data["rule_count"] == 1
    assert data["would_run"] is False


def test_status_human_output_reports_direct_execution(tmp_path: Path) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    approve_preprocess_policy(root)
    result = runner.invoke(app, ["--target", str(root), "preprocess", "status"])
    assert result.exit_code == 0, result.output
    assert "Preprocess mode: default" in result.output
    assert "Rules: 1" in result.output
    assert "Approval: approved" in result.output
    # The effect line now states direct execution, not a sandbox backend.
    assert "run directly" in result.output
    assert "Sandbox:" not in result.output


# --- server start notice -------------------------------------------------------


@pytest.mark.parametrize(
    ("approved", "mode", "expected"),
    [
        (True, "default", "will run; their commands execute"),
        (False, "default", "will be skipped (not approved)"),
        (True, "off", "will be skipped (mode is off)"),
    ],
)
def test_server_start_notice_says_whether_the_root_hooks_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    approved: bool,
    mode: str,
    expected: str,
) -> None:
    root = make_workspace(tmp_path)
    _config_with_rule(root)
    if approved:
        approve_preprocess_policy(root)

    _print_preprocess_start_notice(root, mode)

    # The notice is prose that may wrap at the console width; the command in
    # its remedy is on a line of its own and must survive whole.
    captured = capsys.readouterr().out
    assert expected in " ".join(captured.split())
    names_the_approval_command = "vaultspec-rag preprocess approve" in captured
    assert names_the_approval_command is (not approved)


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
    env = _build_service_child_env(_ServiceChildEnvRequest(preprocess_mode="off"))
    assert env[EnvVar.PREPROCESS.value] == "off"


def test_child_env_leaves_operator_preprocess_env_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No flag: an operator-set preprocess env survives into the daemon.
    monkeypatch.setenv(EnvVar.PREPROCESS.value, "off")
    env = _build_service_child_env(_ServiceChildEnvRequest(preprocess_mode=None))
    assert env[EnvVar.PREPROCESS.value] == "off"


def test_removed_enable_knob_is_gone() -> None:
    # The removed enable knob must not resurface: the enum no longer defines it,
    # so no code path can read or write VAULTSPEC_RAG_PREPROCESS_ENABLED.
    assert not hasattr(EnvVar, "PREPROCESS_ENABLED")
    assert all(member.value != "VAULTSPEC_RAG_PREPROCESS_ENABLED" for member in EnvVar)


def test_removed_trust_all_knob_is_gone() -> None:
    # The retired trust-all knob must not resurface.
    assert not hasattr(EnvVar, "PREPROCESS_TRUST_ALL")
    assert all(
        member.value != "VAULTSPEC_RAG_PREPROCESS_TRUST_ALL" for member in EnvVar
    )


# --- index verb mode flags -----------------------------------------------------


def test_index_rejects_removed_unsandboxed_flag(tmp_path: Path) -> None:
    # The --preprocess-unsandboxed escape hatch was removed from `index`; the
    # parser must reject it as an unknown option.
    root = make_workspace(tmp_path)
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
    root = make_workspace(tmp_path)
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
