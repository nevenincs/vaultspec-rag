"""Guard tests: ``.env.example`` and the source declare the same variables.

``.env.example`` is the one place an operator can discover what a variable
does and what it ships as, and it is the layout every worktree's ``.env`` is
provisioned in. It drifts from the source in three ways, each silent on its
own: a variable the source reads never reaches it, a variable it declares
stops being read, and a default it shows stops being the default. These
guards close all three, in both directions, against the source itself rather
than against a list somebody maintains.

A declaration is an ASSIGNMENT line (``VAR=`` or ``# VAR=``), not a mention.
A prose mention carries no default, so it does not document the variable, and
a substring match would let ``VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES``
stand in for ``VAULTSPEC_RAG_PREPROCESS`` - the pair most likely to be
confused.

Each guard was broken once, run alone and seen to fail on its own assertion,
then restored and seen to pass, in one uninterrupted sequence with nothing
left mutated on disk. The mutation each one catches is recorded in its
docstring.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

import pytest
from vaultspec_core.config import VariableScope
from vaultspec_core.env_values import parse_bool

from ..config._registry import entry
from ..config._schema import ENV_OVERRIDE_MAP
from ..config._settings import VaultSpecConfigWrapper
from ..config._types import EnvVar
from ._env_surface import (
    ENV_EXAMPLE,
    borrowed_name_is_referenced,
    harness_name_is_read,
    product_setting_is_consumed,
    source_surface,
    template_assignments,
)

pytestmark = [pytest.mark.unit]

#: Names a parent process sets on its own child, which nobody sets by hand. A
#: line for one would advertise a knob and invite somebody to turn it, so
#: these are the only names the source may carry and the example may not.
_SET_BY_A_PARENT_PROCESS: Final[dict[str, str]] = {
    "_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT": "the test harness, on its session",
    "_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE": "the test harness, on its session",
    "_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP": "the test harness, on its session",
    "PYTEST_CURRENT_TEST": "pytest, on the process running a test",
    "PYTEST_XDIST_WORKER": "pytest-xdist, on each worker",
    "GITHUB_ACTIONS": "the Actions runner, on every step",
    "GITHUB_ENV": "the Actions runner, on every step",
    "RUNNER_TOOL_CACHE": "the Actions runner, on every step",
    "FULL_RUN_LABEL": "the merge-gate workflow, on its own steps",
}

#: Names the harness spells out and nothing reads. Declaring one would document
#: behaviour the code does not have, so each stays off the example until a
#: reader exists - at which point the guard below evicts it from this set.
_NAMED_WITHOUT_A_READER: Final = frozenset(
    {
        "VAULTSPEC_FIX_STRICT",
        "VAULTSPEC_ALLOW_EMPTY_SELECTION",
    }
)

#: Environment accesses whose key cannot be read off the source. Each was read
#: and found to pass on only names declared elsewhere: the first restores the
#: variables the session saved, the second tests whichever switch it is handed.
_REVIEWED_DYNAMIC_SITES: Final = frozenset(
    {
        "conftest.py::pytest_unconfigure",
        "dev/init/__main__.py::_truthy",
    }
)

_BANNER: Final = re.compile(r"^#\s*-{3,}\s*$")
_PROSE: Final = re.compile(r"^#.*[A-Za-z]{2}")


def _declared() -> set[str]:
    return {name for _, name, _ in template_assignments()}


def _internal() -> set[str]:
    return {var.value for var in EnvVar if entry(var).scope is VariableScope.INTERNAL}


def test_env_example_exists() -> None:
    assert ENV_EXAMPLE.is_file(), f"operator env template missing at {ENV_EXAMPLE}"


def test_env_example_documents_every_env_var() -> None:
    """Every variable an operator may set has a line of its own.

    Internal scope is exempt, and not as a convenience: a marker this project
    sets on its own child processes is not something an operator sets, so a
    template line for it would advertise a knob and invite somebody to turn
    it. The registry decides which is which, so a name cannot be kept off the
    template without also being declared unsettable.

    Mutation: deleted one variable's assignment line. Observed this assertion
    fail naming that variable.
    """
    declared = _declared()
    missing = sorted(
        var.value
        for var in EnvVar
        if var.value not in declared and entry(var).scope is not VariableScope.INTERNAL
    )
    assert not missing, (
        "the operator env template documents no default for "
        f"{len(missing)} recognised environment variable(s): "
        f"{', '.join(missing)}. Add a commented '# NAME=default' line with a "
        "prose comment stating what the variable does and what changing it "
        "costs, under the matching section of .env.example."
    )


def test_the_example_declares_every_variable_the_source_names() -> None:
    """Nothing outside the settings enum is read without being declared.

    The enum covers the product's Python. The harness, the release tooling
    and the monitor read variables too, and those reach no enum - so the
    source is scanned, and a name it carries is either declared or one a
    parent process sets on its own child.

    Mutation: added ``os.environ.get("VAULTSPEC_RAG_UNDECLARED")`` to a
    harness module. Observed this assertion fail naming that variable and the
    module.
    """
    exempt = set(_SET_BY_A_PARENT_PROCESS) | _NAMED_WITHOUT_A_READER | _internal()
    declared = _declared()
    undeclared = {
        name: sorted(files)
        for name, files in source_surface().names.items()
        if name not in declared and name not in exempt
    }
    assert not undeclared, (
        "the source names environment variables .env.example does not "
        f"declare: {undeclared}. Add a commented '# NAME=default' line under "
        "a description of what each does."
    )


def test_the_example_declares_nothing_the_source_does_not_read() -> None:
    """A declared variable has a reader, or it is a knob that does nothing.

    What counts as a reader depends on who owns the name. A variable this
    project defines must be acted on by shipped code - mapping it onto a
    settings key nobody reads is not that. A variable another project owns is
    declared to keep its literal in one place, so being referenced anywhere
    earns it. A harness variable must reach an environment access.

    Mutation: added ``# VAULTSPEC_RAG_NOTHING_READS_THIS=`` under a
    description. Observed this assertion fail naming that variable.
    """
    by_value = {var.value: var for var in EnvVar}
    unread: list[str] = []
    for name in sorted(_declared()):
        var = by_value.get(name)
        if var is None:
            used = harness_name_is_read(name)
        elif entry(var).scope is VariableScope.EXTERNAL:
            used = borrowed_name_is_referenced(var)
        else:
            used = product_setting_is_consumed(var)
        if not used:
            unread.append(name)
    assert not unread, (
        ".env.example declares variables nothing in the source reads, so each "
        "advertises a knob that configures nothing - delete the line, or wire "
        f"the reader its description promises: {unread}"
    )


def test_the_example_declares_no_name_a_parent_process_sets() -> None:
    """The names kept off the example stay off it, and stay real.

    Mutation: added ``# PYTEST_CURRENT_TEST=`` under a description. Observed
    the first assertion fail naming it.
    """
    kept_off = set(_SET_BY_A_PARENT_PROCESS) | _NAMED_WITHOUT_A_READER | _internal()
    advertised = sorted(_declared() & kept_off)
    assert not advertised, (
        f".env.example declares names nobody sets by hand: {advertised}"
    )

    named = source_surface().names
    stale = sorted(
        name
        for name in (*_SET_BY_A_PARENT_PROCESS, *_NAMED_WITHOUT_A_READER)
        if name not in named
    )
    assert not stale, (
        f"names exempted from .env.example that the source no longer carries: {stale}"
    )

    wired = sorted(
        name for name in _NAMED_WITHOUT_A_READER if harness_name_is_read(name)
    )
    assert not wired, (
        "these names now have a reader, so they are settings like any other - "
        f"declare them in .env.example and drop the exemption: {wired}"
    )


def test_every_dynamic_environment_access_is_reviewed() -> None:
    """An access the scan cannot read is one a person has.

    A key that only exists at run time can name any variable, declared or
    not. Holding the set of such sites exact means a new one fails here until
    somebody reads it, and a removed one does not leave a standing waiver.

    Mutation: added ``os.environ.get(name)`` to a function taking ``name`` as
    a parameter. Observed this assertion fail naming that function.
    """
    assert source_surface().dynamic_sites == _REVIEWED_DYNAMIC_SITES


def test_the_example_declares_each_variable_once() -> None:
    """A second line for one name is two defaults for one variable.

    Mutation: duplicated one assignment line. Observed this assertion fail
    naming that variable.
    """
    counts = Counter(name for _, name, _ in template_assignments())
    repeated = sorted(name for name, count in counts.items() if count > 1)
    assert not repeated, f".env.example declares these more than once: {repeated}"


def test_every_declaration_sits_under_a_description_of_its_own() -> None:
    """The line above an assignment is prose about that assignment.

    Two assignments stacked under one comment share a description, and the
    second is then documented by whatever the reader infers.

    Mutation: deleted the comment block above one assignment, leaving it
    directly under the previous one. Observed this assertion fail naming it.
    """
    lines = ENV_EXAMPLE.read_text(encoding="utf-8").splitlines()
    assigned = {number for number, _, _ in template_assignments()}
    undescribed = [
        name
        for number, name, _ in template_assignments()
        if (number - 1) in assigned
        or _BANNER.match(lines[number - 2])
        or not _PROSE.match(lines[number - 2])
    ]
    assert not undescribed, (
        ".env.example declares these without a description directly above "
        f"them: {undescribed}"
    )


def _shows(shown: str, default: object) -> bool:
    """Return whether a template value is the shipped *default*."""
    if default is None:
        return shown == ""
    if isinstance(default, bool):
        return parse_bool(shown) is default
    if isinstance(default, (int, float)):
        try:
            return float(shown) == float(default)
        except ValueError:
            return False
    return shown == str(default)


def test_the_example_shows_the_default_each_setting_ships_with() -> None:
    """A commented value is a claim about what unsetting the variable gives.

    The claim is checked against the defaults table the settings resolve
    from, per type: a boolean by the shared vocabulary, a number by value, an
    absent default as an empty assignment.

    Mutation: changed one shown default to a different number. Observed this
    assertion fail naming that variable with both values.
    """
    shown = {name: value for _, name, value in template_assignments()}
    defaults = VaultSpecConfigWrapper._RAG_DEFAULTS
    wrong = {
        var.value: f"shows {shown[var.value]!r}, ships {defaults[key]!r}"
        for key, var in ENV_OVERRIDE_MAP.items()
        if var.value in shown and not _shows(shown[var.value], defaults[key])
    }
    assert not wrong, f".env.example shows defaults the settings do not ship: {wrong}"
