"""Guards that one boolean spelling means one thing across every reader.

Four readers of boolean environment values shipped four different vocabularies
at once. The worst pairing: ``off`` disabled the stdio watchdog while
*enabling* the memory probe, because the probe activated on any non-empty
value that was not ``0``. An operator who spelled a switch off the way a shell
spells off turned one feature on. Nothing failed; the probe simply ran.

That defect is invisible to a per-reader test, because each reader was
self-consistent. Only a test that puts one spelling through all of them at
once can see it, which is what :class:`TestEveryReaderAgrees` does.

What each reader is still free to decide for itself is the *out-of-band*
policy - what an empty value and an unrecognised word resolve to. Those
divergences are deliberate and are each pinned by a named test below, so a
later reader cannot quietly widen one into a second vocabulary again.

Every guard here was proved able to fail: each was broken one at a time, run
alone, observed to fail on the assertion it names, restored, and observed to
pass. The mutations are recorded on the tests they belong to.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest

from .._env_values import FALSE_TOKENS, TRUE_TOKENS
from ..config._settings import get_config, reset_config
from ..config._types import EnvVar, hf_cache_only
from ..memory_probe import is_enabled
from ..server._stdio_lifetime import watchdog_disabled
from ._import_probe import assert_fresh_import_excludes
from ._scaffold import restore_env, set_env

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]

#: Every spelling with a defined meaning, paired with the state it names. The
#: empty string is excluded on purpose: it is the one input the readers are
#: allowed to disagree about, and its cases are pinned separately below.
_SPELLINGS: tuple[tuple[str, bool], ...] = tuple(
    sorted(
        [(token, True) for token in TRUE_TOKENS]
        + [(token, False) for token in FALSE_TOKENS if token]
    )
)

#: A word in neither table. Deliberately a near-miss of a real spelling, which
#: is the shape an operator actually produces.
_TYPO = "treu"


@pytest.fixture
def clean_env() -> Iterator[None]:
    """Unset every variable these tests drive, and put it all back after."""
    driven = (
        EnvVar.HTML_STRIP,
        EnvVar.MEMORY_PROBE,
        EnvVar.STDIO_WATCHDOG,
        EnvVar.HF_HUB_OFFLINE,
        EnvVar.TRANSFORMERS_OFFLINE,
    )
    saved = {var: os.environ.pop(var.value, None) for var in driven}
    reset_config()
    try:
        yield
    finally:
        for var, previous in saved.items():
            restore_env(var, previous)
        reset_config()


def _generic_setting_reads(spelling: str) -> bool:
    """Resolve a plain boolean setting through the generic coercion chain."""
    previous = set_env(EnvVar.HTML_STRIP, spelling)
    try:
        reset_config()
        return bool(get_config().html_strip)
    finally:
        restore_env(EnvVar.HTML_STRIP, previous)
        reset_config()


def _memory_probe_reads(spelling: str) -> bool:
    previous = set_env(EnvVar.MEMORY_PROBE, spelling)
    try:
        return is_enabled()
    finally:
        restore_env(EnvVar.MEMORY_PROBE, previous)


def _stdio_watchdog_reads(spelling: str) -> bool:
    """Report the watchdog's state as *enabled*, matching the other readers."""
    previous = set_env(EnvVar.STDIO_WATCHDOG, spelling)
    try:
        return not watchdog_disabled()
    finally:
        restore_env(EnvVar.STDIO_WATCHDOG, previous)


def _hf_offline_reads(spelling: str) -> bool:
    previous = set_env(EnvVar.HF_HUB_OFFLINE, spelling)
    try:
        return hf_cache_only()
    finally:
        restore_env(EnvVar.HF_HUB_OFFLINE, previous)


#: ``reader name -> callable`` for every boolean environment reader shipped.
#: A new reader belongs here; that is the point of the table.
_READERS = {
    "generic setting": _generic_setting_reads,
    "memory probe": _memory_probe_reads,
    "stdio watchdog": _stdio_watchdog_reads,
    "hugging face offline": _hf_offline_reads,
}


@pytest.mark.usefixtures("clean_env")
class TestEveryReaderAgrees:
    """One spelling, one meaning, whichever switch it is set on."""

    @pytest.mark.parametrize(("spelling", "expected"), _SPELLINGS)
    def test_every_reader_resolves_the_spelling_the_same_way(
        self,
        spelling: str,
        expected: bool,
    ) -> None:
        """No reader may disagree with the others about a defined spelling.

        Mutation: restored the memory probe's original rule (any non-empty
        value other than ``0`` enables it). Observed this assertion fail on
        the ``off``, ``false`` and ``no`` cases, naming the memory probe as
        reading them as on while the other three read them as off.
        """
        disagreed = {
            name: reader(spelling)
            for name, reader in _READERS.items()
            if reader(spelling) is not expected
        }
        assert not disagreed, (
            f"{spelling!r} names {expected} everywhere else, but these readers "
            f"resolve it otherwise, so one spelling means two things: "
            f"{disagreed}"
        )

    def test_off_never_enables_anything(self) -> None:
        """The exact pairing that shipped, pinned on its own.

        Mutation: as above. Observed this assertion fail naming the memory
        probe as enabled by ``off``.
        """
        enabled_by_off = {name for name, reader in _READERS.items() if reader("off")}
        assert not enabled_by_off, (
            "these readers treat 'off' as on, which is the defect that shipped: "
            f"{sorted(enabled_by_off)}"
        )


@pytest.mark.usefixtures("clean_env")
class TestOutOfBandPolicyPerReader:
    """The deliberate divergences, each pinned to the reason it exists."""

    def test_generic_setting_rejects_an_unrecognised_word(self) -> None:
        """A settings knob refuses a typo rather than guessing at it.

        Mutation: made the coercion fall back to the shipped default on an
        unparsable value. Observed this assertion fail because no error was
        raised.
        """
        previous = set_env(EnvVar.HTML_STRIP, _TYPO)
        try:
            reset_config()
            with pytest.raises(ValueError, match=EnvVar.HTML_STRIP.value) as caught:
                _ = get_config().html_strip
        finally:
            restore_env(EnvVar.HTML_STRIP, previous)
            reset_config()
        # The message must carry the accepted spellings, not merely the name:
        # a rejection an operator cannot act on sends them to the source.
        assert "on" in str(caught.value)

    def test_memory_probe_rejects_an_unrecognised_word(self) -> None:
        """The probe follows the settings policy in full, rejection included.

        Mutation: made ``is_enabled`` return ``False`` for an unparsed value
        instead of raising. Observed this assertion fail because no error was
        raised.
        """
        previous = set_env(EnvVar.MEMORY_PROBE, _TYPO)
        try:
            with pytest.raises(ValueError, match=EnvVar.MEMORY_PROBE.value) as caught:
                is_enabled()
        finally:
            restore_env(EnvVar.MEMORY_PROBE, previous)
        assert _TYPO in str(caught.value)

    def test_memory_probe_reads_an_empty_value_as_off(self) -> None:
        """``VAR=`` leaves the diagnostic off, the safe direction for a probe.

        Mutation: made an empty value enable the probe, the direction the
        watchdog resolves it in. Observed this assertion fail.
        """
        previous = set_env(EnvVar.MEMORY_PROBE, "")
        try:
            assert is_enabled() is False
        finally:
            restore_env(EnvVar.MEMORY_PROBE, previous)

    def test_watchdog_stays_armed_on_an_unrecognised_word(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A misspelt escape hatch must not disarm the backstop.

        Disarming leaves stdin EOF as the shim's only exit path, which is the
        exact condition the watchdog exists to survive, so this reader fails
        safe where a settings knob rejects.

        Two mutations, one per assertion. Made ``watchdog_disabled`` treat an
        unparsed value as disabling: observed the armed check fail. Deleted the
        warning call while leaving the fail-safe intact: observed the log check
        fail, which is what keeps the silent-but-correct shape from passing.
        """
        previous = set_env(EnvVar.STDIO_WATCHDOG, _TYPO)
        try:
            with caplog.at_level(logging.WARNING, logger="vaultspec_rag.server"):
                assert watchdog_disabled() is False
        finally:
            restore_env(EnvVar.STDIO_WATCHDOG, previous)
        # Failing safe silently would hide the typo forever; the warning is
        # the only signal the operator's intent was not applied.
        assert any(_TYPO in record.getMessage() for record in caplog.records), (
            "an unrecognised watchdog value must be logged, or an operator who "
            "meant to disable the backstop never learns they did not"
        )

    def test_watchdog_stays_armed_on_an_empty_value(self) -> None:
        """An unexpanded ``VAR="$UNSET"`` must not strand shim processes.

        Every other boolean reads empty as off. This one does not, and that
        divergence is the point: losing the backstop by accident is the
        failure it was written to prevent.

        Mutation: dropped the empty-value branch so the shared table's
        ``""``-is-false entry applied. Observed this assertion fail.
        """
        previous = set_env(EnvVar.STDIO_WATCHDOG, "")
        try:
            assert watchdog_disabled() is False
        finally:
            restore_env(EnvVar.STDIO_WATCHDOG, previous)

    def test_hugging_face_offline_defers_an_unrecognised_word(self) -> None:
        """A third-party variable is not this project's to reject.

        The Hub and Transformers own these names and parse them themselves;
        refusing a value the owning library accepts would break an install
        whose configuration this project has no authority over.

        Mutation: made ``hf_cache_only`` raise on an unparsed value. Observed
        this assertion fail with that error instead of returning ``False``.
        """
        previous = set_env(EnvVar.HF_HUB_OFFLINE, _TYPO)
        try:
            assert hf_cache_only() is False
        finally:
            restore_env(EnvVar.HF_HUB_OFFLINE, previous)


def test_memory_probe_import_stays_free_of_the_settings_package() -> None:
    """Reading the shared table must not cost a spawn worker its import chain.

    The probe is reachable from spawn workers, which re-import everything.
    Importing the settings module for the boolean vocabulary would pull the
    vaultspec-core config package into every one of them, which is why the
    table lives in a stdlib-only module and the variable's name is restated
    rather than imported.

    Mutation: added ``from .config._types import EnvVar`` at module scope in
    ``memory_probe``. Observed this guard fail with ``vaultspec_core`` and its
    submodules named in the child's assertion payload.
    """
    assert_fresh_import_excludes("""
import sys

import vaultspec_rag.memory_probe  # noqa: F401

loaded = sorted(
    m for m in sys.modules
    if m in {"torch", "vaultspec_core"}
    or m.startswith(("torch.", "vaultspec_core."))
)
assert not loaded, loaded
""")
