"""Guards that the settings enum stays the one authoritative env-var list.

Three things can silently break that claim: a module reading a
``VAULTSPEC_RAG_*`` name the enum does not know about, a module restating a
name the enum already owns and then drifting from it, and the enum declaring a
first-party name nothing reads. One test per failure mode.

The third is the one that already happened. ``VAULTSPEC_RAG_SERVICE_DAEMON``
was written into the daemon's environment and declared here, and its comment
described a reader that told resident code apart from an interactive CLI. No
such reader existed: the distinction was made by an in-process flag the server
entry point sets, which is both unforgeable and able to tell a spawned daemon
from an embedded in-process host - something an inherited environment marker
cannot do. So the enum advertised a knob that configured nothing, and the
documentation restated its claim as fact.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from ..config import EnvVar
from ..memory_probe import ENV_VAR as MEMORY_PROBE_ENV_VAR

pytestmark = [pytest.mark.unit]

#: Names that are deliberately not settings. The preprocess invocation carries
#: a JSON payload to a hook subprocess - it is a transport channel, not a knob -
#: and the pytest singleton markers are test-harness internals.
_NOT_SETTINGS = frozenset(
    {
        "VAULTSPEC_PREPROCESS_INVOCATION",
        # Arguments handed to a PowerShell child through its environment so the
        # path and target never enter the command string, where they would be
        # subject to injection. A transport channel, not a knob.
        "VAULTSPEC_JUNCTION_PATH",
        "VAULTSPEC_JUNCTION_TARGET",
        "_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT",
        "_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE",
        "_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP",
    }
)

_SRC = Path(__file__).resolve().parent.parent
_ENV_LITERAL = re.compile(r"\"(_?VAULTSPEC(?:_RAG)?_[A-Z0-9_]+)\"")

#: Prefix marking a name this project defines, as opposed to one it merely
#: references because another library honours it. The two carry different
#: admission rules, which the enum's own docstring states.
_FIRST_PARTY_PREFIX = "VAULTSPEC_RAG_"

#: The single member exempt from needing an ``EnvVar.<NAME>`` reference in
#: production. The probe module is reachable from spawn workers and must not
#: import this module, so it restates the bare name - a restatement that is
#: itself pinned by ``test_memory_probe_env_name_matches_the_settings_enum``.
#: Nothing else may join this set without the same kind of pin.
_READ_WITHOUT_THE_ENUM = frozenset({"MEMORY_PROBE"})


def test_memory_probe_env_name_matches_the_settings_enum() -> None:
    """The one deliberate restatement must equal the enum member it copies."""
    assert EnvVar.MEMORY_PROBE.value == MEMORY_PROBE_ENV_VAR


def test_every_first_party_variable_is_read_somewhere_in_production() -> None:
    """A ``VAULTSPEC_RAG_*`` member nothing reads configures nothing.

    A first-party name earns its place by being read. One that is only ever
    written, or only ever declared, is a marker whose documentation describes
    behaviour the code does not have - which is exactly what
    ``VAULTSPEC_RAG_SERVICE_DAEMON`` shipped as. Third-party names are out of
    scope here: those are declared to keep a literal in one place, and the
    behaviour behind them belongs to the library that honours them.

    Mutation: re-added a ``SERVICE_DAEMON = "VAULTSPEC_RAG_SERVICE_DAEMON"``
    member to the enum without any reader. Observed this assertion fail naming
    that member.
    """
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in _SRC.rglob("*.py")
        if "tests" not in path.parts
    )
    unread = sorted(
        member.name
        for member in EnvVar
        if member.value.startswith(_FIRST_PARTY_PREFIX)
        and member.name not in _READ_WITHOUT_THE_ENUM
        and not re.search(rf"EnvVar\.{member.name}\b", production)
    )
    assert not unread, (
        "the settings enum declares these variables but no production module "
        "reads them, so each advertises a knob that configures nothing - "
        "either wire the reader its documentation describes, or delete the "
        f"declaration: {unread}"
    )


def test_no_module_reads_a_settings_env_var_the_enum_does_not_own() -> None:
    """Every ``VAULTSPEC_*`` literal in production code is a known setting."""
    known = {member.value for member in EnvVar} | _NOT_SETTINGS
    offenders: dict[str, set[str]] = {}
    for path in _SRC.rglob("*.py"):
        if "tests" in path.parts:
            continue
        found = {
            name
            for name in _ENV_LITERAL.findall(path.read_text(encoding="utf-8"))
            if name not in known
        }
        if found:
            offenders[str(path.relative_to(_SRC))] = found
    assert not offenders, (
        "these modules name a VAULTSPEC_* environment variable the settings "
        f"enum does not declare, so it is a setting with no canonical home: {offenders}"
    )
