"""Unit tests for the command-form preprocessor runner (no GPU).

Exercises the runner's contract with a *real* subprocess: a tiny Python
extractor script is written to ``tmp_path`` and invoked through the runner.
No mocks - the runner
genuinely spawns the interpreter, so timeout, non-zero exit, bad JSON, oversize
emission, and the three ``on_error`` dispositions are all exercised end to end.
"""

import json
import shlex
import sys
import textwrap
from dataclasses import replace
from pathlib import Path

import pytest

from ..indexer._content_policy import ContentKind
from ..indexer._preprocess_config import OnError, PreprocessRule
from ..indexer._preprocess_runner import (
    PreprocessAbortError,
    PreprocessResult,
    _build_argv,
    _build_batch_argv,
    run_preprocessor,
)

pytestmark = [pytest.mark.unit]


def test_dash_leading_path_operand_is_neutralised() -> None:
    """CWE-88: a bare path operand beginning with - is prefixed with ./ so
    the child parses it as a path, not an option."""
    rule = PreprocessRule(
        pattern="*",
        command="extract {path}",
        entry_point=None,
        priority=100,
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
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
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
    )
    assert _build_argv(rule_embedded, Path("-x")) == ["extract", "--in=-x"]


def test_dash_leading_manifest_operand_is_neutralised() -> None:
    """The batch shape carries the same CWE-88 guarantee as the per-file one.

    Both shapes now share one substitution helper, so this asserts the batch
    caller actually reaches it. While they were separate functions with
    identical bodies, a fix to the per-file form above would have left this
    path silently exposed - and only the per-file form had a test.

    Mutation-proven: dropping the ``./`` guard in ``_substitute_operand``
    fails this on its own ``startswith("-")`` assertion.
    """
    rule = PreprocessRule(
        pattern="*",
        command="extract {paths}",
        entry_point=None,
        priority=100,
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
        on_error="skip",
        timeout_s=30.0,
        options={},
        order=0,
    )
    argv = _build_batch_argv(rule, "--output=owned")
    assert argv == ["extract", "./--output=owned"]
    assert not argv[-1].startswith("-")
    # An absolute manifest path (the normal case) is untouched.
    manifest = str(Path("/tmp/manifest.txt"))
    assert _build_batch_argv(rule, manifest)[-1] == manifest


_CAP = 1024 * 1024


def _run(
    source: Path,
    rule: PreprocessRule,
    *,
    max_emitted_bytes: int,
) -> PreprocessResult:
    """Invoke the runner directly against the original source path.

    The hook runs as a bounded, curated subprocess grandchild with the project
    root as cwd; here we exercise its timeout, exit-code, JSON, and cap logic.
    """
    return run_preprocessor(
        source,
        rule,
        max_emitted_bytes=max_emitted_bytes,
        project_root=source.parent,
    )


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
        target=ContentKind.DOCUMENT,
        extractor_version="1.0.0",
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
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "ok"
    assert result.output is not None
    assert result.output.units is not None
    assert result.output.units[0].text == "hello from page one"
    assert result.output.units[0].locator is not None
    assert result.output.units[0].locator.value == 1


_CWD_PROBE_BODY = """
    import json, os, sys
    print(json.dumps({
        "schema_version": 1,
        "preprocessor_id": "cwd-probe",
        "preprocessor_version": "1.0",
        "source_path": sys.argv[1],
        "text": os.getcwd(),
    }))
"""


def test_hook_runs_with_the_project_root_as_cwd(tmp_path: Path) -> None:
    # Project-launcher hook commands (uv run, npm exec, make) resolve their
    # project from the cwd, so the child runs with the project root as its
    # working directory - the same directory a hook author validates from with
    # preprocess run-one.
    script = _script(tmp_path, _CWD_PROBE_BODY)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.output is not None
    assert Path(result.output.text or "") == tmp_path


def test_hook_receives_the_original_source_path(tmp_path: Path) -> None:
    # With staging removed the hook is handed the ORIGINAL source path as its
    # argv operand and echoes it into source_path and the unit anchor, so deep
    # links reference the real file directly - no scratch copy, no remap.
    script = _script(tmp_path, _SUCCESS_BODY)
    source = tmp_path / "report.bin"
    source.write_bytes(b"\x00\x01binary")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.output is not None
    assert result.output.source_path == str(source)
    assert result.output.units is not None
    anchor = result.output.units[0].anchor
    assert anchor == f"{source}#page=1"
    # No scratch-dir leakage in any indexed path.
    assert "vsrag-hook-" not in result.output.source_path
    assert anchor is not None and "vsrag-hook-" not in anchor


def test_hook_receives_versioned_invocation_envelope(tmp_path: Path) -> None:
    body = """
        import json, os, sys
        envelope = json.loads(os.environ["VAULTSPEC_PREPROCESS_INVOCATION"])
        print(json.dumps({
            "schema_version": 1,
            "preprocessor_id": "envelope-probe",
            "preprocessor_version": envelope["extractor_version"],
            "source_path": sys.argv[1],
            "text": json.dumps(envelope, sort_keys=True),
        }))
    """
    script = _script(tmp_path, body)
    source = tmp_path / "report.bin"
    source.write_bytes(b"input")
    rule = replace(
        _rule(script),
        extractor_version="2.3.4",
        options={"locale": "en", "tables": True},
    )
    result = _run(source, rule, max_emitted_bytes=_CAP)
    assert result.output is not None
    envelope = json.loads(result.output.text or "")
    assert envelope == {
        "extractor_version": "2.3.4",
        "mode": "single",
        "options": {"locale": "en", "tables": True},
        "schema_version": 1,
        "source_paths": ["report.bin"],
        "target": "document",
    }


def test_hook_cannot_redirect_output_to_another_source(tmp_path: Path) -> None:
    body = """
        import json
        print(json.dumps({
            "schema_version": 1,
            "preprocessor_id": "redirect",
            "preprocessor_version": "1.0",
            "source_path": "another.bin",
            "text": "redirected",
        }))
    """
    script = _script(tmp_path, body)
    source = tmp_path / "report.bin"
    source.write_bytes(b"input")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "does not match invoked source" in result.reason


def test_nonzero_exit_is_skipped(tmp_path: Path) -> None:
    script = _script(tmp_path, "import sys\nsys.exit(3)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "exited 3" in result.reason


def test_bad_json_is_skipped(tmp_path: Path) -> None:
    script = _script(tmp_path, "print('this is not json')\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "not valid JSON" in result.reason


def test_schema_invalid_output_is_skipped(tmp_path: Path) -> None:
    body = "import json\nprint(json.dumps({'schema_version': 1}))\n"
    script = _script(tmp_path, body)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "skipped"


def test_timeout_is_skipped(tmp_path: Path) -> None:
    script = _script(tmp_path, "import time\ntime.sleep(5)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script, timeout_s=0.5), max_emitted_bytes=_CAP)
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
    result = _run(source, _rule(script), max_emitted_bytes=100)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "exceeds cap" in result.reason


def test_emitted_cap_measures_encoded_bytes(tmp_path: Path) -> None:
    body = """
        import json, sys
        print(json.dumps({
            "schema_version": 1,
            "preprocessor_id": "echo",
            "preprocessor_version": "1.0",
            "source_path": sys.argv[1],
            "text": "é" * 60,
        }))
    """
    script = _script(tmp_path, body)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=100)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "text bytes 120 exceeds cap 100" in result.reason


def test_oversize_stdout_is_bounded_and_skipped(tmp_path: Path) -> None:
    # Emit far more raw stdout than the cap allows; the bounded read must skip
    # without buffering it all (review PREPROCESS-003). cap=100 -> stdout cap
    # is max(100*4, 1MiB) = 1 MiB; emit ~3 MiB of non-JSON.
    body = "import sys\nsys.stdout.write('x' * (3 * 1024 * 1024))\n"
    script = _script(tmp_path, body)
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=100)
    assert result.status == "skipped"
    assert result.reason is not None
    assert "exceeds" in result.reason


def test_on_error_fail_raises_abort(tmp_path: Path) -> None:
    script = _script(tmp_path, "import sys\nsys.exit(1)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    with pytest.raises(PreprocessAbortError):
        _run(source, _rule(script, on_error="fail"), max_emitted_bytes=_CAP)


def test_on_error_passthrough_returns_passthrough(tmp_path: Path) -> None:
    script = _script(tmp_path, "import sys\nsys.exit(1)\n")
    source = tmp_path / "doc.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script, on_error="passthrough"), max_emitted_bytes=_CAP)
    assert result.status == "passthrough"
    assert result.output is None


def test_path_with_spaces_is_passed_as_single_arg(tmp_path: Path) -> None:
    script = _script(tmp_path, _SUCCESS_BODY)
    source = tmp_path / "a doc with spaces.bin"
    source.write_bytes(b"x")
    result = _run(source, _rule(script), max_emitted_bytes=_CAP)
    assert result.status == "ok"
    assert result.output is not None
    # A single argv element (not split on the spaces) proves the path was passed
    # intact through shlex token-wise substitution; the hook echoes the full
    # original path back.
    assert result.output.source_path is not None
    assert result.output.source_path == str(source)
