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
temporary directory: ``uv run``, ``uv sync``, ``uv lock``, ``uv add``,
``uv remove`` and ``uv venv`` on a project, ``uv pip`` on an interpreter, and
``uv tool`` on the tool directory. uv answers a request it cannot apply in
place by rebuilding the environment, which removes its contents before it
fails on the files a running service holds, so a test that steers a repair or
a sync at a real installation destroys it. ``uv run`` is no exception, with or
without ``--no-sync``: it creates a project environment that is absent and
replaces one it finds unusable before it looks at that flag, and an
environment built by another operating system over the same checkout is one
it finds unusable. Every environment a test may change is one it created
under its own temporary tree. The one launch let through outside it is
``uv run --no-sync`` on the environment this interpreter is itself running
from, which uv finds usable and leaves as it is.

The hook runs on every audited event in the process, so the matching path is
deliberately cheap: one dictionary lookup on the event name, then a normalised
prefix comparison against at most a handful of roots.  Both the plain and the
fully resolved spellings of each root are protected, so a home directory
reached through a junction or a symlink is covered without resolving every
candidate path at event time.
"""

from __future__ import annotations

import os
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

#: The ``uv pip`` and ``uv tool`` actions that change the environment they act
#: on. A ``--dry-run`` of one of these, or of a project verb below, only
#: resolves, so it is never refused.
_UV_PIP_VERBS = frozenset({"install", "uninstall", "sync"})
_UV_TOOL_VERBS = frozenset({"install", "uninstall", "upgrade"})

#: Verbs that write the project's own files - its lockfile, its manifest - as
#: well as its environment, so the project directory is judged even when the
#: environment has been pointed somewhere else.
_UV_PROJECT_FILE_VERBS = frozenset({"sync", "lock", "add", "remove"})

#: The first word of every launch this guard judges. ``uv run`` is one, with
#: or without ``--no-sync``: the flag stops uv installing into the project
#: environment, not creating or replacing it, and uv does that first. It has
#: no dry run of its own, so a ``--dry-run`` on its command line belongs to
#: the program it runs and excuses nothing. ``uv build`` is not one: it builds
#: in an environment of its own and leaves the project's alone.
_UV_JUDGED_VERBS = _UV_PROJECT_FILE_VERBS | {"run", "venv", "pip", "tool"}

#: Options naming where uv works, each followed by a path. ``--directory`` is
#: where the launch runs; ``--project`` is the project it acts on from there.
_UV_DIRECTORY_OPTION = "--directory"
_UV_PROJECT_OPTION = "--project"

#: ``uv run`` options under which it uses no project environment at all.
_UV_RUN_WITHOUT_PROJECT = frozenset({"--no-project", "--isolated"})

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


def _option_values(words: Sequence[str], names: tuple[str, ...]) -> list[str]:
    """Return every value given to one of *names* in *words*, in order."""
    values: list[str] = []
    for index, word in enumerate(words):
        for name in names:
            if word == name and index + 1 < len(words):
                values.append(words[index + 1])
            elif word.startswith(f"{name}="):
                values.append(word[len(name) + 1 :])
    return values


def _option_value(words: Sequence[str], names: tuple[str, ...]) -> str | None:
    """Return the first value given to one of *names* in *words*, if any."""
    return next(iter(_option_values(words, names)), None)


def _beneath(base: str, path: str | None) -> str:
    """Return *path* taken from *base*, or *base* itself when there is none."""
    return os.path.join(base, path) if path else base


def _launch_variable(env: object, name: str) -> str | None:
    """Return *name* from the launch's environment, else from this process's."""
    source: Mapping[str, object] = (
        cast("Mapping[str, object]", env) if isinstance(env, Mapping) else os.environ
    )
    value = source.get(name)
    return value if isinstance(value, str) and value else None


def _windows_command_words(line: str) -> list[str]:
    """Split a Windows command line the way the program it starts does.

    A backslash is literal unless a run of them reaches a double quote: each
    pair is then one backslash, and an odd one left over makes that quote a
    literal character instead of the start or end of a quoted stretch. An
    argument carrying program text is full of both, and a splitter that gave
    up on such a line would leave the launch unjudged.
    """
    words: list[str] = []
    word: list[str] = []
    quoted = False
    started = False
    backslashes = 0
    for character in line:
        if character == "\\":
            backslashes += 1
            continue
        started = started or bool(backslashes)
        if character == '"':
            word.append("\\" * (backslashes // 2))
            if backslashes % 2:
                word.append('"')
            else:
                quoted = not quoted
            started = True
        elif character in " \t" and not quoted:
            word.append("\\" * backslashes)
            if started:
                words.append("".join(word))
            word, started = [], False
        else:
            word.append("\\" * backslashes + character)
            started = True
        backslashes = 0
    word.append("\\" * backslashes)
    if started or backslashes:
        words.append("".join(word))
    return words


def _command_words(command: object) -> list[str]:
    """Return the words of an audited launch's command.

    POSIX audits the argument vector. Windows audits the command line it has
    already joined, so that is split back into the words it was joined from.
    """
    if isinstance(command, (list, tuple)):
        return [_path_text(word) or "" for word in cast("Sequence[object]", command)]
    line = _path_text(command)
    return [] if line is None else _windows_command_words(line)


def _uv_words(args: tuple[object, ...]) -> list[str]:
    """Return the words after ``uv`` in an audited launch, or none.

    Audited ``subprocess.Popen`` arguments are ``(executable, args, cwd, env)``.
    """
    if len(args) < 4:
        return []
    argv = _command_words(args[1])
    if not argv or Path(argv[0]).stem.casefold() != "uv":
        return []
    return argv[1:]


def _split_at_verb(words: list[str]) -> tuple[list[str], list[str]]:
    """Return the options uv was given ahead of its verb, and the rest.

    A word after an option is that option's value or the verb, and which
    options take a value differs between uv versions. It is read as the verb
    when it names one this guard judges and as a value otherwise, so an option
    this guard does not know can cost a refusal but cannot hide a launch.
    """
    after_option = False
    for index, word in enumerate(words):
        if word.startswith("-"):
            after_option = "=" not in word
        elif after_option and word not in _UV_JUDGED_VERBS:
            after_option = False
        else:
            return words[:index], words[index:]
    return words, []


def _split_at_command(words: list[str]) -> tuple[list[str], list[str]]:
    """Return ``uv run``'s own options, and the command line it was given.

    Only the options that open the launch are certainly uv's. One this guard
    does not know may take a value, which then reads as the command and ends
    uv's options early; what follows is judged as the command's.
    """
    index = 0
    while index < len(words) and words[index].startswith("-"):
        if words[index] == "--":
            return words[:index], words[index + 1 :]
        names_a_path = words[index] in (_UV_DIRECTORY_OPTION, _UV_PROJECT_OPTION)
        index += 2 if names_a_path else 1
    return words[:index], words[index:]


def _launch_directory(words: Sequence[str], here: str) -> str:
    """Return the directory a launch runs in, which ``--directory`` moves."""
    return _beneath(here, _option_value(words, (_UV_DIRECTORY_OPTION,)))


def _project_directory(words: Sequence[str], here: str) -> str:
    """Return the project directory a launch acts on."""
    return _beneath(
        _launch_directory(words, here), _option_value(words, (_UV_PROJECT_OPTION,))
    )


def _stated_environment(words: Sequence[str], env: object, project: str) -> str | None:
    """Return the environment a launch names for itself, if it names one.

    ``--active`` hands the launch to ``VIRTUAL_ENV`` ahead of anything else.
    Otherwise ``UV_PROJECT_ENVIRONMENT`` replaces the project's own ``.venv``,
    and a relative value is taken from the project.
    """
    active = _launch_variable(env, "VIRTUAL_ENV") if "--active" in words else None
    stated = active or _launch_variable(env, "UV_PROJECT_ENVIRONMENT")
    return os.path.join(project, stated) if stated else None


def _discovered_environment(project: str) -> str | None:
    """Return the environment uv finds for *project* when a launch names none.

    uv takes the nearest directory at or above the project that holds a
    ``pyproject.toml`` as the project's root, and that root's ``.venv`` as its
    environment.
    """
    start = Path(os.path.abspath(project))
    for directory in (start, *start.parents):
        if (directory / "pyproject.toml").is_file():
            return str(directory / ".venv")
    return None


def _is_interpreter_environment(environment: str | None) -> bool:
    """Return whether *environment* is the one this interpreter runs from."""
    if environment is None:
        return False
    try:
        return canonical_path(environment) == canonical_path(sys.prefix)
    except OperatorDirectoryWriteError:
        return False


def _run_targets(
    options: list[str], command: list[str], here: str, env: object
) -> tuple[str, ...]:
    """Return what a ``uv run`` launch can create or replace; nothing if let be.

    Let be: a launch that uses no project environment, and a ``--no-sync``
    launch on the environment this interpreter is itself running from. uv
    finds that one usable, because it is in use, and ``--no-sync`` then keeps
    it from installing anything into it. Any other environment outside the
    temporary directory is one it may find absent or unusable, and replace.
    """
    if not _UV_RUN_WITHOUT_PROJECT.isdisjoint(options):
        return ()
    project = _project_directory(options, here)
    environment = _stated_environment(options, env, project)
    # A project named after uv's own options ended is an argument of the
    # command, unless an option this guard does not know ended them early. The
    # two cannot be told apart, so it is judged beside the project uv was read
    # as using rather than trusted to be the command's.
    named_later = tuple(
        _beneath(here, value)
        for value in _option_values(command, (_UV_DIRECTORY_OPTION, _UV_PROJECT_OPTION))
    )
    in_use = _is_interpreter_environment(
        environment or _discovered_environment(project)
    )
    if in_use and "--no-sync" in options and not named_later:
        return ()
    return (environment or project, *named_later)


def _project_targets(words: list[str], here: str, env: object) -> tuple[str, ...]:
    """Return the project a file-writing verb acts on, and its environment."""
    project = _project_directory(words, here)
    environment = _stated_environment(words, env, project)
    return (project,) if environment is None else (project, environment)


def _venv_targets(words: list[str], here: str, env: object) -> tuple[str, ...]:
    """Return what a ``uv venv`` launch can create or replace.

    That is its path argument when it has one. A word after an option may be
    that option's value or the path, so with no certain path each such word is
    judged as one, beside the project environment a launch with no path makes.
    """
    base = _launch_directory(words, here)
    certain: list[str] = []
    possible: list[str] = []
    for index, word in enumerate(words):
        if word.startswith("-"):
            continue
        previous = words[index - 1] if index else ""
        after_option = previous.startswith("-") and "=" not in previous
        (possible if after_option else certain).append(word)
    if certain:
        return (_beneath(base, certain[0]),)
    return (
        *_project_targets(words, here, env),
        *(_beneath(base, word) for word in possible),
    )


def _installer_targets(
    words: list[str], here: str, env: object
) -> tuple[str, tuple[str, ...]] | None:
    """Return the verb and target of a ``uv pip`` or ``uv tool`` change, if any."""
    verb, action = words[0], words[1:2]
    if verb == "pip" and action and action[0] in _UV_PIP_VERBS:
        interpreter = _option_value(words, ("--python", "-p"))
        venv = _launch_variable(env, "VIRTUAL_ENV")
        return f"pip {action[0]}", (interpreter or venv or here,)
    if verb == "tool" and action and action[0] in _UV_TOOL_VERBS:
        tool_dir = _launch_variable(env, "UV_TOOL_DIR")
        return f"tool {action[0]}", (tool_dir or _DEFAULT_UV_TOOL_DIR,)
    return None


def _uv_launch_targets(
    args: tuple[object, ...],
) -> tuple[str, tuple[str, ...]] | None:
    """Return the uv verb and everything a launch could change, if anything.

    ``None`` for anything that is not uv changing an environment. Every
    target returned has to be one a test created, so a launch whose target
    cannot be read with certainty returns each reading of it.
    """
    leading, rest = _split_at_verb(_uv_words(args))
    if not rest:
        return None
    verb, here, env = rest[0], _path_text(args[2]) or ".", args[3]
    if verb == "run":
        options, command = _split_at_command(rest[1:])
        return verb, _run_targets([*leading, *options], command, here, env)
    words = [*leading, *rest[1:]]
    if "--dry-run" in words:
        return None
    if verb == "venv":
        return verb, _venv_targets(words, here, env)
    if verb in _UV_PROJECT_FILE_VERBS:
        return verb, _project_targets(words, here, env)
    return _installer_targets(rest, here, env)


def _refuse_uv_outside_scratch(args: tuple[object, ...]) -> None:
    """Raise when a uv launch would change an environment no test created."""
    launch = _uv_launch_targets(args)
    if launch is None:
        return
    verb, targets = launch
    for target in targets:
        if target != _DEFAULT_UV_TOOL_DIR:
            spelling = _target_spelling(target)
            if spelling is not None and any(
                _is_within(spelling, root) for root in _scratch_roots
            ):
                continue
        raise OperatorDirectoryWriteError(
            f"refusing uv {verb} on {target}: it is outside the system "
            "temporary directory, so it is a project or environment this test "
            "did not create. uv rebuilds an environment it cannot use or "
            "change in place, and `uv run` does so even with --no-sync; point "
            "the launch at one under the test's own temporary tree."
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
