"""Provisioning outcome lookups for tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..commands._provision import (
        ProvisionOutcome,
        ProvisionStep,
        ProvisionStepResult,
    )


def result_for(
    outcome: ProvisionOutcome, step: ProvisionStep
) -> ProvisionStepResult | None:
    """Return the result recorded for *step*, or ``None`` if not considered."""
    for result in outcome.steps:
        if result.step == step:
            return result
    return None
