"""Parity between vaultspec-rag and the installed vaultspec-core.

The env-parity contract is that rag imports one resolution order, one boolean
vocabulary, and one install surface from core rather than mirroring them. A
regression in any of those looks the same either way - a value that once
agreed between the two packages quietly drifts - so this file checks the
contract directly against the installed core, not against a restated copy of
its rules:

(a) the shared framework variables (root, log level, watchdog) resolve the
    same answer in both packages from the same environment, and unattended
    detection is literally core's own function, not a second one;
(b) rag's boolean vocabulary is core's vocabulary - the same table objects,
    not a copy that could drift;
(c) no rag console-script entry module loads a ``.env`` outside the gate;
(d) every install/uninstall flag rag shares with core carries the same name,
    short form, and default - introspected from the real Typer/Click command
    objects, never from parsed ``--help`` text.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from typing import TYPE_CHECKING, cast

import pytest
import typer.main
from typer.core import TyperOption
from vaultspec_core import env_values as core_env_values
from vaultspec_core.cli import app as core_app
from vaultspec_core.config import VAULTSPEC_LOG_LEVEL, resolve_target
from vaultspec_core.config import is_unattended as core_is_unattended
from vaultspec_core.logging_config import resolve_log_level
from vaultspec_core.mcp_server.kill_switch import (
    watchdog_disabled as core_watchdog_disabled,
)

from .._named_root import named_root
from ..cli import app as rag_app
from ..cli._install import is_unattended as rag_imported_is_unattended
from ..config._registry import entry
from ..config._types import EnvVar
from ..server._stdio_lifetime import watchdog_disabled as rag_watchdog_disabled

if TYPE_CHECKING:
    from pathlib import Path

    # Typer vendors its own copy of Click, so a command tree
    # ``typer.main.get_command`` returns is built from ``typer._click``, not
    # the top-level ``click`` package (see test_uninstall_safety.py).
    from typer._click.core import Command

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# (a) Shared framework variables: same answer from the same environment.
# ---------------------------------------------------------------------------


def test_root_parity_with_only_the_shared_variable_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A session naming only the framework-wide root resolves it in both."""
    monkeypatch.delenv(EnvVar.RAG_ROOT.value, raising=False)
    monkeypatch.setenv("VAULTSPEC_TARGET_DIR", str(tmp_path))

    rag_resolved = named_root()
    core_resolved = resolve_target(None)

    assert rag_resolved.path == core_resolved.path == tmp_path.resolve()


def test_root_parity_without_either_variable_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Neither rung naming a root: both discover, neither invents one."""
    monkeypatch.delenv(EnvVar.RAG_ROOT.value, raising=False)
    monkeypatch.delenv("VAULTSPEC_TARGET_DIR", raising=False)

    rag_resolved = named_root()
    core_resolved = resolve_target(None)

    assert rag_resolved.path is None
    assert core_resolved.path is None


def test_root_scoped_override_does_not_leak_into_core(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Rag's own scoped name overrides rag alone; core still sees the shared one."""
    scoped = tmp_path / "scoped"
    scoped.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setenv(EnvVar.RAG_ROOT.value, str(scoped))
    monkeypatch.setenv("VAULTSPEC_TARGET_DIR", str(shared))

    rag_resolved = named_root()
    core_resolved = resolve_target(None)

    assert rag_resolved.path == scoped.resolve()
    assert core_resolved.path == shared.resolve()


def test_log_level_parity_with_only_the_shared_variable_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session naming only the framework-wide level resolves it in both."""
    monkeypatch.delenv(EnvVar.LOG_LEVEL.value, raising=False)
    monkeypatch.setenv(VAULTSPEC_LOG_LEVEL.env_name, "DEBUG")

    rag_level = resolve_log_level(variable=entry(EnvVar.LOG_LEVEL))
    core_level = resolve_log_level(variable=VAULTSPEC_LOG_LEVEL)

    assert rag_level == core_level == "DEBUG"


def test_log_level_parity_rejects_the_same_bad_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from vaultspec_core.config import ConfigurationError

    monkeypatch.delenv(EnvVar.LOG_LEVEL.value, raising=False)
    monkeypatch.setenv(VAULTSPEC_LOG_LEVEL.env_name, "WARNIGN")

    with pytest.raises(ConfigurationError):
        resolve_log_level(variable=entry(EnvVar.LOG_LEVEL))
    with pytest.raises(ConfigurationError):
        resolve_log_level(variable=VAULTSPEC_LOG_LEVEL)


def test_watchdog_parity_with_only_the_shared_variable_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session disarming the shared watchdog name disarms rag's too."""
    monkeypatch.delenv(EnvVar.STDIO_WATCHDOG.value, raising=False)
    monkeypatch.setenv("VAULTSPEC_STDIO_WATCHDOG", "0")

    assert rag_watchdog_disabled() is True
    assert core_watchdog_disabled("0") is True


def test_watchdog_parity_unset_stays_armed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EnvVar.STDIO_WATCHDOG.value, raising=False)
    monkeypatch.delenv("VAULTSPEC_STDIO_WATCHDOG", raising=False)

    assert rag_watchdog_disabled() is False
    assert core_watchdog_disabled(None) is False


def test_unattended_detection_is_cores_own_function() -> None:
    """Rag imports core's ``is_unattended`` rather than reimplementing it."""
    assert rag_imported_is_unattended is core_is_unattended


# ---------------------------------------------------------------------------
# (b) Rag's boolean vocabulary IS core's - identity, not a copy.
# ---------------------------------------------------------------------------

_VOCABULARY_IMPORT_SITES: tuple[tuple[str, str], ...] = (
    ("vaultspec_rag.config._settings", "parse_bool"),
    ("vaultspec_rag.config._settings", "BOOL_SHAPE"),
    ("vaultspec_rag.config._types", "parse_bool"),
    ("vaultspec_rag.server._stdio_lifetime", "parse_bool"),
    ("vaultspec_rag.server._stdio_lifetime", "BOOL_SHAPE"),
    ("vaultspec_rag.memory_probe", "parse_bool"),
    ("vaultspec_rag.memory_probe", "BOOL_SHAPE"),
    ("vaultspec_rag.memory_probe", "is_blank"),
    ("vaultspec_rag.config._schema", "rejection"),
)


@pytest.mark.parametrize(
    ("module_path", "attr"),
    _VOCABULARY_IMPORT_SITES,
    ids=[f"{mod}.{attr}" for mod, attr in _VOCABULARY_IMPORT_SITES],
)
def test_every_rag_vocabulary_site_holds_cores_own_object(
    module_path: str, attr: str
) -> None:
    module = importlib.import_module(module_path)
    assert getattr(module, attr) is getattr(core_env_values, attr)


def test_no_rag_module_declares_a_shadow_vocabulary_table() -> None:
    """A local ``TRUE_TOKENS``/``FALSE_TOKENS`` would be the copy this guards."""
    import pathlib

    package_root = pathlib.Path(
        importlib.import_module("vaultspec_rag").__file__  # type: ignore[arg-type]
    ).parent
    offenders: list[str] = []
    for path in package_root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        has_table_name = "TRUE_TOKENS" in text or "FALSE_TOKENS" in text
        if has_table_name and "from vaultspec_core" not in text:
            offenders.append(str(path))
    assert not offenders, offenders


# ---------------------------------------------------------------------------
# (c) No rag entry point loads a .env outside the gate.
# ---------------------------------------------------------------------------

_ENTRY_MODULES = ("vaultspec_rag.__main__", "vaultspec_rag.server")


@pytest.mark.parametrize("module", _ENTRY_MODULES)
def test_console_script_entry_module_never_imports_dotenv(module: str) -> None:
    """Importing an entry module alone must not register ``dotenv``.

    Runs in a fresh interpreter subprocess so no prior import in this test
    process can taint the result, mirroring the same proof already made for
    the CLI package (``test_cli_no_dotenv_load.py``) but for every
    console-script entry point rather than just one.
    """
    script = f"import sys; import {module}; print('dotenv' in sys.modules)"
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "False", proc.stderr


# ---------------------------------------------------------------------------
# (d) Shared install/uninstall flags exist in both CLIs, introspected.
# ---------------------------------------------------------------------------


def _root_command(app: typer.Typer) -> Command:
    return typer.main.get_command(app)


def _subcommand(app: typer.Typer, name: str) -> Command:
    root = _root_command(app)
    commands = cast("dict[str, Command]", getattr(root, "commands", None) or {})
    return commands[name]


def _find_option(command: Command, long_flag: str) -> TyperOption:
    for param in command.params:
        opts = getattr(param, "opts", [])
        if long_flag in opts:
            assert isinstance(param, TyperOption)
            return param
    raise AssertionError(f"{long_flag} is not registered on {command.name!r}")


#: The root options every vaultspec package shares: long flag -> short flag.
_SHARED_ROOT_FLAGS: dict[str, str] = {
    "--target": "-t",
    "--debug": "-d",
    "--verbose": "-v",
    "--version": "-V",
}


@pytest.mark.parametrize(
    ("long_flag", "short_flag"), sorted(_SHARED_ROOT_FLAGS.items())
)
def test_shared_root_flags_match_core(long_flag: str, short_flag: str) -> None:
    core_param = _find_option(_root_command(core_app), long_flag)
    rag_param = _find_option(_root_command(rag_app), long_flag)

    assert short_flag in core_param.opts
    assert short_flag in rag_param.opts
    assert core_param.default == rag_param.default
    assert core_param.is_flag == rag_param.is_flag


#: The install flags every vaultspec package shares: long flag -> short
#: flag, or ``None`` where the flag has no short form.
_SHARED_INSTALL_FLAGS: dict[str, str | None] = {
    "--target": "-t",
    "--upgrade": None,
    "--dry-run": None,
    "--force": None,
    "--skip": None,
    "--mode": None,
    "--json": None,
    "--no-hints": None,
}


@pytest.mark.parametrize(
    ("long_flag", "short_flag"), sorted(_SHARED_INSTALL_FLAGS.items())
)
def test_shared_install_flags_match_core(
    long_flag: str, short_flag: str | None
) -> None:
    core_param = _find_option(_subcommand(core_app, "install"), long_flag)
    rag_param = _find_option(_subcommand(rag_app, "install"), long_flag)

    if short_flag is not None:
        assert short_flag in core_param.opts
        assert short_flag in rag_param.opts
    assert core_param.is_flag == rag_param.is_flag
    assert getattr(core_param, "multiple", False) == getattr(
        rag_param, "multiple", False
    )
    if long_flag == "--skip":
        # Both declare a repeatable option with no entries by default; core
        # spells that default ``None`` and rag ``()``, which read identically
        # to every caller that iterates them.
        assert not core_param.default
        assert not rag_param.default
    else:
        assert core_param.default == rag_param.default


def test_uninstall_shares_target_and_json_with_core() -> None:
    """``uninstall`` carries the root-selector and machine-output flags too.

    ``--upgrade``/``--mode``/``--no-hints`` are install-only in every
    package, so this checks only the subset uninstall actually declares.
    """
    shared_flags = (
        ("--target", "-t"),
        ("--force", None),
        ("--dry-run", None),
        ("--json", None),
    )
    for long_flag, short_flag in shared_flags:
        core_param = _find_option(_subcommand(core_app, "uninstall"), long_flag)
        rag_param = _find_option(_subcommand(rag_app, "uninstall"), long_flag)
        if short_flag is not None:
            assert short_flag in core_param.opts
            assert short_flag in rag_param.opts
        assert core_param.is_flag == rag_param.is_flag
        assert core_param.default == rag_param.default
