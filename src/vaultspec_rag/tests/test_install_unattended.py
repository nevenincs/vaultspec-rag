"""Whether an install may ask a question, and what it does when it may not.

Deciding this from standard input alone got two cases wrong. A run emitting
a machine envelope went on prompting, because its terminal was still a
terminal even though nothing would read the question printed over the JSON.
A continuous-integration job that inherited a terminal prompted into a log
and then waited. Both are the same mistake - asking who is watching by
looking at one stream - and the framework answers it in one place now.

The streams here are real objects with a real ``isatty`` of ``False``; no
terminal is faked, and none is needed, because every case below is one where
nobody is watching. What the attended case does is not asserted from a
counterfeit terminal: it is the absence of every unattended signal, and each
of those is pinned on its own.
"""

from __future__ import annotations

import io

import pytest
from vaultspec_core.config import (
    CI,
    VAULTSPEC_NON_INTERACTIVE,
    ConfigurationError,
)

from ..cli._install import _confirmation_hook

pytestmark = [pytest.mark.unit]


def _asked(prompt: str) -> bool:
    """A confirmation callback that must never be reached unattended."""
    raise AssertionError(f"an unattended run asked: {prompt}")


def _hook(
    environ: dict[str, str] | None = None, *, json_output: bool = False
) -> object:
    """Resolve the hook against explicit streams nobody is reading."""
    return _confirmation_hook(
        _asked,
        json_output=json_output,
        environ=environ or {},
        stdin=io.StringIO(),
        stdout=io.StringIO(),
    )


def test_a_machine_envelope_never_prompts() -> None:
    """The question would be printed over the document meant to be parsed."""
    assert _hook(json_output=True) is None


def test_streams_nobody_is_reading_never_prompt() -> None:
    """Neither stream is a terminal, so no answer could arrive."""
    assert _hook() is None


def test_a_declared_unattended_session_never_prompts() -> None:
    assert _hook({VAULTSPEC_NON_INTERACTIVE.env_name: "1"}) is None


def test_continuous_integration_never_prompts() -> None:
    """The near-universal convention, defined by its owners as presence."""
    assert _hook({CI.env_name: ""}) is None


def test_the_product_marker_outranks_the_continuous_integration_one() -> None:
    """A wrapper run under CI with somebody watching can say so.

    Saying so does not conjure an operator, though: the streams still decide,
    which is why this run is still unattended. What the marker settles is
    that CI alone no longer does.
    """
    from vaultspec_core.config import unattended_declared

    assert (
        unattended_declared({CI.env_name: "1", VAULTSPEC_NON_INTERACTIVE.env_name: "0"})
        is False
    )


def test_a_mistyped_marker_is_refused_rather_than_guessed() -> None:
    """Guessing turns a typo into a silently skipped configuration step."""
    with pytest.raises(ConfigurationError, match=VAULTSPEC_NON_INTERACTIVE.env_name):
        _hook({VAULTSPEC_NON_INTERACTIVE.env_name: "nope-ish"})
