"""The import guards' own guard.

Five tests across this suite assert that some module loads no torch, and all
five now run through one shared probe. That concentration is worth a positive
control: if the probe ever stopped detecting anything - a mistyped forbidden
name, a scan that matched nothing, a runner that swallowed the child's exit
status - every one of those five would keep reporting green while defending
nothing. These tests fail when the probe stops working, so the others can be
trusted when they pass.
"""

from __future__ import annotations

import pytest

from ._import_probe import assert_fresh_import_excludes, import_probe_source

pytestmark = [pytest.mark.unit]


def test_the_probe_rejects_an_import_that_really_loads_the_forbidden_module() -> None:
    """Importing torch itself must be caught, or the guards prove nothing."""
    with pytest.raises(AssertionError):
        assert_fresh_import_excludes(import_probe_source("torch"))


def test_the_probe_catches_a_submodule_of_a_forbidden_package() -> None:
    """A chain that loads only ``torch.nn`` is still a chain that loaded torch.

    An exact-name-only scan would report clean here, which is the specific way
    this check is easiest to get subtly wrong.
    """
    with pytest.raises(AssertionError):
        assert_fresh_import_excludes(import_probe_source("torch.nn"))


def test_the_probe_passes_for_a_module_that_stays_clean() -> None:
    """The negative direction: a genuinely torch-free import must not fail.

    Without this, a probe that failed unconditionally would satisfy both cases
    above and still be useless.
    """
    assert_fresh_import_excludes(import_probe_source("vaultspec_rag.store_schema"))
