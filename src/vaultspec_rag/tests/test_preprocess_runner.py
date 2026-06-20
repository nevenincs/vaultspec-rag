"""Unit tests for the command-form preprocessor runner (no GPU).

Exercises D6/D9/D10 with a *real* subprocess: a tiny Python extractor script is
written to ``tmp_path`` and invoked through the runner. No mocks - the runner
genuinely spawns the interpreter, so timeout, non-zero exit, bad JSON, oversize
emission, and the three ``on_error`` dispositions are all exercised end to end.
"""

import shlex
import sys
import textwrap
from pathlib import Path

import pytest

from ..indexer._preprocess_config import OnError, PreprocessRule
from ..indexer._preprocess_runner import (
    PreprocessAbortError,
    _build_argv,
    run_preprocessor,
)

pytestmark = [pytest.mark.unit]


def test_dash_leading_path_operand_is_neutralised() -> None:
    """H2 (CWE-88): a bare path operand beginning with - is prefixed with ./ so
    the child parses it as a path, not an option."""
    rule = PreprocessRule(
        pattern="*",
        command="extract {path}",
        entry_point=None,
        priority=100,
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
    )
    argv = _build_argv(rule, Path("-rf.pdf"))
    assert argv == ["extract", "./-rf.pdf"]
    # An absolute path (the normal case) is untouched (no ./ prefix).
    argv_abs = _build_argv(rule, Path("/tmp/-rf.pdf"))
    assert argv_abs[-1] == str(Path("/tmp/-rf.pdf"))
    assert not argv_abs[-1].startswith("./")
    # An embedded (non-standalone) substitution is not mangled.
    rule_embedded = PreprocessRule(
        pattern="*",
        command="extract --in={path}",
        entry_point=None,
        priority=100,
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
    )
    assert _build_argv(rule_embedded, Path("-x")) == ["extract", "--in=-x"]


_CAP = 1024 * 1024


def _script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "extractor.py"
    script.write_text(textwrap.dedent(body), encoding="utf-8")
    return script


def _rule(
    script: Path,
    *,
    on_error: OnError = "skip",
    timeout_s: float | None = 30.0,
) -> PreprocessRule:
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} {{path}}"
    return PreprocessRule(
        pattern="*.bin",
        command=command,
        entry_point=None,
        priority=100,
        on_error=on_error,
        timeout_s=timeout_s,
        options={},
        order=0,
    )


_SUCCESS_BODY = """
    import json, sys
    src = sys.argv[1]
    print(json.dumps({
        "schema_version": 1,
        "preprocessor_id": "echo",
        "preprocessor_version": "1.0",
        "source_path": src,
        "units": [
            {"text": "hello from page one",
             "anchor": src + "#page=1",
             "locator": {"kind": "page", "value": 1}},
        ],
    }))
"""


def test_success_returns_validated_output(tmp_path: Path) -> None:
    script = _script(tmp_path, _SUCCESS_BODY)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"\x00\x01binary")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "ok"
    assert result.output is not None
    assert result.output.units is not None
    assert result.output.units[0].text == "hello from page one"
    assert result.output.units[0].locator is not None
    assert result.output.units[0].locator.value == 1


def test_nonzero_exit_is_skipped(tmp_path: Path) -> None:
    script = _script(tmp_path, "import sys\nsys.exit(3)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "exited 3" in result.reason


def test_bad_json_is_skipped(tmp_path: Path) -> None:
    script = _script(tmp_path, "print('this is not json')\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "not valid JSON" in result.reason


def test_schema_invalid_output_is_skipped(tmp_path: Path) -> None:
    body = "import json\nprint(json.dumps({'schema_version': 1}))\n"
    script = _script(tmp_path, body)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"


def test_timeout_is_skipped(tmp_path: Path) -> None:
    script = _script(tmp_path, "import time\ntime.sleep(5)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(
        source, _rule(script, timeout_s=0.5), max_emitted_bytes=_CAP
    )
    assert result.status == "skipped"
    assert result.reason is not None
    assert "timed out" in result.reason


def test_oversize_emission_is_skipped(tmp_path: Path) -> None:
    body = """
        import json, sys
        print(json.dumps({
            "schema_version": 1,
            "preprocessor_id": "echo",
            "preprocessor_version": "1.0",
            "source_path": sys.argv[1],
            "text": "x" * 5000,
        }))
    """
    script = _script(tmp_path, body)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=100)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "exceeds cap" in result.reason


def test_oversize_stdout_is_bounded_and_skipped(tmp_path: Path) -> None:
    # Emit far more raw stdout than the cap allows; the bounded read must skip
    # without buffering it all (review PREPROCESS-003). cap=100 -> stdout cap
    # is max(100*4, 1MiB) = 1 MiB; emit ~3 MiB of non-JSON.
    body = "import sys\nsys.stdout.write('x' * (3 * 1024 * 1024))\n"
    script = _script(tmp_path, body)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=100)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "exceeds" in result.reason


def test_on_error_fail_raises_abort(tmp_path: Path) -> None:
    script = _script(tmp_path, "import sys\nsys.exit(1)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    with pytest.raises(PreprocessAbortError):
        run_preprocessor(source, _rule(script, on_error="fail"), max_emitted_bytes=_CAP)


def test_on_error_passthrough_returns_passthrough(tmp_path: Path) -> None:
    script = _script(tmp_path, "import sys\nsys.exit(1)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(
        source, _rule(script, on_error="passthrough"), max_emitted_bytes=_CAP
    )
    assert result.status == "passthrough"
    assert result.output is None


def test_path_with_spaces_is_passed_as_single_arg(tmp_path: Path) -> None:
    script = _script(tmp_path, _SUCCESS_BODY)
    source = tmp_path / "a doc with spaces.bin"
    source.write_bytes(b"x")
    result = run_preprocessor(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "ok"
    assert result.output is not None
    assert result.output.source_path == str(source)
