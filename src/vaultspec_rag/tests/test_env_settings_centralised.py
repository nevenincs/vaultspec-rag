"""Guards that the settings enum stays the one authoritative env-var list.

Two things can silently break that claim: a module reading a
``VAULTSPEC_RAG_*`` name the enum does not know about, and a module restating
a name the enum already owns and then drifting from it. One test per failure
mode.
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


def test_memory_probe_env_name_matches_the_settings_enum() -> None:
    """The one deliberate restatement must equal the enum member it copies."""
    assert EnvVar.MEMORY_PROBE.value == MEMORY_PROBE_ENV_VAR


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
