"""Guards on the framework registry this package declares its variables to.

The registry is what the shared accessors resolve against: a name it does not
carry cannot be read through them at all, and a name it carries with the wrong
metadata is worse than absent. Three properties are load-bearing and none is
visible from the module that declares them, because each is a claim about the
whole set rather than about one entry:

- every declared name is registered, exactly once, to this package - so the
  enum and the registry cannot drift into two different lists;
- exactly the credentials are secret, and exactly the two a repository may
  legitimately supply are eligible for a workspace ``.env`` - so a settings
  knob can never be read out of repository content;
- exactly the three shared settings chain to a framework name, and no
  credential chains at all.

The resolution behaviour those declarations buy is then exercised against real
environment mappings rather than asserted from the declarations again, so a
test cannot pass by restating the table it is checking.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from vaultspec_core.config import (
    VAULTSPEC_LOG_LEVEL,
    VAULTSPEC_STDIO_WATCHDOG,
    VAULTSPEC_TARGET_DIR,
    VariableScope,
    env_source,
    env_value,
)

from ..commands import _mcp_topology as commands_mcp_topology
from ..config._registry import PACKAGE, entry
from ..config._settings import get_config, reset_config
from ..config._types import EnvVar
from ..indexer._preprocess_schema import PREPROCESS_INVOCATION_ENV
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._scaffold import restore_env, set_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

#: The prefix a name this package owns carries.
_OWNED_PREFIX = "VAULTSPEC_RAG_"

#: The credentials, and nothing else, must be secret.
_EXPECTED_SECRETS = {
    EnvVar.TYPESAFE_API_KEY,
    EnvVar.QDRANT_API_KEY,
    EnvVar.HF_TOKEN,
}

#: The credentials a workspace ``.env`` may supply. The Qdrant key is excluded
#: on purpose: it addresses an operator's own deployment, and repository
#: content has no business naming one.
_EXPECTED_DOTENV = {EnvVar.TYPESAFE_API_KEY, EnvVar.HF_TOKEN}

#: The settings shared with the rest of the framework, and the framework name
#: each falls back to.
_EXPECTED_FALLBACKS = {
    EnvVar.RAG_ROOT: VAULTSPEC_TARGET_DIR,
    EnvVar.LOG_LEVEL: VAULTSPEC_LOG_LEVEL,
    EnvVar.STDIO_WATCHDOG: VAULTSPEC_STDIO_WATCHDOG,
}


@pytest.fixture
def clean_chain() -> Iterator[None]:
    """Unset the scoped and framework names these tests drive, then restore."""
    scoped = {var: os.environ.pop(var.value, None) for var in _EXPECTED_FALLBACKS}
    framework = {
        shared.env_name: os.environ.pop(shared.env_name, None)
        for shared in _EXPECTED_FALLBACKS.values()
    }
    port = os.environ.pop(EnvVar.PORT.value, None)
    reset_config()
    try:
        yield
    finally:
        for var, previous in scoped.items():
            restore_env(var, previous)
        for name, previous in framework.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
        restore_env(EnvVar.PORT, port)
        reset_config()


def test_every_declared_variable_is_registered_once_to_this_package() -> None:
    """The enum and the registry are one list, bound to one owner.

    An entry belongs to exactly one package, because registration is what the
    credential gate consults to decide whose install mode opens a workspace
    ``.env``. A member missing from the registry is unreadable through the
    shared accessors; a name appearing twice would make that ownership
    ambiguous.
    """
    entries = [entry(var) for var in EnvVar]
    assert [item.env_name for item in entries] == [var.value for var in EnvVar]
    assert {item.package for item in entries} == {PACKAGE}
    names = [item.env_name for item in entries]
    assert len(set(names)) == len(names)


def test_scope_follows_the_prefix_rule() -> None:
    """A name this package owns is a product setting; anything else is not.

    The framework refuses the mismatch outright - a product entry whose name
    lacks the prefix cannot be constructed - so what this pins is the
    classification itself: that no third-party convention was quietly claimed
    as a setting of ours, and no setting of ours was filed as somebody else's.
    """
    misfiled = sorted(
        var.name
        for var in EnvVar
        if (entry(var).scope is VariableScope.PRODUCT)
        != var.value.startswith(_OWNED_PREFIX)
        and entry(var).scope is not VariableScope.INTERNAL
    )
    assert not misfiled


def test_exactly_the_transport_markers_are_internal() -> None:
    """A marker this package sets on its own children is not a knob.

    Scope is what keeps the collective startup check off them: refusing to
    start because a JSON execution envelope is not a valid setting would be
    refusing over a value no operator wrote.
    """
    internal = {var for var in EnvVar if entry(var).scope is VariableScope.INTERNAL}

    assert internal == {
        EnvVar.RAG_JUNCTION_PATH,
        EnvVar.RAG_JUNCTION_TARGET,
        EnvVar.PREPROCESS_INVOCATION,
    }


def test_exactly_the_credentials_are_secret() -> None:
    """A secret's value is withheld from diagnostics; a setting's is not."""
    secret = {var for var in EnvVar if entry(var).secret}
    assert secret == _EXPECTED_SECRETS


def test_only_the_gated_credentials_are_eligible_for_a_workspace_dotenv() -> None:
    """Repository content may supply these two keys, and nothing else.

    Marking a settings knob eligible would reopen exactly the boundary the
    gate exists to close: a cloned repository configuring a tool that merely
    happens to run inside it.
    """
    eligible = {var for var in EnvVar if entry(var).workspace_dotenv}
    assert eligible == _EXPECTED_DOTENV


def test_only_the_shared_settings_chain_to_a_framework_name() -> None:
    """Three names fall back, each to the framework name it shares a meaning with.

    A credential never chains: a key provisioned for one package must not
    enrol another through a second name.
    """
    chained = {var: entry(var).fallback for var in EnvVar if entry(var).fallback}
    assert chained == _EXPECTED_FALLBACKS
    assert not [var for var in _EXPECTED_FALLBACKS if entry(var).secret]


def test_only_the_watchdog_fails_safe() -> None:
    """One protective switch is exempt from reject-on-invalid, and only one."""
    assert {var for var in EnvVar if entry(var).fail_safe} == {EnvVar.STDIO_WATCHDOG}


@pytest.mark.parametrize("var", sorted(_EXPECTED_FALLBACKS, key=lambda v: v.value))
def test_the_scoped_name_outranks_the_framework_name(var: EnvVar) -> None:
    """A session setting both gets the scoped answer, naming the scoped source."""
    shared = _EXPECTED_FALLBACKS[var]
    environ = {var.value: "scoped", shared.env_name: "framework"}
    assert env_value(entry(var), environ) == "scoped"
    assert env_source(entry(var), environ) is entry(var)


@pytest.mark.parametrize("var", sorted(_EXPECTED_FALLBACKS, key=lambda v: v.value))
def test_the_framework_name_answers_when_the_scoped_one_is_blank(var: EnvVar) -> None:
    """A blank scoped name is unset, so the shared name behind it answers.

    A diagnostic must then name the variable the operator actually set, which
    is the framework one, not the scoped one that supplied nothing.
    """
    shared = _EXPECTED_FALLBACKS[var]
    environ = {var.value: "   ", shared.env_name: "framework"}
    assert env_value(entry(var), environ) == "framework"
    assert env_source(entry(var), environ) is shared


def test_an_unchained_setting_never_reads_a_framework_name() -> None:
    """Only the three shared settings look past their own name."""
    environ = {VAULTSPEC_TARGET_DIR.env_name: "elsewhere"}
    assert env_value(entry(EnvVar.DATA_DIR), environ) is None


@pytest.mark.usefixtures("clean_chain")
def test_a_blank_numeric_setting_falls_through_to_its_default() -> None:
    """Blank is unset for every key, not a value to be parsed or refused.

    ``VAR="$UNSET"`` exports a blank string from a shell, and the resolution
    contract is that it means the same as never setting it at all - for a
    number as much as for a path.
    """
    previous = set_env(EnvVar.PORT, "   ")
    try:
        reset_config()
        assert get_config().mcp_port == 8766
    finally:
        restore_env(EnvVar.PORT, previous)
        reset_config()


@pytest.mark.usefixtures("clean_chain")
def test_a_setting_arrives_stripped() -> None:
    """Surrounding whitespace resolves rather than refusing the value."""
    previous = set_env(EnvVar.PORT, "  9001\t")
    try:
        reset_config()
        assert get_config().mcp_port == 9001
    finally:
        restore_env(EnvVar.PORT, previous)
        reset_config()


@pytest.mark.usefixtures("clean_chain")
def test_the_settings_chain_honours_the_framework_log_level() -> None:
    """A session that sets only the shared level configures this package too."""
    os.environ[VAULTSPEC_LOG_LEVEL.env_name] = "DEBUG"
    reset_config()
    assert get_config().log_level == "DEBUG"


def test_the_registry_stays_off_the_spawn_worker_import_chain() -> None:
    """The cheap modules a spawn worker re-imports must not reach the registry.

    The registry pulls the framework configuration package, which costs an
    order of magnitude more to import than the stdlib-only value vocabulary,
    and a spawn-started worker pays that cost once per worker. The probe runs
    in a fresh interpreter because this one's module table is polluted by
    every test that ran before it.
    """
    assert_fresh_import_excludes(
        import_probe_source(
            "vaultspec_core.env_values",
            "vaultspec_rag.memory_probe",
            forbidden=("vaultspec_core.config", "vaultspec_rag.config._registry"),
        )
    )


def test_the_junction_child_is_handed_the_names_its_command_reads() -> None:
    """Both sides of a two-process handshake are spelled from one enum.

    The path and the target travel through the child's environment rather
    than its command line, which is what keeps them out of a string a shell
    would interpret. That only works while the names the parent sets and the
    names the command reads are the same two, and they live in two different
    languages - so a rename that reached one side and not the other would
    silently produce a junction command with two empty arguments.
    """
    source = Path(commands_mcp_topology.__file__).read_text(encoding="utf-8")
    written = re.findall(r"EnvVar\.(RAG_JUNCTION_\w+)\.value:", source)
    read = re.findall(r"\$env:\{EnvVar\.(RAG_JUNCTION_\w+)\.value\}", source)

    assert written == ["RAG_JUNCTION_PATH", "RAG_JUNCTION_TARGET"]
    assert read == written


def test_the_preprocessor_envelope_keeps_the_name_its_readers_know() -> None:
    """A name user-authored code reads is not this package's to rename.

    Every other marker took the package prefix; this one did not, because
    the processes on the other side of it are extractors people wrote
    against the documented name.
    """
    assert EnvVar.PREPROCESS_INVOCATION.value == "VAULTSPEC_PREPROCESS_INVOCATION"
    assert EnvVar.PREPROCESS_INVOCATION.value == PREPROCESS_INVOCATION_ENV
