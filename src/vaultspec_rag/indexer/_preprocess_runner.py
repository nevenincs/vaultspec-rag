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
from contextlib import ExitStack
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal, cast

from pydantic import ValidationError

from .._process_probe import kill_child_tree
from .._python_child import script_command
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

#: The out-of-process entry-point runner, named by its file rather than by its
#: module path. The child runs with the project root on its import path so a
#: hook can import its own modules, and a module path would be resolved there
#: first: a project shipping a directory under this package's name would then
#: supply the runner as well as the hook.
_ENTRY_RUNNER_FILE = pathlib.Path(__file__).with_name("_preprocess_entry.py")

#: Raw stdout is captured up to this multiple of the emitted-text cap, leaving
#: headroom for JSON structure while bounding peak memory so a runaway extractor
#: cannot OOM the worker before the emitted-size cap fires (review PREPROCESS-003).
_STDOUT_CAP_MULTIPLIER = 4
_MIN_STDOUT_CAP = 1024 * 1024
#: Hard ceiling on captured stderr so a flooding child cannot OOM us either.
_STDERR_CAP = 64 * 1024
#: How long a killed preprocessor tree, and then its pipe readers, are each
#: given to be gone before cleanup reports that they are not.
_CLEANUP_SECONDS = 5.0

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


@dataclass(frozen=True, slots=True)
class _PreprocessExecutionContext:
    """Shared cap, root, and checkpoint controls for one hook invocation."""

    max_emitted_bytes: int
    project_root: pathlib.Path
    checkpoint: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class _BoundedProcessRequest:
    """One child process launch with its bounded-output controls."""

    argv: list[str]
    timeout_s: float | None
    stdout_cap: int
    cwd: pathlib.Path
    env: dict[str, str]
    checkpoint: Callable[[], None] | None = None


@dataclass(frozen=True, slots=True)
class _BatchOutputInput:
    """Raw batch output and the source identities it must account for."""

    returncode: int
    stdout: bytes
    stderr: str
    stdout_cap: int
    context: _PreprocessExecutionContext
    source_paths: Sequence[pathlib.Path]


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
        return script_command(
            sys.executable, _ENTRY_RUNNER_FILE, rule.entry_point, str(source_path)
        )
    if rule.command is not None:
        path_str = str(source_path)
        tokens = shlex.split(rule.command, posix=True)
        return [_substitute_operand(token, "{path}", path_str) for token in tokens]
    return []


def _substitute_operand(token: str, placeholder: str, value: str) -> str:
    """Substitute *placeholder* into one argv token, neutralising option-injection.

    Serves both invocation shapes - the per-file ``{path}`` operand and the
    batch ``{paths}`` manifest operand - because the neutralisation is the
    same guarantee for both and must never be strengthened on one shape only.

    Token-wise substitution already defeats shell injection. This additionally
    closes argv-position injection (CWE-88): if a standalone operand resolves
    to a value beginning with ``-`` (a file whose name an attacker controls,
    e.g. ``--output=...``), it would be parsed by the child as an option, not
    an operand. A bare ``-``-leading operand is prefixed with ``./`` so it is
    unambiguously a path. Absolute paths - the normal case for both a source
    file and a manifest temp file - never begin with ``-`` and are unchanged.
    """
    substituted = token.replace(placeholder, value)
    if substituted == value and substituted.startswith("-"):
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


@dataclass(frozen=True, slots=True)
class _PipeCapture:
    output: dict[str, bytes]
    stopped: threading.Event
    errors: list[Exception]


def _drain_pipe(
    pipe: IO[bytes],
    key: str,
    cap: int,
    capture: _PipeCapture,
) -> None:
    """Drain a nonblocking pipe without holding a BufferedReader's read lock."""
    buf = bytearray()
    try:
        while not capture.stopped.is_set():
            try:
                chunk = os.read(pipe.fileno(), 65536)
            except BlockingIOError:
                capture.stopped.wait(0.01)
                continue
            if not chunk:
                break
            buf.extend(chunk[: max(0, cap - len(buf))])
    except Exception as exc:
        capture.errors.append(exc)
    finally:
        capture.output[key] = bytes(buf)


def _wait_for_child(
    handle: subprocess.Popen[bytes],
    deadline: float | None,
    checkpoint: Callable[[], None] | None,
) -> None:
    """Poll one child at cooperative cancellation and timeout safe points."""
    while handle.poll() is None:
        if checkpoint is not None:
            checkpoint()
        if deadline is not None and time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(handle.args, 0)
        try:
            handle.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            continue


def _join_readers(
    threads: tuple[threading.Thread, ...],
    deadline: float,
    errors: list[Exception],
    checkpoint: Callable[[], None] | None,
) -> None:
    """Await EOF only within the invocation's remaining output-drain budget."""
    while any(thread.is_alive() for thread in threads):
        if checkpoint is not None:
            checkpoint()
        if errors:
            raise errors[0]
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired("preprocessor pipe drain", 0)
        for thread in threads:
            thread.join(timeout=0.01)
    if errors:
        raise errors[0]


def _stop_readers(threads: tuple[threading.Thread, ...], deadline: float) -> None:
    """Join only started readers within the shared cleanup deadline."""
    for thread in threads:
        if thread.ident is not None:
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                raise RuntimeError("preprocessor pipe reader did not terminate")


def _terminate_and_join(
    handle: subprocess.Popen[bytes],
    threads: tuple[threading.Thread, ...],
    stopped: threading.Event,
) -> None:
    """Stop readers, kill the child's whole tree, and say what could not be shown.

    Three things are reported rather than left unsaid: a process that
    survived the kill, a running child whose descendants could not be
    identified, and a child that had already exited while a reader was still
    waiting on a pipe - which means something it started holds that pipe, and
    nothing is left to say what.
    """
    pending_readers = sum(thread.is_alive() for thread in threads)
    stopped.set()
    cleanup_error: Exception | None = None
    if handle.poll() is not None and pending_readers:
        cleanup_error = ProcessLookupError(
            "parent exited before descendant witness; "
            f"pending_pipe_readers={pending_readers}, descendant_count=unknown"
        )
    try:
        killed = kill_child_tree(handle, confirm_seconds=_CLEANUP_SECONDS)
        if killed.survivors:
            raise RuntimeError(
                f"preprocessor processes {list(killed.survivors)} survived cleanup"
            )
        if not killed.witnessed and cleanup_error is None:
            cleanup_error = ProcessLookupError(
                "preprocessor parent identity is unreadable"
            )
    finally:
        _stop_readers(threads, time.monotonic() + _CLEANUP_SECONDS)
    if cleanup_error is not None:
        raise cleanup_error


def _drain_and_wait(
    handle: subprocess.Popen[bytes],
    timeout_s: float | None,
    stdout_cap: int,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[int, bytes, str]:
    """Own pipes through bounded waiting; never wait indefinitely in Popen.__exit__."""
    with ExitStack() as cleanup:
        for pipe in (handle.stdout, handle.stderr):
            if pipe is not None:
                cleanup.callback(pipe.close)
        return _drain_child(handle, timeout_s, stdout_cap, checkpoint)


def _drain_child(
    handle: subprocess.Popen[bytes],
    timeout_s: float | None,
    stdout_cap: int,
    checkpoint: Callable[[], None] | None = None,
) -> tuple[int, bytes, str]:
    """Capture capped output using stoppable readers within one timeout budget."""
    captured: dict[str, bytes] = {"stdout": b"", "stderr": b""}
    stopped = threading.Event()
    errors: list[Exception] = []
    capture = _PipeCapture(captured, stopped, errors)
    threads: tuple[threading.Thread, ...] = ()
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None
    try:
        if handle.stdout is None or handle.stderr is None:
            raise _PreprocessSkipError("preprocessor pipes unavailable")
        # Windows pipe descriptors support this on every supported Python version.
        # A refused/unsupported flag is an explicit failure, never a blocking fallback.
        os.set_blocking(handle.stdout.fileno(), False)
        os.set_blocking(handle.stderr.fileno(), False)
        threads = tuple(
            threading.Thread(
                target=_drain_pipe,
                args=(pipe, key, cap, capture),
                name=f"preprocessor-{key}",
            )
            for pipe, key, cap in (
                (handle.stdout, "stdout", stdout_cap + 1),
                (handle.stderr, "stderr", _STDERR_CAP),
            )
        )
        for thread in threads:
            thread.start()
        _wait_for_child(handle, deadline, checkpoint)
        _join_readers(
            threads,
            deadline if deadline is not None else time.monotonic() + _CLEANUP_SECONDS,
            errors,
            checkpoint,
        )
    except BaseException as exc:
        try:
            _terminate_and_join(handle, threads, stopped)
        except Exception as cleanup_exc:
            exc.add_note(f"preprocessor cleanup failed: {cleanup_exc}")
        if isinstance(exc, subprocess.TimeoutExpired):
            msg = f"preprocessor timed out after {timeout_s}s"
            if notes := getattr(exc, "__notes__", None):
                msg += "; " + "; ".join(notes)
            raise _PreprocessSkipError(msg) from exc
        raise
    stderr_text = captured["stderr"].decode("utf-8", errors="replace").strip()
    returncode = handle.returncode if handle.returncode is not None else -1
    return returncode, captured["stdout"], stderr_text


def _run_bounded(request: _BoundedProcessRequest) -> tuple[int, bytes, str]:
    """Launch ``argv`` directly and drain it bounded.

    The child runs with the curated env and ``cwd`` as its working directory.
    All output/timeout bounds are enforced by :func:`_drain_and_wait`.

    Raises:
        _PreprocessSkipError: On launch failure or timeout.
    """
    try:
        handle = default_popen_handle(request.argv, cwd=request.cwd, env=request.env)
    except OSError as exc:
        msg = f"preprocessor could not be launched: {exc}"
        raise _PreprocessSkipError(msg) from exc

    return _drain_and_wait(
        handle,
        request.timeout_s,
        request.stdout_cap,
        request.checkpoint,
    )


def _invoke_and_validate(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    context: _PreprocessExecutionContext,
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
        context.project_root,
        "single",
    )
    stdout_cap = max(
        context.max_emitted_bytes * _STDOUT_CAP_MULTIPLIER,
        _MIN_STDOUT_CAP,
    )
    returncode, stdout, stderr = _run_bounded(
        _BoundedProcessRequest(
            argv=argv,
            timeout_s=rule.timeout_s,
            stdout_cap=stdout_cap,
            cwd=context.project_root,
            env=_child_env(context.project_root, invocation),
            checkpoint=context.checkpoint,
        )
    )
    output = _validate_output(
        returncode,
        stdout,
        stderr,
        stdout_cap,
        context.max_emitted_bytes,
    )
    _validate_source_binding(output, source_path, context.project_root)
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
            _PreprocessExecutionContext(
                max_emitted_bytes=max_emitted_bytes,
                project_root=project_root,
                checkpoint=checkpoint,
            ),
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


def _build_batch_argv(rule: PreprocessRule, manifest_path: str) -> list[str]:
    """Build the subprocess argv for a batch command rule.

    The command is shell-split with ``{paths}`` substituted token-wise for the
    manifest path (never via a shell), matching the per-file command form's
    injection safety.
    """
    command = rule.command or ""
    tokens = shlex.split(command, posix=True)
    return [_substitute_operand(token, "{paths}", manifest_path) for token in tokens]


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


def _split_batch_output(input: _BatchOutputInput) -> _BatchParse:
    """Parse and validate a batch envelope into per-file outputs and failures.

    Raises:
        _PreprocessSkipError: On a whole-envelope failure (oversize stdout,
            non-zero exit, non-JSON, or a non-array top level). The caller
            resolves every file in the batch through ``on_error`` for these.
    """
    if len(input.stdout) > input.stdout_cap:
        msg = f"preprocessor stdout exceeds {input.stdout_cap} bytes; skipping"
        raise _PreprocessSkipError(msg)
    if input.returncode != 0:
        msg = f"preprocessor exited {input.returncode}: {input.stderr[:500]}"
        raise _PreprocessSkipError(msg)
    try:
        payload = json.loads(input.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        msg = f"preprocessor stdout is not valid JSON: {exc}"
        raise _PreprocessSkipError(msg) from exc
    if not isinstance(payload, list):
        msg = "preprocessor batch output must be a JSON array of per-file objects"
        raise _PreprocessSkipError(msg)

    keys_by_norm = _batch_key_lookup(input.source_paths)
    outputs: dict[str, PreprocOutput] = {}
    failures: dict[str, str] = {}
    for raw_element in cast("list[object]", payload):
        if not isinstance(raw_element, dict):
            continue
        element = cast("dict[str, object]", raw_element)
        key = _match_batch_key(
            element.get("path"),
            keys_by_norm,
            input.context.project_root,
        )
        if key is None:
            continue
        body = {name: value for name, value in element.items() if name != "path"}
        try:
            output = validate_preproc_output(body)
        except (ValidationError, UnsupportedSchemaVersionError) as exc:
            failures[key] = f"preprocessor output failed validation: {exc}"
            continue
        try:
            _validate_source_binding(
                output,
                pathlib.Path(key),
                input.context.project_root,
            )
        except _PreprocessSkipError as exc:
            failures[key] = str(exc)
            continue
        emitted = _emitted_text_bytes(output)
        if emitted > input.context.max_emitted_bytes:
            failures[key] = (
                "emitted text bytes "
                f"{emitted} exceeds cap {input.context.max_emitted_bytes}"
            )
            continue
        outputs[key] = output
    return _BatchParse(outputs, failures)


def _invoke_batch(
    source_paths: Sequence[pathlib.Path],
    rule: PreprocessRule,
    manifest_path: str,
    context: _PreprocessExecutionContext,
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
        max(
            context.max_emitted_bytes * _STDOUT_CAP_MULTIPLIER * count,
            _MIN_STDOUT_CAP,
        ),
        _MAX_BATCH_STDOUT_CAP,
    )
    timeout_s = (
        None
        if rule.timeout_s is None
        else min(rule.timeout_s * count, _MAX_BATCH_TIMEOUT_S)
    )
    invocation = _invocation_envelope(
        source_paths,
        rule,
        context.project_root,
        "batch",
    )
    returncode, stdout, stderr = _run_bounded(
        _BoundedProcessRequest(
            argv=argv,
            timeout_s=timeout_s,
            stdout_cap=stdout_cap,
            cwd=context.project_root,
            env=_child_env(context.project_root, invocation),
            checkpoint=context.checkpoint,
        )
    )
    return _split_batch_output(
        _BatchOutputInput(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
            stdout_cap=stdout_cap,
            context=context,
            source_paths=source_paths,
        )
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
                manifest_path,
                _PreprocessExecutionContext(
                    max_emitted_bytes=max_emitted_bytes,
                    project_root=project_root,
                    checkpoint=checkpoint,
                ),
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
