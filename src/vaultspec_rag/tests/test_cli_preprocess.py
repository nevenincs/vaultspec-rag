"""Unit tests for the ``preprocess`` CLI verb group (no GPU).

Exercises D13: ``list`` / ``check`` / ``run-one`` over a real tmp workspace with
a real ``.vaultragpreprocess.toml`` and a real extractor script (no mocks).
``check`` is the only hard-fail path (non-zero exit on an invalid config).
"""

from __future__ import annotations

import json
import shlex
import sys
import textwrap
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from ..cli import app

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


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
    assert "Timeout: no timeout" in result.output
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
