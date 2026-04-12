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

### Iteration 4 — deeper sweep of the Iteration 2/3 surfaces (2026-04-12)

**New findings — fixed in this iteration:**

- **F4.1 LOW — stale docstring in `VaultIndexer.full_index`.** The
  docstring still said `clean: If True, drop and recreate the collection` and its `Raises:` section still described the old
  non-clean delete path. **Fix**: rewrote both the `Args:clean`
  entry and the `Raises:` / `Returns:` entries to describe the
  new failure-safe streaming + post-purge semantics, and called
  out that explicit schema reset must use `store.drop_table()`.
- **F4.2 MEDIUM — new phases had no try/finally around
  `phase_end`.** The "prepare collection", "purge stale
  documents" / "purge stale chunks", and "write metadata" phases
  in both `VaultIndexer.full_index` and `CodebaseIndexer.full_index`
  all followed the `phase_start(...); do_work(); phase_end()`
  pattern. If `ensure_table`, `delete_documents`, or
  `_save_meta` raised, `phase_end()` was skipped and the reporter
  would see an unbalanced phase. **Fix**: wrapped each of the six
  phases (three per indexer) in its own `try/finally`. The inner
  `try: delete_documents() except OSError: raise` pattern in the
  purge step is preserved inside the outer try so the error log
  still fires before the exception propagates.

**New findings — accepted / documented (no fix):**

- **F4.3 LOW — pre-existing phases without try/finally.** The
  older phases (`scan vault`, `parse documents`, `scan codebase`,
  `hash files`, `chunk files`, and the incremental-index phases)
  also use the unguarded pattern. They are not part of the #68
  Track B surface area and were not introduced by this PR;
  fixing them all is scope creep. Tracked here for a future
  `indexer reporter hygiene` pass.
- **F4.4 LOW — `IndexResult.removed` always zero on full_index.**
  The new purge step can delete rows, but `IndexResult.removed`
  remains `0` for `full_index`. The field is only populated by
  `incremental_index`. Accepted — changing the reporting contract
  for full_index is a semantics change that should be its own PR.
- **F4.5 LOW — empty-vault phase sequence not covered by the
  progress integration test.** `test_indexer_progress_integration`
  only runs against a non-empty synthetic vault. The new
  `test_full_index_clean_on_empty_corpus_purges_all` covers the
  empty path at the store-count level but does not assert the
  progress event sequence. Accepted — the event sequence is
  identical between empty and non-empty (same `phase_start`
  invocations with zero totals); adding a dedicated progress
  assertion would be redundant.
- **F4.6 LOW — `full_index` docstring on `CodebaseIndexer`
  already updated in Iteration 2, re-verified here.** No
  additional change needed.
- **F4.7 LOW — `cli.py` `full_index(clean=True)` sites re-
  checked.** Two call sites in `handle_index`; behaviour is
  strictly safer (no destructive upfront drop). No change
  needed.
- **F4.8 LOW — `test_codebase_integration::test_vaultragignore_*`
  re-checked.** The test re-indexes with `clean=True` after
  adding a file that was previously ignored. New behaviour
  (upsert in place + purge stale) still ends up with both
  `src/app.py` (re-upserted with the same chunk IDs) and
  `src/vendor.py` (newly added) in the store. Test passes.

**Test results:**

- 30 integration tests passed, including the new empty-corpus
  regression.
- Ruff / ruff-format / ty all clean.

### Iteration 5 — re-audit queue

After Iteration 4 commits, re-walk the ten domains against:

- `memory_probe.py` — no changes this iteration; re-audit cached-
  module edge cases (concurrent first-call from multiple threads,
  psutil import raising something other than ImportError).
- `indexer.py` — six new `try/finally` blocks; check none of them
  swallow exceptions and that the `raise` inside the purge step
  is still reachable.
- `test_indexer_integration.py` — new regression test touches
  `VaultStore` directly with a test-managed `tmp_path_factory`;
  verify it isolates the Qdrant data dir from the session-scoped
  `rag_components` fixture (distinct `root_dir`, so the config
  lookup goes to a distinct path).
- The broader test suite — spot-check for any test that
  implicitly relies on the old destructive `clean=True` semantics
  (there were two candidates audited above; none failed).
- **New domains to add next iteration**:
  1. **Backwards compatibility** — does the new streaming helper
     still produce bytewise-identical Qdrant collections vs the
     old drop-then-upsert path? (Deterministic input → same IDs
     → same payloads; the answer should be yes but worth a
     direct verification against a reference hash.)
  1. **CLI surface** — does `--clean` flag behaviour still match
     what the help text and README claim?

If Iteration 5 finds new items, open F5.x. Continue until an
iteration passes with zero new items across every domain and
every file in the change set and its dependents.

### Iteration 5 — quiet pass (2026-04-12)

Re-walked the ten domains plus the two added domains
(backwards compatibility, CLI surface) against the Iteration-4
state. Full unit + integration matrix re-run.

**Findings — all accepted / no fix:**

- **F5.1 (analysed → no bug)** — if `store.ensure_table()` raises
  inside the `prepare collection` phase's new try block,
  `existing_ids_before` is never bound. Verified by code path:
  the exception propagates out of `full_index` before the purge
  phase runs, so `NameError` is unreachable. Safe.
- **F5.2 LOW** — `MemoryProbe._sampler_stop` / `_lock` use
  `field(default_factory=...)`, so every instance gets a fresh
  Event / Lock. Verified correct.
- **F5.3 MEDIUM (accepted)** — concurrent first-call race on
  `_psutil_process` and `_torch_module` module-level caches
  could lead to 2× initialisation in parallel samplers. Values
  are identical, so it's a small waste, not a bug. Accepted;
  adding a lock would be over-engineering for a diagnostic tool.
- **F5.4 LOW (verified safe)** — my new
  `test_full_index_clean_on_empty_corpus_purges_all` uses a
  distinct `tmp_path_factory.mktemp` root. `VaultStore` joins
  `root_dir` with the config's **relative** `data_dir`, so
  session-scoped `rag_components` and this test point at
  different Qdrant directories. Isolated.
- **F5.5 LOW (no change)** — `MemoryProbe.__post_init__`
  assigns `peak_rss_mb = start_rss_mb` before the sampler
  starts. No race window because the sampler only updates
  `peak_rss_mb` under `self._lock` and no external thread can
  observe the probe before `__post_init__` returns.
- **F5.6 LOW (accepted)** — `datetime.date.today()` in the
  repro script is local-time; vault frontmatter does not care
  about UTC vs local. Accepted.
- **F5.7 LOW (verified)** — `MemoryProbe.phase` context manager
  relays to `checkpoint`, which is already
  `self._enabled`-guarded. No duplicate env check.
- **F5.8 LOW (accepted)** — module-level caches persist across
  tests in a pytest session. PID / torch state are also
  process-global, so the cache never becomes stale. No test
  resets the caches.
- **F5.9 LOW (accepted as design)** — `threading.Lock` is not
  reentrant. If a caller already holds `gpu_lock` before calling
  `full_index`, a deadlock would occur. Verified against all
  call sites (CLI, watcher, MCP tools, tests): none acquire the
  lock before calling full_index. Accepted as architectural
  invariant.
- **F5.10 LOW (verified)** — `cli.py handle_index` calls
  `full_index(clean=True)` when `--clean` is passed. New
  behaviour is strictly safer (failure-safe rebuild). Help
  text and README do not promise destructive drop-first
  semantics, so no copy change needed.
- **F5.11 LOW (accepted)** — `get_all_ids` may raise
  `RuntimeError`/`VaultStoreLockedError` (not `OSError`). Those
  propagate out of the `except OSError` branch intentionally:
  lock contention should fail fast rather than be silently
  swallowed into an empty snapshot.
- **F5.12 LOW (accepted)** — `_stream_encode_and_upsert_vault`
  unconditionally constructs a `MemoryProbe` even when `docs`
  is empty. When the probe env var is disabled this is a no-op;
  when enabled, it briefly spins up a sampler thread and
  immediately tears it down. Correct, cheap.

**Test matrix (full run):**

- `pytest -m "unit or integration"`: **486 passed, 50 deselected**.
- Ruff / ruff-format / ty: all clean.

**Iteration 5 is the first pass that produced zero action items.**
The audit loop reaches a fixed point here for the current PR
surface. Iteration 6+ will re-open when new code review comments
arrive from wgergely, gemini-code-assist, codex-connector, or a
Claude self-review pass.

**Loop state:** idle. New findings append as F6.x, F7.x, … below
when reviewers post additional comments.

### Iteration 6 — deep sweep on user request (2026-04-12)

User pushed back on Iteration 5's "quiet pass" verdict —
correctly identifying that the audit had been too willing to
mark items "accepted" without actually chasing them. This
iteration reopens the loop with twelve concrete tasks that
trace into files Iteration 5 never opened (watcher, MCP
reindex tools, benchmarks) and into edge cases that were
hand-waved (psutil error paths, sampler thread safety,
concurrent reindex race, signal handling, IndexResult
observability, profile-script scope).

**New findings — fixed in commit `1036085`:**

- **F6.1 HIGH** — Stale MCP tool docstrings.
  `reindex_vault` and `reindex_codebase` still claimed
  `clean=True` "drops and recreates the collection". MCP tool
  docstrings ship to LLM clients as authoritative tool specs,
  so this was actively misleading. Rewrote both to describe
  the failure-safe streaming + post-stream stale-purge
  semantics and noted the new `removed` field semantics.
- **F6.2 MEDIUM (analysed → fixed by F6.6)** — Concurrent MCP
  reindex calls dispatch through `_run_in_thread` to anyio's
  worker pool with no indexer-level lock. Two concurrent
  callers on the same project root could race the
  `existing_ids_before` snapshot. Resolved by F6.6.
- **F6.3 LOW → MEDIUM (escalated)** — `IndexResponse.removed`
  always reported `0` on the `full_index` path because the
  underlying `IndexResult.removed` was hard-coded to `0`.
  MCP / CLI / watcher observability lost the stale-purge
  count entirely. Fixed by F6.10.
- **F6.4 LOW** — `_torch_probed = True` was set BEFORE the
  init body, so a transient `torch.cuda.is_available()`
  failure (driver hiccup on first touch) would be cached as
  "no CUDA forever". Set `_torch_probed` only after the
  full init succeeds; ImportError still cached because a
  missing torch install is permanent.
- **F6.5 LOW** — `tools/profile_vault_index.py` assigned
  `result` inside the inner try block; if `VaultIndexer(...)`
  or `full_index(...)` raised before binding, the
  post-with-block prints raised `UnboundLocalError` and
  masked the original exception. Pre-bind `result = None`
  and guard the prints.
- **F6.6 MEDIUM** — No indexer-level lock against concurrent
  `full_index` / `incremental_index` calls. Real race: two
  reindex calls (manual CLI + watcher, two MCP calls, etc.)
  on the same indexer instance could both snapshot
  `existing_ids_before`, both stream upserts, and both purge.
  Pre-existing class of race that the new failure-safe path
  made longer (the snapshot now lives across the entire
  encode pipeline, not just the upsert). **Fix**: per-indexer
  `threading.Lock` `_writer_lock` acquired by thin public
  wrappers around new `_full_index_locked` /
  `_incremental_index_locked` private methods. Same pattern
  applied to both VaultIndexer and CodebaseIndexer. Search
  reads do not acquire the lock.
- **F6.7 MEDIUM** — `current_rss_mb` had no exception
  handling. `psutil.NoSuchProcess` (stale PID after fork),
  `psutil.AccessDenied` (Windows ACLs),
  `psutil.ZombieProcess` (Linux) would propagate out of the
  sampler thread and crash it silently. Wrapped in try /
  except + drop the cached process handle on failure so the
  next call can re-probe.
- **F6.8 MEDIUM** — `_run` sampler body had no try/except.
  A single bad sample (psutil failure, signal interrupt)
  would crash the thread; subsequent `stop()` joins on a
  dead thread without warning. Wrapped the body in
  try/except, log a warning on failure, continue the loop.
- **F6.9 MEDIUM** — `_release_cuda_cache()` was only called
  on the success path of each slice. KeyboardInterrupt or a
  CUDA OOM mid-encode would skip the release, leaving the
  reserved pool inflated until the next operation. Wrapped
  the slice body in its own try/finally so cleanup runs on
  every exit path. Pre-bind `dense = sparse = None` so the
  finally clause does not hit a `NameError` on early raise.
- **F6.10 MEDIUM** — `IndexResult.removed` on `full_index`.
  The new purge step can legitimately delete rows, but the
  result object always reported `removed=0`. Set
  `removed = len(stale_ids)` in both VaultIndexer and
  CodebaseIndexer return values so MCP responses, CLI
  summaries, and watcher logs surface the actual number of
  purged rows.

**New findings — verified safe / no fix:**

- **F6.11 LOW (verified)** — `_release_cuda_cache()` ordering
  vs upsert. Considered moving it before the I/O-bound upsert
  so concurrent search queries see a smaller pool during the
  I/O wait. Verified that the peak CUDA reserved pool happens
  *during* encode, not after — once encode returns, the
  blocks are idle whether released before or after the
  upsert. Releasing earlier would still incur the host-device
  sync. Left order as-is.
- **F6.12 LOW (accepted as design)** — `memory_probe` import
  is hard-coded into the streaming helpers. If `memory_probe.py`
  were broken, the indexer would break too. Considered making
  it a soft dep; decided against it because a broken probe
  module should fail loudly at install time, and silently
  degrading is worse.
- **F6.13 LOW (accepted)** — `gpu_lock` is `threading.Lock`,
  not `RLock`. Same-thread re-entry would deadlock. Verified
  no caller nests gpu_lock acquisitions; documented on the
  `VaultIndexer.__init__` docstring.

**Iteration 6 also merged `origin/main` (commits up to
`8c83e37`)**, picking up:

- The `test_mcp_registry_lock_exists` RLock-acceptance fix
  (PR #76) that was failing in CI on this branch
- The companion-package release pipeline + store-eviction
  work from #71/#72/#73/#74/#75/#77

After the merge, CI Tests goes from FAILURE → SUCCESS without
any change required from this PR.

**Test results:**

- 324 unit (was 313 pre-merge — main brought 11 new tests)
- 41 integration (vault + codebase + progress + performance)
- Ruff / format / ty all clean
- Live RSS regression repro (synthetic 135 docs, RTX 4080
  SUPER): peak RSS 8.2 GB, peak CUDA reserved 17 GB during
  the worst slice, 1.4 GB between slices. Variance is corpus-
  shape dependent — Iteration 7 wall-clock work is expected
  to dramatically reduce both via sort-by-length batching.

### Iteration 7 — wall-clock fixes (2026-04-12)

User pivoted PR scope to include wall-clock too. Track A
("Wall-clock investigation is out of scope") is retracted.

**Diagnosis:**

`SentenceTransformer.encode` length-sorts each call's input
internally, then iterates `batch_size`-item sub-batches of the
sorted list. The streaming helper was passing
`batch_size=embedding_batch_size=64` (the slice size), which
meant the entire 64-doc slice became one sub-batch. Within
that sub-batch the longest doc (~2000 tokens) determined the
attention matrix size for all 64 — for variable-length vault
corpora (200–8000 chars) this was the source of the 200x
per-item slowdown. Confirmed by inspecting
`SentenceTransformer.encode` source (`length_sorted_idx = np.argsort(...)`) and by querying the loaded model:
`max_seq_length=32768`, `tokenizer.model_max_length=131072`.

**Fixes (commit pending):**

- **F7.1 — `embedding_max_seq_length=2048` config + applied to
  the dense Qwen3 model.** Caps the model's advertised context
  window so the tokenizer truncates aggressively and the model
  cannot allocate position-embedding / attention buffers for
  the 32 k context. `max_embed_chars=8000` truncates raw text
  to ~2000 BPE tokens for Qwen3, so 2048 is the right ceiling.
  **Sparse encoder is intentionally NOT capped**: SPLADE is
  BERT-based (`max_position_embeddings=512`) and a 2048 cap
  causes a position-embedding shape mismatch at forward time.
  The sparse path already truncates internally.
- **F7.2 — `embedding_encode_batch_size=8` config.** New
  config key separate from `embedding_batch_size` (slice size).
  `encode_documents` and `encode_documents_sparse` default to
  this value when no `batch_size` is passed, so
  SentenceTransformer's per-call length sort produces 8-item
  length-uniform sub-batches instead of one 64-item batch.
- **F7.3 — Length-sort docs/chunks BEFORE the streaming
  loop.** Both `_stream_encode_and_upsert_vault` and
  `_stream_encode_and_upsert_codebase` now `sorted(..., key=lambda d: -len(...))` before the slice loop, so each
  slice contains length-uniform items. Combined with F7.2 the
  worst-case padding cost is bounded to one 8-doc sub-batch's
  longest item, not one 64-doc slice's longest item.

**Measured impact (135-doc synthetic corpus, RTX 4080 SUPER):**

| metric             | baseline | iter 6 | iter 7 (live repro) | iter 7 (regression test) |
| ------------------ | -------: | -----: | ------------------: | -----------------------: |
| peak RSS delta     |    24 GB | 8.2 GB |              2.6 GB |                   871 MB |
| wall time (s)      |     1117 |   18.7 |                 4.5 |                      3.5 |
| cuda reserved peak |      n/a |  17 GB |              3.6 GB |                    ~3 GB |

vs the original baseline:

- Peak RSS: **24 GB → 2.6 GB** (9x reduction).
- Wall time: **1117 s → 4.5 s** (248x faster).
- Both targets from the issue (peak RSS 3-5 GB, wall \<30 s)
  are exceeded comfortably.

**Regression test ceilings tightened:**

- `test_vault_full_index_peak_rss_bounded` now asserts
  `delta_mb < 4 * 1024` (was `< 8 * 1024`).
- New assertion: `wall_seconds < 30.0`. Original baseline was
  ~1117 s; empirical post-fix is ~3.5 s on RTX 4080 SUPER, so
  30 s leaves >8x headroom for slower hardware.

**Tests:**

- 324 unit + 41 integration tests pass on the merged branch.
- Ruff / format / ty all clean.

### Iteration 8 — re-audit of wall-clock surfaces (2026-04-12)

Re-walked Iteration 7 changes for any second-order bugs.

**Findings — all verified safe / no fix:**

- **F8.1 verified** — `int(self._dense_model.max_seq_length)`
  in the dense-load log line. If the setattr fails (caught by
  the broad `except`), the attribute retains its prior value
  (32768 for Qwen3) and the log line prints whatever the
  actual value is. Defensive against weird ST versions; log
  remains accurate.
- **F8.2 verified** — `embedding_max_seq_length` config
  default (2048) is delivered by the wrapper's `_RAG_DEFAULTS`
  and confirmed readable via `cfg.embedding_max_seq_length`.
  The `hasattr` check in embeddings.py is belt-and-suspenders
  against non-wrapper configs.
- **F8.3 verified** — Python's `sorted` is stable. Two docs
  with identical length retain their scan order, so
  determinism is preserved across runs of the same input.
- **F8.4 verified** — `_default_encode_batch_size()` reads
  the config on every call, so runtime config changes
  propagate per encode. Consistent with how
  `_default_max_embed_chars()` already worked.
- **F8.5 verified** — `_default_batch_size()` is now unused
  inside `EmbeddingModel`. It still reads
  `embedding_batch_size` (the slice size), so external
  callers that import it still get the slice-size config.
  Left in place for backward compatibility; no churn.
- **F8.6 verified** — No test or caller depends on the
  "first slice = scan order" expectation. Result counts are
  computed via set operations (new_ids, deleted_ids) which
  are order-independent. `_save_meta` writes a dict where
  order doesn't matter.
- **F8.7 verified** — `sorted(...)` is O(n log n); for 50k
  docs the sort cost is negligible (~ms in Python).
- **F8.8 verified** — `len(d.title) + len(d.content)` is a
  cheap O(1) length lookup, not a string concat. No double
  work.
- **F8.9 verified** — `incremental_index` uses the streaming
  helper for changed docs only. The helper sorts a copy via
  `sorted()` and does not mutate the input list, so the
  caller's `docs_to_index` order is preserved if it iterates
  again afterward.
- **F8.10 verified** — `result.added = len(docs)` is computed
  from the original (not sorted) docs list in the full_index
  return statement, so the count is consistent regardless of
  internal processing order.
- **F8.11 verified** — `embedding_encode_batch_size=8` OOM
  backoff path: 8 → 4 → 2 → 1. Same shape as the previous
  64 → 32 → 16 → … → 1 path; the smaller starting point
  reduces OOM probability further.
- **F8.12 verified** — Live regression numbers after
  iteration 7: `delta=+54MB, wall=~3.5s` on the 135-doc
  synthetic corpus. Memory and wall-time ceilings have
  abundant headroom for slower hardware.

**Iteration 8 produced zero action items.** The wall-clock
fix is correct and complete; its second-order surface area
has been swept.

### Iteration 9 — fresh reviewer responses on iter 6/7/8 (2026-04-12)

User triggered fresh `@codex review`, `@gemini review pr`,
`@claude review safety` after iteration 8. All three bots
re-reviewed against the merged-main commit `f32b221`.

**Claude safety review — CLEAN on all three requested areas:**

- `_writer_lock` pattern: consistent ordering, no deadlock,
  no re-entrant trap. The `_full_index_locked` private method
  never calls back into the public wrapper, so the
  non-reentrant `threading.Lock` is safe.
- `except Exception` in sampler thread: narrowly scoped to
  `current_rss_mb()` only; logs full traceback via
  `exc_info=True`; `BaseException` (KeyboardInterrupt,
  SystemExit) escapes correctly. Not a catch-all that hides
  business logic.
- Length-sort ordering: `sorted()` returns a new list so the
  input is not mutated; in-place mutation of `VaultDocument`
  objects flows correctly through both `docs` and `sorted_docs`
  references; all `IndexResult` fields are order-independent.
- Verdict: **"branch is safe to merge from a concurrency and
  correctness standpoint."**

**Claude flagged 2 INFO findings — both addressed in commit
pending:**

- **F9.1 INFO** — `embedding_encode_batch_size` and
  `embedding_max_seq_length` (plus `embedding_batch_size` and
  `max_embed_chars` for symmetry) absent from
  `_ENV_OVERRIDE_MAP`. **Fix**: added all four perf knobs to
  `_ENV_OVERRIDE_MAP` with new `EnvVar` enum members
  (`EMBEDDING_BATCH_SIZE`, `EMBEDDING_ENCODE_BATCH_SIZE`,
  `EMBEDDING_MAX_SEQ_LENGTH`, `MAX_EMBED_CHARS`). The wrapper's
  type-coercion path handles `int` env values automatically.
  Verified end-to-end: `VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE=128`
  etc. all read back as the correct int value.
- **F9.2 INFO (pre-existing)** — `_incremental_index_locked`
  for CodebaseIndexer deletes old chunk IDs before upsert.
  Search queries between the delete and upsert see missing
  chunks. Pre-existing behavior, asymmetric with the
  `_full_index_locked` upsert-then-purge approach. Tracked
  as a follow-up; not regressed by this PR.

**Gemini review — 3 line-level findings:**

- **F9.3 CRITICAL (FALSE POSITIVE)** — gemini reported
  `start` undefined in `_full_index_locked` after the wrapper
  refactor. Verified at `indexer.py:1043`: `start = time.time()` IS in scope, inside `_full_index_locked` body.
  CI Tests (full integration suite) is GREEN, which would
  catch a NameError on the very first integration test run.
  Gemini misread the diff. Marked as no-fix.
- **F9.4 MEDIUM** — `except OSError` in the `prepare collection` step only catches OS-level errors. If
  `get_all_ids` raises `RuntimeError` (Qdrant client error or
  `VaultStoreLockedError`) the indexer crashes entirely.
  **Fix**: broaden to `except (OSError, RuntimeError)` so
  the rebuild continues with an empty `existing_ids_before`
  snapshot (the stale-purge step is then a no-op). Same fix
  applied to both `VaultIndexer` and `CodebaseIndexer`.
- **F9.5 MEDIUM (FALSE POSITIVE)** — `strict=True` in zip
  requires Python 3.10+. The project's `pyproject.toml`
  declares `requires-python = ">=3.13"`, so this is satisfied
  by a generous margin. No-fix.

**Codex review — 1 P2 line-level finding:**

- **F9.6 P2** — `clean=True` no longer drops the collection
  up front, so users who changed embedding model / dimension
  cannot recover via `vaultspec-rag index --clean`. The
  `ensure_table()` call sees the existing collection (with
  the old dimension) and reuses it; subsequent upserts then
  fail with a Qdrant schema mismatch.
  **Fix**: restore destructive `drop_table()` /
  `drop_code_table()` calls in the `prepare collection`
  phase BUT only when `clean=True` is explicitly passed. The
  default `clean=False` path remains failure-safe. This
  resolves the codex iteration 2 P1 (failure-safe by
  default) and the codex iteration 9 P2 (schema reset
  capability) simultaneously: users get failure safety on
  the watcher / incremental path AND a destructive reset
  capability when they explicitly opt in.

**Tests after iteration 9 fixes:**

- 324 unit + 41 integration: PASSED
- Ruff / format / ty: clean
- Env-var override roundtrip verified for all 4 new keys.

**Iteration 10 — re-audit queue:**

After Iteration 9 commits, re-trigger the bots once more to
verify the new `clean=True` destructive path is acceptable
(it directly addresses both codex iterations). Also re-check
any existing tests that exercise `clean=True` to ensure they
still see the expected post-rebuild state.
