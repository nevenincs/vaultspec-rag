---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
step_id: 'S06'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Inject the gate into VaultSearcher like gpu_lock at each construction site in the registry and wait on the gate at search admission before acquiring gpu_lock in the GPU section, never parking while holding gpu_lock and preserving the torch-free path, with a unit test of admission gating for gpu_lock None and an injected gate

## Scope

- `src/vaultspec_rag/search/_searcher.py`

## Description

- Add keyword-only `quiesce_gate: QuiesceGate | None = None` to `VaultSearcher.__init__`, stored as `self._quiesce_gate`, typed via a TYPE_CHECKING import so the search path gains no runtime import weight (`src/vaultspec_rag/search/_searcher.py:67,106,151`).
- Wait on the gate at the very top of `_gpu_section`, before the `gpu_lock is None` short-circuit and before `self._gpu_lock.acquire()`, so a paused entrant parks without holding the GPU lock and gateless-lock searchers are still gated (`src/vaultspec_rag/search/_searcher.py:170-172`).
- Pass `quiesce_gate=self._quiesce_gate` at the registry's `VaultSearcher` construction site beside the existing `gpu_lock=self._gpu_lock` (`src/vaultspec_rag/service.py:748`).
- Add `src/vaultspec_rag/tests/test_search_quiesce_admission.py` with three CPU-only tests: paused gate parks a `gpu_lock=None` searcher's GPU-section entry until resume (bounded join), a parked entrant leaves a real `gpu_lock` acquirable (wait-before-acquire ordering), and a gateless searcher admits immediately.

## Outcome

Search admission now honours the process-global quiesce gate: new entrants park at zero CPU before touching the GPU lock, requests already inside their GPU section drain unpreempted, and the wait never sits inside `gpu_lock`. Guards proven both directions in one uninterrupted sequence each: replacing the gate wait with a no-op turned the block test red on "search admission did not park at the paused gate"; moving the wait after `gpu_lock.acquire()` turned the ordering test red on "a parked entrant is holding the GPU lock"; restoring returned both green (3 passed). Green gate: `ruff check src tools` all checks passed, `ty check` on touched files all checks passed.

## Notes

The wait-after-acquire mutation run exposed that a red assertion left the parked non-daemon worker alive, hanging the pytest process at interpreter exit; both parking tests (and the jobs-side guard) now reopen the gate in a `finally` so a red run terminates instead of wedging the suite. Only the `VaultSearcher` construction site receives the gate; the three indexer constructions keep quiesce through their job tokens' checkpoints, not a constructor parameter.
