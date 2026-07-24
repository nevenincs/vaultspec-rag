"""Run-checkpoint logic shared by the code and document indexers.

The two indexers keep separate checkpoint classes on purpose: their commit
units differ, so the per-unit bookkeeping around them genuinely differs too.
What does not differ is the run-level reasoning that has nothing to do with
what a unit is - and that is what lives here.

The distinction worth holding is which duplications are dangerous. A duplicated
one-line property reads wrong once and is corrected in place. A duplicated
*decision* is different: it is the copy that never gets the fix. If someone
corrects how an interrupted run is classified in one indexer and not the other,
one source type silently mis-classifies interruptions on resume - no test
compares the two implementations against each other, so nothing announces the
divergence. That is why the classification is centralised here and the
one-liners were deliberately left where they are.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING

from ._run_ledger import RunTerminalState

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from ._run_ledger import RunGeneration, RunLedger

__all__ = [
    "classify_interrupted_generation",
    "configuration_fingerprint",
]


def configuration_fingerprint(configuration: DataclassInstance) -> str:
    """Fingerprint a run configuration into its run-signature identity.

    Sorted keys and separator-tight JSON make the digest depend on the
    configuration's values alone, never on field declaration order or on how
    the encoder happens to space its output - the fingerprint has to be stable
    across processes for a resumed run to recognise its own parent generation.
    """
    payload = json.dumps(asdict(configuration), sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(payload.encode("utf-8")).hexdigest()


def classify_interrupted_generation(
    ledger: RunLedger,
    generation: RunGeneration,
    exc: BaseException,
) -> RunGeneration:
    """Finish an interrupted generation under the terminal state it earned.

    A generation that is no longer ``RUNNING`` has already reached a terminal
    state and is returned untouched, so a failure raised after the run finished
    cannot overwrite the outcome it already recorded.

    The destructive/non-destructive split is the load-bearing part. An
    interrupted rebuild has already dropped data it did not finish replacing,
    so it is ``REBUILD_INCOMPLETE`` - a state a later run must not treat as a
    usable parent. An interrupted incremental run left the published data
    intact and is merely ``FAILED``.

    Returns the finished generation; the caller reassigns it and re-raises, so
    the original exception continues to propagate unchanged.
    """
    if generation.terminal_state is not RunTerminalState.RUNNING:
        return generation
    terminal_state = (
        RunTerminalState.REBUILD_INCOMPLETE
        if generation.destructive_intent
        else RunTerminalState.FAILED
    )
    detail = f"{type(exc).__name__}: {exc}".rstrip()
    return ledger.finish_generation(
        generation.generation_id,
        terminal_state,
        detail=detail,
    )
