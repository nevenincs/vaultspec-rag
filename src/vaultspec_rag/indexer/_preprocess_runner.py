"""Command-form preprocessor execution (the runtime side of the hook).

Runs a project-supplied ``command`` rule against one source file in a
``subprocess.run`` grandchild, parses and validates its stdout JSON against the
:mod:`._preprocess_schema` contract, enforces the emitted-text cap, and maps the
outcome onto the rule's ``on_error`` disposition (D6, D9, D10).

Running the real extraction in a separate OS process is what makes the command
form CPU-only-safe *by construction*: the child has its own interpreter and
cannot pollute the spawn worker's import chain or CUDA state, satisfying the
``index-workers-stay-cpu-only`` rule without any trust assumptions. The command
is split with :func:`shlex.split` and the ``{path}`` placeholder is substituted
token-wise (never via a shell), so source paths with spaces or shell
metacharacters cannot inject.
"""

from __future__ import annotations

import json
import logging
import shlex
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal

from pydantic import ValidationError

from ._preprocess_schema import (
    PreprocOutput,
    UnsupportedSchemaVersionError,
    validate_preproc_output,
)

if TYPE_CHECKING:
    import pathlib

    from ._preprocess_config import PreprocessRule

logger = logging.getLogger(__name__)

#: Module path of the out-of-process entry-point runner (#185 follow-up).
_ENTRY_RUNNER_MODULE = "vaultspec_rag.indexer._preprocess_entry"

#: Raw stdout is captured up to this multiple of the emitted-text cap, leaving
#: headroom for JSON structure while bounding peak memory so a runaway extractor
#: cannot OOM the worker before the emitted-size cap fires (review PREPROCESS-003).
_STDOUT_CAP_MULTIPLIER = 4
_MIN_STDOUT_CAP = 1024 * 1024
#: Hard ceiling on captured stderr so a flooding child cannot OOM us either.
_STDERR_CAP = 64 * 1024

__all__ = [
    "PreprocessAbortError",
    "PreprocessResult",
    "PreprocessStatus",
    "run_preprocessor",
]

PreprocessStatus = Literal["ok", "skipped", "passthrough"]


class PreprocessAbortError(RuntimeError):
    """Raised when a failing rule has ``on_error = "fail"``.

    Propagates out of the worker to abort the whole index run, per the D1
    failure semantics. ``skip`` and ``passthrough`` never raise.
    """


class _PreprocessSkipError(Exception):
    """Internal: a recoverable per-file failure carrying a human reason."""


@dataclass(frozen=True, slots=True)
class PreprocessResult:
    """Outcome of running one preprocessor against one source file.

    Attributes:
        status: ``ok`` (use ``output``), ``skipped`` (drop the file from the
            index, counted), or ``passthrough`` (index the raw source).
        output: The validated :class:`PreprocOutput` when ``status == "ok"``,
            else ``None``.
        reason: A human-readable explanation when the file was skipped, else
            ``None``.
    """

    status: PreprocessStatus
    output: PreprocOutput | None
    reason: str | None


def _emitted_text_length(output: PreprocOutput) -> int:
    """Return the total emitted character count for the cap check (D10)."""
    if output.text is not None:
        return len(output.text)
    if output.units is not None:
        return sum(len(unit.text) for unit in output.units)
    return 0


def _build_argv(rule: PreprocessRule, source_path: pathlib.Path) -> list[str]:
    """Build the subprocess argv for a rule (command or entry_point form).

    A ``command`` rule is shell-split with ``{path}`` substituted token-wise
    (never via a shell). An ``entry_point`` rule is invoked as the current
    interpreter running the out-of-process entry runner, so it shares the exact
    same isolation and timeout guarantees as the command form (#185 follow-up).
    """
    if rule.entry_point is not None:
        return [
            sys.executable,
            "-m",
            _ENTRY_RUNNER_MODULE,
            rule.entry_point,
            str(source_path),
        ]
    if rule.command is not None:
        tokens = shlex.split(rule.command, posix=True)
        return [token.replace("{path}", str(source_path)) for token in tokens]
    return []


def _run_bounded(
    argv: list[str],
    timeout_s: float | None,
    stdout_cap: int,
) -> tuple[int, bytes, str]:
    """Run ``argv``, capturing stdout up to ``stdout_cap`` bytes and bounded stderr.

    Reads both pipes on dedicated threads (deadlock-free) but stops *storing*
    stdout past the cap, so a runaway extractor cannot spike memory before the
    emitted-size cap fires (review PREPROCESS-003). The wall-clock ``timeout_s``
    still bounds a child that keeps producing output.

    Returns ``(returncode, stdout_bytes, stderr_text)``; ``stdout_bytes`` is at
    most ``stdout_cap + 1`` so the caller can detect truncation.

    Raises:
        _PreprocessSkipError: On launch failure or timeout.
    """
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        msg = f"preprocessor could not be launched: {exc}"
        raise _PreprocessSkipError(msg) from exc

    captured: dict[str, bytes] = {"stdout": b"", "stderr": b""}

    def _drain_stdout(pipe: IO[bytes]) -> None:
        buf = bytearray()
        while True:
            chunk = pipe.read(65536)
            if not chunk:
                break
            if len(buf) <= stdout_cap:
                buf += chunk  # store until just past the cap, then discard
        captured["stdout"] = bytes(buf[: stdout_cap + 1])

    def _drain_stderr(pipe: IO[bytes]) -> None:
        captured["stderr"] = pipe.read(_STDERR_CAP)
        while pipe.read(65536):
            pass

    if proc.stdout is None or proc.stderr is None:  # pragma: no cover - PIPE set
        proc.kill()
        msg = "preprocessor pipes unavailable"
        raise _PreprocessSkipError(msg)
    t_out = threading.Thread(target=_drain_stdout, args=(proc.stdout,))
    t_err = threading.Thread(target=_drain_stderr, args=(proc.stderr,))
    t_out.start()
    t_err.start()
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait()
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        msg = f"preprocessor timed out after {timeout_s}s"
        raise _PreprocessSkipError(msg) from exc
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    stderr_text = captured["stderr"].decode("utf-8", errors="replace").strip()
    return proc.returncode, captured["stdout"], stderr_text


def _invoke_and_validate(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    max_emitted_bytes: int,
) -> PreprocOutput:
    """Run the preprocessor, parse stdout, validate, and enforce the size caps.

    Raises:
        _PreprocessSkipError: On any recoverable per-file failure (misconfigured
            rule, non-zero exit, timeout, oversize stdout, non-JSON or
            schema-invalid output, or emitted text over the cap).
    """
    argv = _build_argv(rule, source_path)
    if not argv:
        msg = "rule has neither a runnable command nor entry_point"
        raise _PreprocessSkipError(msg)

    stdout_cap = max(max_emitted_bytes * _STDOUT_CAP_MULTIPLIER, _MIN_STDOUT_CAP)
    returncode, stdout, stderr = _run_bounded(argv, rule.timeout_s, stdout_cap)

    if len(stdout) > stdout_cap:
        msg = f"preprocessor stdout exceeds {stdout_cap} bytes; skipping"
        raise _PreprocessSkipError(msg)

    if returncode != 0:
        msg = f"preprocessor exited {returncode}: {stderr[:500]}"
        raise _PreprocessSkipError(msg)

    try:
        payload = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"preprocessor stdout is not valid JSON: {exc}"
        raise _PreprocessSkipError(msg) from exc

    try:
        output = validate_preproc_output(payload)
    except (ValidationError, UnsupportedSchemaVersionError) as exc:
        msg = f"preprocessor output failed validation: {exc}"
        raise _PreprocessSkipError(msg) from exc

    emitted = _emitted_text_length(output)
    if emitted > max_emitted_bytes:
        msg = f"emitted text {emitted} exceeds cap {max_emitted_bytes}"
        raise _PreprocessSkipError(msg)

    return output


def run_preprocessor(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    *,
    max_emitted_bytes: int,
) -> PreprocessResult:
    """Run a command rule against one source file and resolve its disposition.

    Args:
        source_path: Absolute path to the source file to preprocess.
        rule: The matched, validated command rule.
        max_emitted_bytes: The emitted-text length cap (D10).

    Returns:
        A :class:`PreprocessResult`. On success, ``status == "ok"`` with the
        validated output. On a recoverable failure the disposition follows the
        rule's ``on_error``: ``skip`` -> ``skipped``; ``passthrough`` ->
        ``passthrough``.

    Raises:
        PreprocessAbortError: If the rule fails and ``on_error == "fail"``.
    """
    try:
        output = _invoke_and_validate(source_path, rule, max_emitted_bytes)
    except _PreprocessSkipError as exc:
        reason = str(exc)
        if rule.on_error == "fail":
            abort = f"preprocessor for {source_path} failed (on_error=fail): {reason}"
            raise PreprocessAbortError(abort) from exc
        if rule.on_error == "passthrough":
            logger.warning(
                "preprocess passthrough for %s (%s); indexing raw source",
                source_path,
                reason,
            )
            return PreprocessResult(status="passthrough", output=None, reason=reason)
        logger.warning("preprocess skip for %s (%s)", source_path, reason)
        return PreprocessResult(status="skipped", output=None, reason=reason)

    return PreprocessResult(status="ok", output=output, reason=None)
