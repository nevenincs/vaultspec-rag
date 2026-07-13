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
import pathlib
import shlex
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Literal

from pydantic import ValidationError

from ._hook_sandbox import (
    SandboxUnavailableError,
    curated_child_env,
    default_popen_handle,
    resolve_hook_sandbox,
    stage_source,
)
from ._preprocess_schema import (
    PreprocOutput,
    UnsupportedSchemaVersionError,
    validate_preproc_output,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ._hook_sandbox import HookSandbox, SandboxHandle
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


#: Reason surfaced when server-mode containment resolves no working backend and
#: the hook is refused rather than run unconfined (ADR D6). The file is
#: skipped-and-surfaced; the operator can opt out with the named env knob.
_REFUSED_REASON = (
    "hook refused: no sandbox backend (set "
    "VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED=1 to override)"
)

#: Per-worker memo of the resolved backend, keyed on the ``(server_mode,
#: unsandboxed)`` policy inputs. ``run_preprocessor`` is called once per file
#: inside a spawn worker, but the capability probe (AppContainer profile
#: derivation / ``bwrap`` lookup) should happen at most once per worker.
_backend_cache: dict[tuple[bool, bool], HookSandbox | None] = {}
_backend_unavailable: set[tuple[bool, bool]] = set()


def _resolve_backend(*, server_mode: bool, unsandboxed: bool) -> HookSandbox | None:
    """Resolve (and memoize) the containment backend for this policy.

    Delegates the fail-closed policy to
    :func:`._hook_sandbox.resolve_hook_sandbox` - the single authority - and
    caches its outcome so the probe runs once per worker. A server-mode
    unavailability is memoized too and re-raised on every subsequent file.
    """
    key = (server_mode, unsandboxed)
    if key in _backend_unavailable:
        raise SandboxUnavailableError(_REFUSED_REASON)
    if key in _backend_cache:
        return _backend_cache[key]
    try:
        backend = resolve_hook_sandbox(server_mode=server_mode, unsandboxed=unsandboxed)
    except SandboxUnavailableError:
        _backend_unavailable.add(key)
        raise
    _backend_cache[key] = backend
    return backend


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


def _child_env(project_root: pathlib.Path) -> dict[str, str]:
    """Return the curated hook env with the project root on ``PYTHONPATH``.

    The curated env strips every secret and ``VAULTSPEC_RAG_*`` knob (including
    any inherited ``PYTHONPATH``). A project-local hook - whether an
    ``entry_point`` (``module:callable``) or a ``command`` that runs
    ``python -m project.pkg.hook`` - must still be able to import its own module
    tree, which the sandbox read-grants via ``project_root``. Read access alone
    is not enough: the interpreter needs the directory on ``sys.path``, so the
    project root is placed on ``PYTHONPATH`` here. ``PYTHONPATH`` precedes the
    stdlib and site paths, so a repo that plants a ``sitecustomize.py`` or a
    module shadowing a stdlib name would have it imported by the child - but the
    child is OS-sandboxed (no network, no filesystem outside the staged dir and
    the read-granted project root), so that runs contained and cannot exfiltrate
    or persist; it is the project's own code running against its own tree.
    """
    env = curated_child_env()
    env["PYTHONPATH"] = str(project_root)
    return env


def _drain_and_wait(
    handle: SandboxHandle,
    timeout_s: float | None,
    stdout_cap: int,
) -> tuple[int, bytes, str]:
    """Drain a launched child's pipes on threads, then wait with a timeout.

    Reads both pipes on dedicated threads (deadlock-free) but stops *storing*
    stdout past the cap, so a runaway extractor cannot spike memory before the
    emitted-size cap fires (review PREPROCESS-003). The wall-clock ``timeout_s``
    still bounds a child that keeps producing output. The ``handle`` is any
    :class:`~._hook_sandbox.SandboxHandle` - a bare ``Popen`` or a
    backend-launched contained child - so this logic is backend-agnostic.

    Returns ``(returncode, stdout_bytes, stderr_text)``; ``stdout_bytes`` is at
    most ``stdout_cap + 1`` so the caller can detect truncation.

    Raises:
        _PreprocessSkipError: On a timeout or missing pipes.
    """
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

    if handle.stdout is None or handle.stderr is None:  # pragma: no cover - PIPE set
        handle.kill()
        msg = "preprocessor pipes unavailable"
        raise _PreprocessSkipError(msg)
    t_out = threading.Thread(target=_drain_stdout, args=(handle.stdout,))
    t_err = threading.Thread(target=_drain_stderr, args=(handle.stderr,))
    t_out.start()
    t_err.start()
    try:
        handle.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        handle.kill()
        handle.wait()
        t_out.join(timeout=5)
        t_err.join(timeout=5)
        msg = f"preprocessor timed out after {timeout_s}s"
        raise _PreprocessSkipError(msg) from exc
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
    backend: HookSandbox | None,
    scratch_dir: pathlib.Path,
    env: dict[str, str],
    read_paths: Sequence[pathlib.Path],
) -> tuple[int, bytes, str]:
    """Launch ``argv`` through the sandbox backend and drain it bounded.

    When ``backend`` is ``None`` (unsandboxed opt-in, or local mode with no
    backend) the child runs via :func:`._hook_sandbox.default_popen_handle` -
    still with the curated env and scratch cwd, just without OS containment.
    Otherwise the backend confines the child, granting read of ``read_paths``.
    All output/timeout bounds are enforced identically in either case, and the
    backend's per-launch resources are released in ``finally``.

    Raises:
        _PreprocessSkipError: On launch failure or timeout.
    """
    try:
        if backend is None:
            handle: SandboxHandle = default_popen_handle(
                argv, cwd=scratch_dir, env=env
            )
        else:
            handle = backend.launch(
                argv, scratch_dir=scratch_dir, env=env, read_paths=read_paths
            )
    except OSError as exc:
        msg = f"preprocessor could not be launched: {exc}"
        raise _PreprocessSkipError(msg) from exc

    try:
        return _drain_and_wait(handle, timeout_s, stdout_cap)
    finally:
        if backend is not None:
            backend.cleanup(handle)


def _invoke_and_validate(
    source_path: pathlib.Path,
    rule: PreprocessRule,
    max_emitted_bytes: int,
    *,
    project_root: pathlib.Path,
    server_mode: bool,
    unsandboxed: bool,
) -> PreprocOutput:
    """Run the preprocessor inside its sandbox, validate, and enforce the caps.

    Resolves the containment backend (fail-closed in server mode), stages the
    source into a per-run scratch dir, rewrites the argv to point at the staged
    copy (so the child reads the file the sandbox grants), and launches it under
    a curated env with read access to the staged dir, the interpreter runtime,
    and the project root.

    Raises:
        _PreprocessSkipError: On any recoverable per-file failure (no backend in
            server mode, misconfigured rule, non-zero exit, timeout, oversize
            stdout, non-JSON or schema-invalid output, or emitted text over the
            cap).
    """
    try:
        backend = _resolve_backend(server_mode=server_mode, unsandboxed=unsandboxed)
    except SandboxUnavailableError as exc:
        raise _PreprocessSkipError(_REFUSED_REASON) from exc

    scratch_dir, staged = stage_source(source_path)
    try:
        argv = _build_argv(rule, staged)
        if not argv:
            msg = "rule has neither a runnable command nor entry_point"
            raise _PreprocessSkipError(msg)

        stdout_cap = max(max_emitted_bytes * _STDOUT_CAP_MULTIPLIER, _MIN_STDOUT_CAP)
        read_paths = [
            scratch_dir,
            pathlib.Path(sys.base_prefix),
            pathlib.Path(sys.prefix),
            project_root,
        ]
        returncode, stdout, stderr = _run_bounded(
            argv,
            rule.timeout_s,
            stdout_cap,
            backend=backend,
            scratch_dir=scratch_dir,
            env=_child_env(project_root),
            read_paths=read_paths,
        )
        output = _validate_output(
            returncode, stdout, stderr, stdout_cap, max_emitted_bytes
        )
        return _remap_staged_paths(output, staged=staged, original=source_path)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


def _remap_staged_paths(
    output: PreprocOutput,
    *,
    staged: pathlib.Path,
    original: pathlib.Path,
) -> PreprocOutput:
    """Rewrite staged-scratch paths in the output back to the real source.

    The hook sees the staged copy as its input (the sandbox grants only that
    file), so a hook that echoes its argv into ``source_path`` or a unit
    ``anchor`` emits the ephemeral scratch path. Deep links must point at the
    real file, so every reference to the staged path is remapped to the original
    source before the output is indexed. Both the native string and the
    forward-slash form are replaced so an anchor built with either separator is
    covered.
    """
    staged_variants = (str(staged), str(staged).replace("\\", "/"))
    original_str = str(original)

    def _fix(value: str) -> str:
        for variant in staged_variants:
            if variant in value:
                value = value.replace(variant, original_str)
        return value

    updates: dict[str, object] = {"source_path": _fix(output.source_path)}
    if output.units is not None:
        remapped = [
            unit.model_copy(update={"anchor": _fix(unit.anchor)})
            if unit.anchor is not None
            else unit
            for unit in output.units
        ]
        updates["units"] = remapped
    return output.model_copy(update=updates)


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
    project_root: pathlib.Path,
    server_mode: bool,
    unsandboxed: bool,
) -> PreprocessResult:
    """Run a command rule against one source file and resolve its disposition.

    Args:
        source_path: Absolute path to the source file to preprocess.
        rule: The matched, validated command rule.
        max_emitted_bytes: The emitted-text length cap (D10).
        project_root: The project root, granted read-only to the sandboxed hook
            so it can read its own module tree (ADR D2).
        server_mode: ``True`` when the resident service runs the hook, selecting
            the fail-closed sandbox policy (ADR D6).
        unsandboxed: ``True`` when the operator opted out of OS containment
            (ADR D8); the child still runs under the curated env and scratch cwd.

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
            server_mode=server_mode,
            unsandboxed=unsandboxed,
        )
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
