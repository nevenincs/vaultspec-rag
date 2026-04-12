---
tags:
  - '#audit'
  - '#vault-index-perf-memory'
date: 2026-04-12
related:
  - '[[2026-03-06-indexer-pipeline-audit]]'
---

# vault-index-perf-memory rolling audit

Rolling audit tracking every finding from automated code reviewers
(gemini-code-assist, codex-connector) and Claude self-review passes
on PR #70 (Track B: fix 24 GB RSS leak in vault indexer).

Review cadence: after each fix batch, re-read the changed surfaces,
re-run the audit domains from previous iterations, and append any
new findings. Continuous loop until a full audit pass returns zero
new items.

## Audit domains

Every pass MUST cover these domains end-to-end:

1. **Resource lifecycle** — background threads, contexts, file
   handles, GPU memory, caching allocator state, subprocess handles.
1. **Exception safety** — try/finally on mutable global state,
   progress reporters, locks, temporary collections, probe teardown.
1. **Failure-path data safety** — any operation that destroys state
   before new state is ready (drop-then-rebuild).
1. **Concurrency hazards** — lock scope, GPU lock contention, race
   conditions on shared state, thread-safe caching.
1. **Probe / instrumentation correctness** — sampler cadence, peak
   tracking accuracy, env-var interpretation, disabled-state no-op.
1. **Test hermeticity** — env mutation, monkeypatch usage, parallel
   test safety, fixture isolation.
1. **Dependency hygiene** — version pins, import-time cost,
   lazy-import correctness.
1. **Performance of hot paths** — per-sample import cost, repeated
   work inside loops.
1. **Correctness of the RSS fix itself** — slicing boundaries,
   cache flush timing, ordering of del + empty_cache.
1. **Regression test coverage** — thresholds, fixture overlap with
   session-scoped state, flake resilience.

## Iteration log

### Iteration 0 — baseline (initial PR submission, commit 755177c)

Findings documented retrospectively once reviewers posted. All were
incorporated into Iteration 1.

### Iteration 1 — commit d73b7a3 (2026-04-12)

**Addressed:**

- [F1.1] HIGH — MemoryProbe lacked `__enter__`/`__exit__`
  (gemini-R1, claude-safety Finding 1, claude-pr-review medium,
  gemini-R2 high). Added context manager protocol.
- [F1.2] MEDIUM — `gpu_lock` held across I/O-bound upsert
  (gemini-R1, claude-safety Finding 3, claude-pr-review medium).
  Narrowed to encode-only scope in both streaming helpers.

**Not yet addressed — carried forward to Iteration 2:**

- [F2.1] P1 CRITICAL — `VaultIndexer.full_index` destroys the
  collection (drop_table or delete_all) before the new slices have
  been encoded; mid-run failure leaves the vault empty.
  Source: codex-connector. Location: `indexer.py:983` (after
  rebase).
- [F2.2] P1 CRITICAL — `CodebaseIndexer.full_index` has the same
  flaw at `indexer.py:1626`. Source: codex-connector.
- [F2.3] MEDIUM — `reporter.phase_end()` is skipped when the
  streaming loop raises; progress bar / UI state corrupts.
  Source: claude-safety Finding 2. Location: both streaming
  helpers.
- [F2.4] MEDIUM — `current_rss_mb` re-imports `psutil` and
  instantiates `Process` every 250 ms. Source: gemini-R2. Cache
  the `psutil.Process` handle.
- [F2.5] MEDIUM — `current_cuda_mb` re-imports torch and re-checks
  `torch.cuda.is_available()` on every sample. Source: gemini-R2.
  Cache the torch module and availability flag.
- [F2.6] LOW — `MemoryProbe.stop` does not check
  `self._sampler_thread.is_alive()` after the 1 s join timeout.
  Silent cleanup failure. Source: claude-safety Finding 4.
- [F2.7] LOW — `test_vault_full_index_peak_rss_bounded` mutates
  `os.environ` instead of using `monkeypatch.setenv`. Breaks
  parallel runs. Source: claude-safety Finding 5, claude-pr-review
  low.
- [F2.8] LOW — `psutil>=7.2.2` pin is tighter than the code
  actually needs. psutil 6.x exposes the same `memory_info().rss`
  API. Source: claude-pr-review low.
- [F2.9] LOW — `MemoryProbe.checkpoint` re-evaluates `is_enabled()`
  every call. A probe can silently stop recording mid-run if the
  env var is cleared. Source: claude-pr-review low. Cache
  `self._enabled` in `__post_init__`.
- [F2.10] LOW — `tools/profile_vault_index.py` writes
  `date: 2026-04-12` hard-coded. Source: claude-pr-review low.
  Use `datetime.date.today().isoformat()`.
- [F2.11] MEDIUM — `test_vault_full_index_peak_rss_bounded` holds
  `probe` in a local variable and calls `stop()` outside a
  `finally` block. If the assertion or teardown raises, the probe
  thread leaks. Source: claude-pr-review medium cross.
- [F2.12] MEDIUM — `tools/profile_vault_index.py` calls `probe.stop()`
  inside the outer `try`, not its `finally`. Same leak path as
  F2.11. Source: claude-pr-review medium cross.

### Iteration 2 — commit pending (2026-04-12)

**All 12 findings F2.1 – F2.12 addressed.**

- **F2.1, F2.2 (P1 CRITICAL — data-loss window)**: Both
  `VaultIndexer.full_index` and `CodebaseIndexer.full_index` now
  `ensure_table()`, snapshot existing IDs, stream-upsert (idempotent
  by doc/chunk id so old rows are overwritten in place), and only
  purge `existing_ids - new_ids` **after** the streaming encode
  finishes. If any slice raises (CUDA OOM, Qdrant write failure),
  the old collection is preserved intact — the documented
  `clean=True` contract ("no stale documents persist") is still
  honoured via the final purge. `CodebaseIndexer.full_index` kept
  `clean` in its signature for API symmetry with a noqa and an
  updated docstring noting the behavioural change.
- **F2.3**: `reporter.phase_end()` now runs inside a `try/finally`
  in both streaming helpers — progress state stays balanced even
  when the slice loop raises.
- **F2.4**: `current_rss_mb` caches the `psutil.Process` handle in
  a module-level singleton (`_psutil_process`). First call imports
  psutil; subsequent calls are a single attribute lookup.
- **F2.5**: `current_cuda_mb` caches the torch module reference and
  the CUDA availability flag (`_torch_module`, `_torch_probed`,
  `_torch_has_cuda`). `_torch_probed` guards the one-shot import so
  failure is cached too (no retry storm).
- **F2.6**: `MemoryProbe.stop` now logs a warning if
  `self._sampler_thread.is_alive()` after the 1 s join — silent
  cleanup failures are no longer invisible.
- **F2.7**: `test_vault_full_index_peak_rss_bounded` now accepts
  the `monkeypatch` fixture and calls `monkeypatch.setenv` — safe
  under pytest-xdist and parametrized runs.
- **F2.8**: `psutil>=7.2.2` → `psutil>=6.0.0` in `pyproject.toml`
  plus `uv lock` refresh. No code change required because
  `Process().memory_info().rss` has been stable since psutil 5.x.
- **F2.9**: `MemoryProbe.__post_init__` snapshots `self._enabled = is_enabled()` once; `checkpoint()` checks `self._enabled` instead
  of re-reading the environment. The probe's enabled state is now
  deterministic for its entire lifecycle.
- **F2.10**: `tools/profile_vault_index.py` uses
  `datetime.date.today().isoformat()` for both the filename prefix
  and the frontmatter `date:` field.
- **F2.11**: `test_vault_full_index_peak_rss_bounded` uses
  `with MemoryProbe(...) as probe:` — sampler thread is torn down
  even when an assertion raises.
- **F2.12**: `tools/profile_vault_index.py` similarly uses the
  probe as a context manager; `store.close()` moved into an inner
  `try/finally` so a mid-index failure still closes the Qdrant
  lock before the temp dir is purged.

**Additional required changes caught while fixing the above:**

- **Phase schema**: progress tests
  (`test_indexer_progress_integration.py`) updated to expect the
  new `"purge stale documents"` / `"purge stale chunks"` phases
  between `"embed + upsert …"` and `"write metadata"`. The empty-
  docs early-return branches in both indexers emit the purge phase
  as a zero-length no-op so the event sequence stays consistent
  regardless of corpus size.
- **`docs[n].id` vs `docs[n].doc_id`**: `VaultDocument` and
  `CodeChunk` both expose `.id` (verified in `store.py`). Initial
  patch used `.doc_id` which would have broken immediately; caught
  before commit.

**Test results after this batch (commit pending):**

- Unit suite: `313 passed, 222 deselected`
- Integration suite (indexer + progress + performance + codebase):
  `30 passed`
- Ruff, ruff-format, ty — all clean.

### Iteration 3 — re-audit of Iteration 2 surfaces (2026-04-12)

Re-walked every audit domain against the post-Iteration-2 state
of `memory_probe.py`, `indexer.py`, `test_performance.py`,
`tools/profile_vault_index.py`, and the integration test
surfaces.

**New findings — fixed in this iteration:**

- **F3.10 P1 CRITICAL — regression of `clean=True` contract.**
  `VaultIndexer.full_index` still had an early-return branch for
  `if not docs:` that skipped the new `"purge stale documents"`
  step entirely. If a user deletes every `.md` file and then runs
  `full_index(clean=True)` the previously-indexed rows survive —
  directly contradicting the documented "no stale documents
  persist" guarantee. **Fix**: removed the empty-docs short
  circuit; the streaming helper already handles a zero-length
  list, and letting the main path run means the purge step wipes
  all previously-indexed rows when the new corpus is empty.
- **F3.11 P1 CRITICAL — same for CodebaseIndexer.** Same empty
  branch, same fix.
- **F3.4 LOW — `_torch_probed` set before probe completes.**
  `current_cuda_mb` set `_torch_probed = True` at the top of its
  init block, meaning a non-ImportError failure from
  `torch.cuda.is_available()` (driver hiccup) would be cached
  forever as "no CUDA". **Fix**: set `_torch_probed` only after
  the full init succeeds; negative ImportError is still cached
  because a missing package is a permanent condition, but a
  transient CUDA failure is no longer sticky.

**New findings — accepted / documented (no fix):**

- **F3.1 LOW — `_psutil_process` not fork-safe.** If the host
  process forks after the first probe sample, the child will
  still reference the parent PID. Not an issue for the current
  use cases (indexer runs in the main process, no forking) but
  worth tracking. Accepted; revisit if we ever spawn worker
  subprocesses.
- **F3.2 LOW — single-use probe.** Reusing a probe instance
  across multiple `with` blocks will not restart the sampler.
  Accepted; single-use is the documented contract.
- **F3.3 LOW — `samples` list not lock-protected.** Only the
  main thread mutates `samples`; the background sampler touches
  only `peak_rss_mb` (which is lock-protected). Accepted.
- **F3.9 MEDIUM — `clean=True` no longer resets collection
  schema.** The old drop-and-recreate path reset payload indexes
  and dimension. If the user changes embedding_dimension in
  config, the new upsert would fail with a Qdrant dimension
  mismatch. Accepted as a deliberate tradeoff for failure safety:
  schema reset must now be explicit (`store.drop_table()` or
  reinstall). Worth calling out in release notes.

**New test coverage:**

- `test_full_index_clean_on_empty_corpus_purges_all` builds a
  6-doc synthetic vault, indexes it, deletes every `.md` file,
  runs `full_index(clean=True)`, and asserts `store.count() == 0`.
  This test would fail against the old empty-docs early-return.

**Test results:**

- 30 integration tests + regression guard: passed.
- Ruff / format / ty: clean.

### Iteration 4 — re-audit queue

After Iteration 3 commits, re-walk the ten domains against the
updated surfaces:

- `memory_probe.py` (changed — `_torch_probed` ordering)
- `indexer.py` (changed — empty-branch removal in both indexers)
- `test_indexer_integration.py` (changed — new regression test)

and re-check the dependent tests for knock-on regressions:

- `test_indexer_progress_integration.py` — no change needed
  (already asserts `purge stale documents == 0` on a fresh
  collection; should still hold).
- `test_performance.py` — no change needed.
- `test_codebase_integration.py` — no change needed.
- `test_adr_regression.py` — cross-check whether any ADR test
  pinned `clean=True` destructive behaviour.

If Iteration 4 finds new items, open F4.x below and continue.
Loop terminates only when a full ten-domain pass returns zero
new items across all of these files.
