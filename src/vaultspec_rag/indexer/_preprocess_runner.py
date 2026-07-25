"""Command-form preprocessor execution (the runtime side of the hook).

Runs a project-supplied ``command`` rule against one source file in a
``subprocess`` grandchild, parses and validates its stdout JSON against the
:mod:`._preprocess_schema` contract, enforces the emitted-text cap, and maps the
outcome onto the rule's ``on_error`` disposition.

Running the real extraction in a separate OS process is what makes the command
form CPU-only-safe *by construction*: the child has its own interpreter and
cannot pollute the spawn worker's import chain or CUDA state, and it holds
without any trust assumptions. The command
is split with :func:`shlex.split` and the ``{path}`` placeholder is substituted
token-wise (never via a shell), so source paths with spaces or shell
metacharacters cannot inject.

The hook runs directly with the operator's privileges: a root's preprocess
config is repo-authored code, the same trust class as building that repo.
The child still gets a curated, secret-free
environment and runs with the project root as its cwd, and every
output/timeout bound below applies unchanged.
"""

from __future__ import annotations

import json
import logging
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal, cast

from pydantic import ValidationError

from ._hook_sandbox import curated_child_env, default_popen_handle
from ._preprocess_schema import (
    PREPROCESS_INVOCATION_ENV,
    PreprocessInvocation,
    PreprocessInvocationMode,
    PreprocOutput,
    UnsupportedSchemaVersionError,
    validate_preproc_output,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

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

#: Hard ceiling on a batch invocation's wall-clock budget. The per-file
#: ``timeout_s`` the author declared scales with the manifest size, but never
#: past this bound, so one runaway batch cannot hang the indexer for hours.
_MAX_BATCH_TIMEOUT_S = 600.0

#: Absolute ceiling on a batch invocation's captured stdout, on top of the
#: per-file scaling. Bounds peak memory for a large manifest so a runaway
#: extractor cannot spike the worker before the per-file emitted-size cap fires.
_MAX_BATCH_STDOUT_CAP = 64 * 1024 * 1024

__all__ = [
    "PreprocessAbortError",
    "PreprocessResult",
    "PreprocessStatus",
    "run_preprocessor",
    "run_preprocessor_batch",
]

PreprocessStatus = Literal["ok", "skipped", "passthrough"]


class PreprocessAbortError(RuntimeError):
    """Raised when a failing rule has ``on_error = "fail"``.

    Propagates out of the worker to abort the whole index run, per the
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


def _emitted_text_bytes(output: PreprocOutput) -> int:
    """Return the aggregate UTF-8 byte count of all emitted text."""
    if output.text is not None:
        return len(output.text.encode("utf-8"))
    if output.units is not None:
        return sum(len(unit.text.encode("utf-8")) for unit in output.units)
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
        path_str = str(source_path)
        tokens = shlex.split(rule.command, posix=True)
        return [_substitute_path(token, path_str) for token in tokens]
    return []


def _substitute_path(token: str, path_str: str) -> str:
    """Substitute ``{path}`` into one argv token, neutralising option-injection.

    Token-wise substitution already defeats shell injection. This additionally
    closes argv-position injection (CWE-88): if a standalone ``{path}`` operand
    resolves to a value beginning with ``-`` (a file whose name an attacker
    controls, e.g. ``--output=...``), it would be parsed by the child as an
    option, not an operand. A bare ``-``-leading path operand is prefixed with
    ``./`` so it is unambiguously a path. Absolute paths (the normal case) never
    begin with ``-`` and are unchanged.
    """
    substituted = token.replace("{path}", path_str)
    if substituted == path_str and substituted.startswith("-"):
        return f"./{substituted}"
    return substituted


def _canonical_source_identity(
    source_path: pathlib.Path,
    project_root: pathlib.Path,
) -> str:
    """Return the host-owned normalized project-relative source identity."""
    try:
        return source_path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        msg = f"preprocess source is outside the project root: {source_path}"
        raise _PreprocessSkipError(msg) from exc


def _invocation_envelope(
    source_paths: Sequence[pathlib.Path],
    rule: PreprocessRule,
    project_root: pathlib.Path,
    mode: PreprocessInvocationMode,
) -> PreprocessInvocation:
    """Build the canonical envelope shared by command and entry-point forms."""
    return PreprocessInvocation.model_validate(
        {
            "source_paths": tuple(
                _canonical_source_identity(path, project_root) for path in source_paths
            ),
            "options": dict(rule.options),
            "extractor_version": rule.extractor_version,
            "target": rule.target.value,
            "mode": mode,
        }
    )


def _child_env(
    project_root: pathlib.Path,
    invocation: PreprocessInvocation,
) -> dict[str, str]:
    """Return the curated hook env with the project root on ``PYTHONPATH``.

    The curated env strips every secret and ``VAULTSPEC_RAG_*`` knob (including
    any inherited ``PYTHONPATH``). A project-local hook - whether an
    ``entry_point`` (``module:callable``) or a ``command`` that runs
    ``python -m project.pkg.hook`` - must still be able to import its own module
    tree, so the project root is placed on ``PYTHONPATH`` here.
    """
    env = curated_child_env()
    env["PYTHONPATH"] = str(project_root)
    env[PREPROCESS_INVOCATION_ENV] = invocation.canonical_json
    return env


def _drain_stdout_bounded(
    pipe: IO[bytes], stdout_cap: int, captured: dict[str, bytes]
) -> None:
    """Drain stdout while retaining at most one byte beyond its hard cap."""
    buf = bytearray()
    while chunk := pipe.read(65536):
        if len(buf) <= stdout_cap:
            buf += chunk
    captured["stdout"] = bytes(buf[: stdout_cap + 1])


def _drain_stderr_bounded(pipe: IO[bytes], captured: dict[str, bytes]) -> None:
    """Drain stderr while retaining only its bounded diagnostic prefix."""
    captured["stderr"] = pipe.read(_STDERR_CAP)
    while pipe.read(65536):
        pass


def _wait_for_child(
    handle: subprocess.Popen[bytes],
    timeout_s: float | None,
    checkpoint: Callable[[], None] | None,
) -> None:
    """Poll one child at cooperative cancellation and timeout safe points."""
    started = time.monotonic()
    while handle.poll() is None:
        if checkpoint is not None:
            checkpoint()
        if timeout_s is not None and time.monotonic() - started >= timeout_s:
            raise subprocess.TimeoutExpired(handle.args, timeout_s)
        try:
            handle.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            continue


def _terminate_and_join(
    handle: subprocess.Popen[bytes],
    stdout_thread: threading.Thread,
    stderr_thread: threading.Thread,
) -> None:
    """Terminate a child and join both pipe drains on every exceptional exit."""
    handle.kill()
    handle.wait()
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)


def _drain_and_wait(
    handle: subprocess.Popen[bytes],
    timeout_s: float | None,
    stdout_cap: int,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[int, bytes, str]:
    """Drain a launched child's pipes on threads, then wait with a timeout.

    Reads both pipes on dedicated threads (deadlock-free) but stops *storing*
    stdout past the cap, so a runaway extractor cannot spike memory before the
    emitted-size cap fires (review PREPROCESS-003). The wall-clock ``timeout_s``
    still bounds a child that keeps producing output.

    Returns ``(returncode, stdout_bytes, stderr_text)``; ``stdout_bytes`` is at
    most ``stdout_cap + 1`` so the caller can detect truncation.

    Raises:
        _PreprocessSkipError: On a timeout or missing pipes.
    """
    captured: dict[str, bytes] = {"stdout": b"", "stderr": b""}

    if handle.stdout is None or handle.stderr is None:  # pragma: no cover - PIPE set
        handle.kill()
        msg = "preprocessor pipes unavailable"
        raise _PreprocessSkipError(msg)
    t_out = threading.Thread(
        target=_drain_stdout_bounded,
        args=(handle.stdout, stdout_cap, captured),
    )
    t_err = threading.Thread(
        target=_drain_stderr_bounded,
        args=(handle.stderr, captured),
    )
    t_out.start()
    t_err.start()
    try:
        _wait_for_child(handle, timeout_s, checkpoint)
    except subprocess.TimeoutExpired as exc:
        _terminate_and_join(handle, t_out, t_err)
        msg = f"preprocessor timed out after {timeout_s}s"
        raise _PreprocessSkipError(msg) from exc
    except BaseException:
        _terminate_and_join(handle, t_out, t_err)
        raise
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    stderr_text = captured["stderr"].decode("utf-8", errors="replace").strip()
    returncode = handle.returncode if handle.returncode is not None else -1
    return returncode, captured["stdout"], stderr_text


def _run_bounded(
    argv: list[str],
    timeout_s: float | None,
    stdout_cap: int,
    *,
    cwd: pathlib.Path,
    env: dict[str, str],
    checkpoint: Callable[[], None] | None = None,
) -> tuple[int, bytes, str]:
    """Launch ``argv`` directly and drain it bounded.

    The child runs with the curated env and ``cwd`` as its working directory.
    All output/timeout bounds are enforced by :func:`_drain_and_wait`.

    Raises:
        _PreprocessSkipError: On launch failure or timeout.
    """
    try:
        handle = default_popen_handle(argv, cwd=cwd, env=env)
    except OSError as exc:
        msg = f"preprocessor could not be launched: {exc}"
        raise _PreprocessSkipError(msg) from exc

    return _drain_and_wait(handle, timeout_s, stdout_cap, checkpoint)


def _invoke_and_validate(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    max_emitted_bytes: int,
    *,
    project_root: pathlib.Path,
    checkpoint: Callable[[], None] | None = None,
) -> PreprocOutput:
    """Run the preprocessor, validate its output, and enforce the caps.

    The hook reads the original source path directly and runs with the project
    root as its cwd - the same working directory hook authors use when they
    validate a rule with ``preprocess run-one``. Project-launcher commands
    (``uv run``, ``npm exec``, ``make``) resolve their project from the cwd, so
    any other directory silently breaks them; a hook that writes into the repo
    is the project's own doing under the trust model.

    Raises:
        _PreprocessSkipError: On any recoverable per-file failure
            (misconfigured rule, non-zero exit, timeout, oversize stdout,
            non-JSON or schema-invalid output, or emitted text over the cap).
    """
    argv = _build_argv(rule, source_path)
    if not argv:
        msg = "rule has neither a runnable command nor entry_point"
        raise _PreprocessSkipError(msg)

    invocation = _invocation_envelope(
        (source_path,),
        rule,
        project_root,
        "single",
    )
    stdout_cap = max(max_emitted_bytes * _STDOUT_CAP_MULTIPLIER, _MIN_STDOUT_CAP)
    returncode, stdout, stderr = _run_bounded(
        argv,
        rule.timeout_s,
        stdout_cap,
        cwd=project_root,
        env=_child_env(project_root, invocation),
        checkpoint=checkpoint,
    )
    output = _validate_output(
        returncode,
        stdout,
        stderr,
        stdout_cap,
        max_emitted_bytes,
    )
    _validate_source_binding(output, source_path, project_root)
    return output


def _validate_source_binding(
    output: PreprocOutput,
    expected_path: pathlib.Path,
    project_root: pathlib.Path,
) -> None:
    """Reject extractor attempts to redirect output to another source."""
    expected = _canonical_source_identity(expected_path, project_root)
    declared = pathlib.Path(output.source_path)
    if not declared.is_absolute():
        declared = project_root / declared
    actual = _canonical_source_identity(declared, project_root)
    if actual != expected:
        msg = (
            "preprocessor output source_path does not match invoked source: "
            f"expected {expected!r}, received {actual!r}"
        )
        raise _PreprocessSkipError(msg)


def _validate_output(
    returncode: int,
    stdout: bytes,
    stderr: str,
    stdout_cap: int,
    max_emitted_bytes: int,
) -> PreprocOutput:
    """Parse and validate captured stdout against the caps and schema.

    Raises:
        _PreprocessSkipError: On oversize stdout, non-zero exit, non-JSON or
            schema-invalid output, or emitted text over the cap.
    """

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

    emitted = _emitted_text_bytes(output)
    if emitted > max_emitted_bytes:
        msg = f"emitted text bytes {emitted} exceeds cap {max_emitted_bytes}"
        raise _PreprocessSkipError(msg)

    return output


def run_preprocessor(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    *,
    max_emitted_bytes: int,
    project_root: pathlib.Path,
    checkpoint: Callable[[], None] | None = None,
) -> PreprocessResult:
    """Run a command rule against one source file and resolve its disposition.

    Args:
        source_path: Absolute path to the source file to preprocess.
        rule: The matched, validated command rule.
        max_emitted_bytes: The emitted-text length cap.
        project_root: The project root, placed on the child's ``PYTHONPATH`` so
            an ``entry_point`` or project-local hook can import its module tree.

    Returns:
        A :class:`PreprocessResult`. On success, ``status == "ok"`` with the
        validated output. On a recoverable failure the disposition follows the
        rule's ``on_error``: ``skip`` -> ``skipped``; ``passthrough`` ->
        ``passthrough``.

    Raises:
        PreprocessAbortError: If the rule fails and ``on_error == "fail"``.
    """
    try:
        output = _invoke_and_validate(
            source_path,
            rule,
            max_emitted_bytes,
            project_root=project_root,
            checkpoint=checkpoint,
        )
    except _PreprocessSkipError as exc:
        return _dispose_failure(source_path, rule, str(exc), cause=exc)

    return PreprocessResult(status="ok", output=output, reason=None)


def _dispose_failure(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    reason: str,
    *,
    cause: BaseException | None = None,
) -> PreprocessResult:
    """Resolve a per-file failure through the rule's ``on_error`` disposition.

    ``fail`` raises :class:`PreprocessAbortError` (aborting the run); ``skip``
    and ``passthrough`` return the corresponding result. Shared by the per-file
    and batch runners so both map failures identically.
    """
    if rule.on_error == "fail":
        abort = f"preprocessor for {source_path} failed (on_error=fail): {reason}"
        raise PreprocessAbortError(abort) from cause
    if rule.on_error == "passthrough":
        logger.warning(
            "preprocess passthrough for %s (%s); indexing raw source",
            source_path,
            reason,
        )
        return PreprocessResult(status="passthrough", output=None, reason=reason)
    logger.warning("preprocess skip for %s (%s)", source_path, reason)
    return PreprocessResult(status="skipped", output=None, reason=reason)


@dataclass(frozen=True, slots=True)
class _BatchParse:
    """Split batch envelope: per-file validated outputs and per-file reasons.

    ``outputs`` holds the validated output for each source path the hook
    returned a usable element for; ``failures`` holds a human reason for a
    source path whose element was present but invalid (schema-invalid or over
    the emitted cap). A source path absent from both was omitted by the hook.
    """

    outputs: dict[str, PreprocOutput]
    failures: dict[str, str]


def _substitute_paths(token: str, manifest_str: str) -> str:
    """Substitute ``{paths}`` into one argv token, neutralising injection.

    Mirrors :func:`_substitute_path` for the batch manifest placeholder: the
    substitution is token-wise (never via a shell), and a standalone operand
    that resolves to a ``-``-leading value is prefixed with ``./`` so the child
    parses it as a path, not an option (CWE-88). A manifest temp path is
    absolute in the normal case and never ``-``-leading.
    """
    substituted = token.replace("{paths}", manifest_str)
    if substituted == manifest_str and substituted.startswith("-"):
        return f"./{substituted}"
    return substituted


def _build_batch_argv(rule: PreprocessRule, manifest_path: str) -> list[str]:
    """Build the subprocess argv for a batch command rule.

    The command is shell-split with ``{paths}`` substituted token-wise for the
    manifest path (never via a shell), matching the per-file command form's
    injection safety.
    """
    command = rule.command or ""
    tokens = shlex.split(command, posix=True)
    return [_substitute_paths(token, manifest_path) for token in tokens]


def _write_manifest_fd(fd: int, source_paths: Sequence[pathlib.Path]) -> None:
    """Write one absolute source path per line (UTF-8) to an open manifest fd.

    Takes ownership of ``fd`` and closes it. The caller creates the temp file
    (capturing its path) before calling this, so a failing write is still
    unlinked by the caller's cleanup.
    """
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        for path in source_paths:
            fh.write(f"{path}\n")


def _delete_batch_manifest(manifest_path: str) -> None:
    """Delete the batch manifest temp file, tolerating an already-gone file."""
    try:
        os.unlink(manifest_path)
    except OSError as exc:
        logger.debug("could not delete batch manifest %s: %s", manifest_path, exc)


def _batch_key_lookup(source_paths: Sequence[pathlib.Path]) -> dict[str, str]:
    """Map each source path's normalised form to its canonical ``str`` key.

    A hook may echo a path that differs from the manifest line only in case or
    separators, so the response ``path`` is matched against the normalised
    absolute form rather than requiring a byte-identical string.
    """
    return {
        os.path.normcase(os.path.abspath(str(path))): str(path) for path in source_paths
    }


def _match_batch_key(
    raw_path: object,
    keys_by_norm: dict[str, str],
    project_root: pathlib.Path,
) -> str | None:
    """Resolve a response element's ``path`` to a source path key, or ``None``.

    A relative echoed path is resolved against ``project_root`` (the hook's
    working directory), not the indexer process's own cwd, so a hook that emits
    paths relative to the project still maps back to its source files.
    """
    if not isinstance(raw_path, str) or not raw_path:
        return None
    resolved = raw_path
    if not os.path.isabs(resolved):
        resolved = os.path.join(str(project_root), resolved)
    return keys_by_norm.get(os.path.normcase(os.path.abspath(resolved)))


def _split_batch_output(
    returncode: int,
    stdout: bytes,
    stderr: str,
    stdout_cap: int,
    max_emitted_bytes: int,
    source_paths: Sequence[pathlib.Path],
    project_root: pathlib.Path,
) -> _BatchParse:
    """Parse and validate a batch envelope into per-file outputs and failures.

    Raises:
        _PreprocessSkipError: On a whole-envelope failure (oversize stdout,
            non-zero exit, non-JSON, or a non-array top level). The caller
            resolves every file in the batch through ``on_error`` for these.
    """
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
    if not isinstance(payload, list):
        msg = "preprocessor batch output must be a JSON array of per-file objects"
        raise _PreprocessSkipError(msg)

    keys_by_norm = _batch_key_lookup(source_paths)
    outputs: dict[str, PreprocOutput] = {}
    failures: dict[str, str] = {}
    for raw_element in cast("list[object]", payload):
        if not isinstance(raw_element, dict):
            continue
        element = cast("dict[str, object]", raw_element)
        key = _match_batch_key(element.get("path"), keys_by_norm, project_root)
        if key is None:
            continue
        body = {name: value for name, value in element.items() if name != "path"}
        try:
            output = validate_preproc_output(body)
        except (ValidationError, UnsupportedSchemaVersionError) as exc:
            failures[key] = f"preprocessor output failed validation: {exc}"
            continue
        try:
            _validate_source_binding(output, pathlib.Path(key), project_root)
        except _PreprocessSkipError as exc:
            failures[key] = str(exc)
            continue
        emitted = _emitted_text_bytes(output)
        if emitted > max_emitted_bytes:
            failures[key] = (
                f"emitted text bytes {emitted} exceeds cap {max_emitted_bytes}"
            )
            continue
        outputs[key] = output
    return _BatchParse(outputs, failures)


def _invoke_batch(
    source_paths: Sequence[pathlib.Path],
    rule: PreprocessRule,
    max_emitted_bytes: int,
    project_root: pathlib.Path,
    manifest_path: str,
    checkpoint: Callable[[], None] | None = None,
) -> _BatchParse:
    """Run the batch command once over the manifest and split its envelope.

    The wall-clock budget is the per-file ``timeout_s`` scaled by the manifest
    size (capped at :data:`_MAX_BATCH_TIMEOUT_S`), and the stdout cap scales the
    same way so the whole array fits; the per-file emitted-text cap is enforced
    unchanged on each element.

    Raises:
        _PreprocessSkipError: On a launch failure, timeout, or whole-envelope
            defect (the caller resolves every file through ``on_error``).
    """
    argv = _build_batch_argv(rule, manifest_path)
    count = len(source_paths)
    stdout_cap = min(
        max(max_emitted_bytes * _STDOUT_CAP_MULTIPLIER * count, _MIN_STDOUT_CAP),
        _MAX_BATCH_STDOUT_CAP,
    )
    timeout_s = (
        None
        if rule.timeout_s is None
        else min(rule.timeout_s * count, _MAX_BATCH_TIMEOUT_S)
    )
    invocation = _invocation_envelope(source_paths, rule, project_root, "batch")
    returncode, stdout, stderr = _run_bounded(
        argv,
        timeout_s,
        stdout_cap,
        cwd=project_root,
        env=_child_env(project_root, invocation),
        checkpoint=checkpoint,
    )
    return _split_batch_output(
        returncode,
        stdout,
        stderr,
        stdout_cap,
        max_emitted_bytes,
        source_paths,
        project_root,
    )


def run_preprocessor_batch(
    source_paths: Sequence[pathlib.Path],
    rule: PreprocessRule,
    *,
    max_emitted_bytes: int,
    project_root: pathlib.Path,
    checkpoint: Callable[[], None] | None = None,
) -> dict[str, PreprocessResult]:
    """Run a batch command rule once over many files, resolving each in turn.

    Writes the source paths to a manifest temp file, hands it to the command via
    its ``{paths}`` placeholder in a single subprocess, and splits the returned
    JSON array back into one :class:`PreprocessResult` per source path.

    Failure semantics are per file: an element missing from the response, or one
    that fails v1 validation or the emitted-text cap, resolves through the rule's
    ``on_error`` for that file alone. A whole-envelope defect (non-JSON,
    non-array, non-zero exit, timeout, or oversize stdout) resolves every file in
    the batch through ``on_error``. ``on_error == "fail"`` raises
    :class:`PreprocessAbortError` on the first affected file.

    Args:
        source_paths: Absolute paths of the files in this batch.
        rule: The matched, validated batch command rule.
        max_emitted_bytes: The per-file emitted-text length cap.
        project_root: The project root, placed on the child's ``PYTHONPATH`` and
            used as its working directory.

    Returns:
        A mapping of ``str(source_path)`` to its :class:`PreprocessResult`, one
        entry per input path.

    Raises:
        PreprocessAbortError: If any file fails and ``on_error == "fail"``.
    """
    if not source_paths:
        return {}

    # Capture the manifest path before writing so a failing write still unlinks
    # it in the finally below.
    fd, manifest_path = tempfile.mkstemp(prefix="vsrag-batch-", suffix=".txt")
    try:
        _write_manifest_fd(fd, source_paths)
        try:
            parsed = _invoke_batch(
                source_paths,
                rule,
                max_emitted_bytes,
                project_root,
                manifest_path,
                checkpoint,
            )
        except _PreprocessSkipError as exc:
            reason = str(exc)
            return {
                str(path): _dispose_failure(path, rule, reason, cause=exc)
                for path in source_paths
            }

        results: dict[str, PreprocessResult] = {}
        for path in source_paths:
            key = str(path)
            output = parsed.outputs.get(key)
            if output is not None:
                results[key] = PreprocessResult(status="ok", output=output, reason=None)
                continue
            reason = parsed.failures.get(
                key, "preprocessor returned no output for this file"
            )
            results[key] = _dispose_failure(path, rule, reason)
        return results
    finally:
        _delete_batch_manifest(manifest_path)
