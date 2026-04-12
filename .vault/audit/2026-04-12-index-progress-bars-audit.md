---
tags:
  - '#audit'
  - '#index-progress-bars'
date: 2026-04-12
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
  - '[[2026-04-12-index-progress-bars-adr]]'
  - '[[2026-04-12-index-progress-bars-reference]]'
---

# index-progress-bars code review

## Summary

- Findings: **0 CRITICAL**, **0 HIGH**, **0 MEDIUM**, **2 LOW**
- Verdict: **SHIP**

| Check                                    | Result | Notes                                                                                                                                                                                                                         |
| :--------------------------------------- | :----- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1 Required reporter kwarg               | PASS   | All 4 indexer entry points declare `*, reporter: ProgressReporter` with no default. `api.py` sanctioned optional.                                                                                                             |
| C2 Rich isolation                        | PASS   | `grep rich src/vaultspec_rag/indexer.py src/vaultspec_rag/embeddings.py` empty.                                                                                                                                               |
| C3 Sliced embed correctness              | PASS   | Slice step `range(0, len(texts), slice_size)`, extend in-order, `zip(..., strict=True)` pairing preserved across both indexers.                                                                                               |
| C4 Zero-work phases                      | PASS   | Empty-doc and empty-chunk branches still emit `phase_start(total=0)` + `phase_end` pairs for remaining phases.                                                                                                                |
| C5 Thread safety                         | PASS   | Parse-phase workers return via `future.result()` on the main thread; `reporter.advance` is not called from workers. Line-fallback counter guarded by `threading.Lock`.                                                        |
| C6 Test hygiene                          | PASS   | No unittest/mock/patch/skip/monkeypatch. `CountingProgressReporter` is a real class. Hammer test joins all futures before reading the counter.                                                                                |
| C7 Call site reporter choice             | PASS   | cli.handle_index → Rich; cli.handle_quality, mcp_server, watcher → Null; api → Optional+Null fallback; service.py unaffected (no direct indexer calls).                                                                       |
| C8 Lint / type                           | PASS   | `ruff check` and `ruff format --check` both clean. No new `noqa`/`type: ignore`/`pragma` introduced.                                                                                                                          |
| C9 Dead code / unused imports            | PASS   | Old `from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn` removed from cli.py; only `Console`, `Panel`, `Table` remain.                                                                                  |
| C10 ProgressReporter Protocol shape      | PASS   | `@runtime_checkable` Protocol with `phase_start(name, total)`, `advance(n=1)`, `phase_end()`, `log(message)`. Both Null and Rich implementations satisfy it (asserted by `isinstance(... , ProgressReporter)` in unit tests). |
| C11 RichProgressReporter context manager | PASS   | `__enter__` starts Progress only in TTY; `__exit__` stops and drops the reference.                                                                                                                                            |
| C12 Deviation check                      | PASS   | `NullProgressReporter` uses `del` to silence ARG; `api.py` optional matches ADR; watcher lambda creates a fresh `NullProgressReporter()` per call — no closure capture over mutable state.                                    |

## Findings

### CTX-001 | LOW | phase_start silently (re-)starts rich.Progress outside `with`

`src/vaultspec_rag/progress.py:126-136` — if `phase_start` is called in
TTY mode without having entered the context manager (or after `__exit__`),
it lazily calls `Progress.__enter__()` and never pairs it with an exit.
In the current codebase every call site wraps usage in `with RichProgressReporter(console) as reporter:`, so the path is unreachable
today, but the defensive branch could leak a live Rich thread if a
future caller forgets the `with` block.

Suggested fix: raise `RuntimeError("RichProgressReporter used outside context manager")`
instead of auto-starting, or remove the defensive branch entirely.

### DEVIATION-001 | LOW | slice size sourced from `embedding_batch_size`, not the plan's `progress_batch_size`

`src/vaultspec_rag/indexer.py:836`, `:958`, `:1515`, `:1643` — the plan
document (Phase 2) called for a dedicated `progress_batch_size` config
key defaulting to the existing dense batch size. The implementation
uses `get_config().embedding_batch_size` directly with a `max(1, ...)`
floor. This matches the plan's stated fallback and is strictly simpler,
but means there is no independent knob for tuning progress granularity
without also changing the GPU batch size. Acceptable as-is given the
ADR's stated "no new CLI flags, minimal surface" constraint; flagged for
visibility only.

Suggested fix: none required. Optionally add a `progress_batch_size`
override key later if UX tuning demands it.

## Notes (informational, not findings)

- `handle_index` no longer emits per-phase summary `console.log` lines
  (`Vault: N added...`) because those were removed with the old coarse
  task UI. The final summary table at the bottom of the function still
  prints. UX regression is minimal since the reporter now shows per-doc
  progress inline, but if the old one-line summary is still desired it
  would need to be re-added.
- In TTY mode the Rich adapter adds a new task row for every
  `phase_start` and never removes completed rows, matching the ADR's
  "stacked task rows" vision. Long runs with many phases will therefore
  show a tall stack of completed bars — intentional per the ADR.
- `test_progress_unit.py::test_threaded_advance_counter` reaches into
  `reporter._lock` / `_phase_count`. Accessing protected state is
  unusual but the test is exercising real concurrent behaviour (1000
  worker submissions, joined before the assertion), not a tautology.
