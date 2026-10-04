"""Refuse any mutation of the operator's real managed directories and environments.

The suite redirects the managed status directory and the Qdrant storage
directory at a session temporary tree, and re-arms that redirection at both
boundaries of every test.  That is what keeps a test away from the operator's
resident service.  This guard is the backstop for the case the redirection
misses: a path computed before the redirection, a cached configuration object,
a hard-coded default.

It is a process-wide audit hook, installed once at session start with the
operator's real directories resolved before the redirection is applied.  From
then on, any audited filesystem mutation whose target is one of those
directories or anything beneath it raises.  The guard does nothing else: it
never redirects, never creates, never deletes, and reads are untouched, so a
test that legitimately inspects the real installation still can.

The same hook refuses launching uv to change an environment outside the system
temporary directory: ``uv sync`` on a project, ``uv pip`` on an interpreter,
and ``uv tool`` on the tool directory. uv answers a request it cannot apply in
place by rebuilding the environment, which removes its contents before it
fails on the files a running service holds, so a test that steers a repair or
a sync at a real installation destroys it. Every environment a test may change
is one it created under its own temporary tree.

The hook runs on every audited event in the process, so the matching path is
deliberately cheap: one dictionary lookup on the event name, then a normalised
prefix comparison against at most a handful of roots.  Both the plain and the
fully resolved spellings of each root are protected, so a home directory
reached through a junction or a symlink is covered without resolving every
candidate path at event time.
"""

from __future__ import annotations

import os
import shlex
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from os import PathLike

__all__ = [
    "OperatorDirectoryWriteError",
    "canonical_path",
    "guarded_operator_roots",
    "install_operator_directory_guard",
    "operator_managed_roots",
]


class OperatorDirectoryWriteError(RuntimeError):
    """A test tried to mutate the operator's real managed directory."""


def _without_windows_extended_prefix(raw: str) -> str:
    """Return the ordinary spelling of a Windows extended-length path."""
    if os.name != "nt":
        return raw
    normalized = raw.replace("/", "\\")
    folded = normalized.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        return f"\\\\{normalized[8:]}"
    if folded.startswith("\\\\?\\"):
        return normalized[4:]
    if folded.startswith("\\??\\"):
        return normalized[4:]
    if folded.startswith("\\\\.\\"):
        raise OperatorDirectoryWriteError(
            f"Windows device paths cannot identify a managed directory: {raw!r}"
        )
    return raw


def canonical_path(path: str | PathLike[str]) -> Path:
    """Resolve aliases, links, junctions, ``..``, and path casing."""
    raw = os.fspath(path)
    if not raw:
        raise OperatorDirectoryWriteError(
            "an empty path cannot identify a managed directory"
        )
    try:
        candidate = Path(_without_windows_extended_prefix(raw)).expanduser()
        resolved = candidate.resolve(strict=False)
        normalized = os.path.normcase(
            os.path.normpath(_without_windows_extended_prefix(str(resolved)))
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        raise OperatorDirectoryWriteError(
            f"could not canonicalize managed directory path {raw!r}: {exc}"
        ) from exc
    return Path(normalized)


def operator_managed_roots(*, inherited_isolation: bool) -> tuple[str, ...]:
    """Return the real managed directories this session must never mutate.

    The defaults are always included: they are where a process that was told
    nothing resolves the resident service, its lock, its discovery pointer and
    its Qdrant identity, which is exactly what an escaped test reaches.  The
    ambient overrides are included too when this process is not nested inside
    another test session, because an operator who configured the service
    elsewhere has their real directories there and nowhere else.  A nested
    session's ambient values name its parent's temporary tree, which is not an
    operator directory and must stay writable.

    Returns the normalised absolute spellings, plain and fully resolved, with
    duplicates and nested entries removed.
    """
    from ..config._settings import rag_default
    from ..config._types import EnvVar

    candidates: list[str] = [
        str(rag_default("status_dir")),
        str(rag_default("qdrant_storage_dir")),
    ]
    if not inherited_isolation:
        for name in (EnvVar.STATUS_DIR.value, EnvVar.QDRANT_STORAGE_DIR.value):
            configured = os.environ.get(name)
            if configured:
                candidates.append(configured)

    spellings: set[str] = set()
    for candidate in candidates:
        expanded = Path(candidate).expanduser()
        spellings.add(os.path.normcase(os.path.abspath(expanded)))
        spellings.add(os.path.normcase(str(canonical_path(expanded))))
    return _without_nested_entries(spellings)


def _without_nested_entries(spellings: Iterable[str]) -> tuple[str, ...]:
    """Drop every spelling already covered by a shorter one in the set."""
    ordered = sorted(spellings, key=len)
    kept: list[str] = []
    for spelling in ordered:
        if not any(_is_within(spelling, root) for root in kept):
            kept.append(spelling)
    return tuple(kept)


def _is_within(candidate: str, root: str) -> bool:
    """Return whether *candidate* is *root* or sits beneath it."""
    return candidate == root or candidate.startswith(root + os.sep)


#: Watched audit events, each mapped to the argument positions that name a
#: mutation target. ``os.remove`` covers ``os.unlink`` and ``os.rename`` covers
#: ``os.replace``; both pairs raise one event in CPython. The composite
#: ``shutil`` events are watched as well as the primitives they are built from,
#: so a refusal names the operation the test actually asked for.
_WATCHED_EVENTS: dict[str, tuple[int, ...]] = {
    "open": (0,),
    "os.remove": (0,),
    "os.rename": (0, 1),
    "os.mkdir": (0,),
    "os.rmdir": (0,),
    "os.truncate": (0,),
    "os.link": (0, 1),
    "os.symlink": (0, 1),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.utime": (0,),
    "shutil.rmtree": (0,),
    "shutil.move": (0, 1),
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.copytree": (1,),
}

#: Open flags that can create, truncate, extend or overwrite. Checked only when
#: the mode argument is absent, which is how ``os.open`` reports itself.
_WRITING_OPEN_FLAGS = (
    os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC | os.O_EXCL
)

#: uv verbs that change the environment they act on. ``uv run`` is absent on
#: purpose: the suite launches its own children through it with ``--no-sync``.
#: A ``--dry-run`` of any of them only resolves, so it is never refused.
_UV_PIP_VERBS = frozenset({"install", "uninstall", "sync"})
_UV_TOOL_VERBS = frozenset({"install", "uninstall", "upgrade"})

#: What a ``uv tool`` verb changes when its launch names no tool directory.
_DEFAULT_UV_TOOL_DIR = "uv's default tool directory"

_guarded_roots: tuple[str, ...] = ()
_scratch_roots: tuple[str, ...] = ()
_guard_installed = False


def guarded_operator_roots() -> tuple[str, ...]:
    """Return the roots the installed guard is refusing mutations beneath."""
    return _guarded_roots


def _path_text(value: object) -> str | None:
    """Return *value* as text when it spells a path, else ``None``."""
    raw: object = (
        os.fspath(cast("os.PathLike[str]", value))
        if isinstance(value, os.PathLike)
        else value
    )
    if isinstance(raw, bytes):
        return os.fsdecode(raw)
    return raw if isinstance(raw, str) else None


def _target_spelling(value: object) -> str | None:
    """Return the normalised absolute path *value* names, or ``None``.

    A file descriptor, a ``None`` placeholder and anything else that is not a
    path names no directory entry this guard can be about.
    """
    try:
        text = _path_text(value)
        if not text:
            return None
        return os.path.normcase(os.path.abspath(text))
    except (OSError, TypeError, ValueError):
        return None


def _open_is_writing(args: Sequence[object]) -> bool:
    """Return whether an ``open`` audit event describes a mutating open.

    Undecidable shapes are reported as writing: refusing a read is a visible,
    repairable test failure, while allowing a write is the damage this exists
    to prevent.
    """
    mode = args[1] if len(args) > 1 else None
    if isinstance(mode, str):
        return any(character in mode for character in "wxa+")
    flags = args[2] if len(args) > 2 else None
    if isinstance(flags, int):
        return bool(flags & _WRITING_OPEN_FLAGS)
    return True


def _option_value(words: Sequence[str], names: tuple[str, ...]) -> str | None:
    """Return the value given to the first of *names* in *words*, if any."""
    for index, word in enumerate(words):
        for name in names:
            if word == name and index + 1 < len(words):
                return words[index + 1]
            if word.startswith(f"{name}="):
                return word[len(name) + 1 :]
    return None


def _launch_variable(env: object, name: str) -> str | None:
    """Return *name* from the launch's environment, else from this process's."""
    source: Mapping[str, object] = (
        cast("Mapping[str, object]", env) if isinstance(env, Mapping) else os.environ
    )
    value = source.get(name)
    return value if isinstance(value, str) and value else None


def _command_words(command: object) -> list[str]:
    """Return the words of an audited launch's command.

    POSIX audits the argument vector. Windows audits the command line it has
    already joined, so that is split back into words with its quoting removed.
    """
    if isinstance(command, (list, tuple)):
        return [_path_text(word) or "" for word in cast("Sequence[object]", command)]
    line = _path_text(command)
    if line is None:
        return []
    try:
        words = shlex.split(line, posix=False)
    except ValueError:
        return []
    return [
        word[1:-1] if len(word) > 1 and word[0] == word[-1] == '"' else word
        for word in words
    ]


def _uv_launch_target(args: tuple[object, ...]) -> tuple[str, str] | None:
    """Return the uv verb and the environment a launch would change, if any.

    ``None`` for anything that is not uv changing an environment. Audited
    ``subprocess.Popen`` arguments are ``(executable, args, cwd, env)``.
    """
    if len(args) < 4:
        return None
    argv = _command_words(args[1])
    if not argv or Path(argv[0]).stem.casefold() != "uv" or "--dry-run" in argv:
        return None
    words = argv[1:]
    while words and words[0].startswith("-"):
        words = words[1:]
    cwd, env = args[2], args[3]
    here = _path_text(cwd) or "."
    if words[:1] == ["sync"]:
        project = _option_value(words, ("--project", "--directory"))
        return "sync", project or here
    if words[:1] == ["pip"] and words[1:2] and words[1] in _UV_PIP_VERBS:
        interpreter = _option_value(words, ("--python", "-p"))
        venv = _launch_variable(env, "VIRTUAL_ENV")
        return f"pip {words[1]}", interpreter or venv or here
    if words[:1] == ["tool"] and words[1:2] and words[1] in _UV_TOOL_VERBS:
        tool_dir = _launch_variable(env, "UV_TOOL_DIR")
        return f"tool {words[1]}", tool_dir or _DEFAULT_UV_TOOL_DIR
    return None


def _refuse_uv_outside_scratch(args: tuple[object, ...]) -> None:
    """Raise when a uv launch would change an environment no test created."""
    launch = _uv_launch_target(args)
    if launch is None:
        return
    verb, target = launch
    if target != _DEFAULT_UV_TOOL_DIR:
        spelling = _target_spelling(target)
        if spelling is not None and any(
            _is_within(spelling, root) for root in _scratch_roots
        ):
            return
    raise OperatorDirectoryWriteError(
        f"refusing uv {verb} on {target}: it is outside the system temporary "
        "directory, so it is an environment this test did not create. uv "
        "rebuilds an environment it cannot change in place; point the launch "
        "at an environment under the test's own temporary tree."
    )


def _audit(event: str, args: tuple[object, ...]) -> None:
    """Raise when an audited mutation targets a guarded operator directory."""
    positions = _WATCHED_EVENTS.get(event)
    if positions is None:
        if event == "subprocess.Popen":
            _refuse_uv_outside_scratch(args)
        return
    for position in positions:
        if position >= len(args):
            continue
        candidate = _target_spelling(args[position])
        if candidate is None:
            continue
        for root in _guarded_roots:
            if not _is_within(candidate, root):
                continue
            if event == "open" and not _open_is_writing(args):
                return
            raise OperatorDirectoryWriteError(
                f"refusing {event} on {candidate}: it is inside the operator's "
                f"real managed directory {root}. This test escaped the session's "
                "isolated status and Qdrant storage directories; point every "
                "managed path it reaches at its own temporary tree."
            )


def install_operator_directory_guard(roots: tuple[str, ...]) -> None:
    """Install the process-wide refusal for *roots*, once per process.

    An audit hook cannot be removed once added, which is the property that
    makes it a guarantee: no test can lift it for itself. Installation is
    therefore idempotent and the roots are fixed at the first call, as is the
    temporary directory uv launches must stay beneath.
    """
    global _guarded_roots, _scratch_roots, _guard_installed
    if _guard_installed:
        return
    _guarded_roots = roots
    scratch = Path(tempfile.gettempdir())
    _scratch_roots = _without_nested_entries(
        {
            os.path.normcase(os.path.abspath(scratch)),
            os.path.normcase(str(canonical_path(scratch))),
        }
    )
    _guard_installed = True
    sys.addaudithook(_audit)
