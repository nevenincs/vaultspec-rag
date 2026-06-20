---
tags:
  - '#audit'
  - '#storage-lifecycle'
date: '2026-06-19'
related:
  - "[[2026-06-18-storage-lifecycle-plan]]"
---

# `storage-lifecycle` audit: `PR #196 code review`

## Scope

Formal Phase-5 review of the storage-lifecycle surface on branch
`feature/storage-lifecycle` (PR #196), substituting for the retired bot gate.
Three `vaultspec-code-reviewer` agents covered: (1) destructive-verb safety and
out-of-scope-protection invariants, (2) manifest / survey / store-hook
correctness, (3) the qdrant readiness-timeout change and test integrity.
Reviewed `storage_manifest.py`, `storage_safety.py`, `storage_survey.py`,
`storage_ops.py`, `cli/_service_storage.py`, the `store.py` manifest hook,
`qdrant_runtime/_supervise.py`, and the feature's tests against the ADR and
plan. The CLI-direct architecture (no HTTP routes/MCP) is an accepted ADR
divergence and was not treated as a defect.

Outcome: two reviewers request REVISION (safety + correctness/perf); the
timeout/test-integrity reviewer returns PASS. No mock/skip/tautology violations
found. The out-of-scope-protection invariant (prune deletes only orphaned) is
implemented and integration-proven, but two HIGH safety holes and two HIGH
non-safety issues must be fixed before merge.

## Findings

### CRITICAL/HIGH

- **H1 (safety, HIGH/near-critical)** | `storage_ops.py` `delete_prefix` +
  `cli/_service_storage.py` `storage_delete`. `delete_prefix` selects targets by
  `name.startswith(prefix)` and the `--allow-unknown` flag disables the
  manifest-attribution guard. The `prefix` argument has no format validation, so
  `delete --allow-unknown -y ""` (or `... -y r`) matches and drops **every
  collection of every root** - a single-command total out-of-scope wipe, the
  exact thing the feature promises to prevent. Fix: validate the prefix against
  an anchored `^r[0-9a-f]{12}_$` in both the CLI and `delete_prefix`, rejecting
  empty/non-canonical prefixes unconditionally even under `--allow-unknown`.

- **H2 (safety, HIGH)** | `storage_manifest.py` `classify_root`. Orphan
  classification is a bare `Path(entry.root).exists()` with `OSError` swallowed
  to `"orphaned"`. A transiently-unreachable root - UNC/network share,
  unmounted removable drive, permission/timeout error (all common on the primary
  Windows platform) - is misclassified orphaned, so `prune` deletes a fully-live
  index. Fix: treat `OSError`/unreachable as an `"unverifiable"` state that is
  reported but never auto-pruned; classify `orphaned` only on a definitive
  negative for a reachable parent.

- **H3 (performance, HIGH)** | `store.py` `_record_manifest` called at the top of
  `ensure_table`/`ensure_code_table` **before** the `_*_ensured` early-return.
  Those ensure methods front virtually every read/write (search, count, get),
  so every server-mode operation now pays a full manifest `read_text` +
  `json.loads`. The idempotent skip suppresses the write, not the read. This
  reintroduces per-operation hot-path overhead the concurrency work removed. Fix:
  gate the hook behind a once-per-store-lifetime flag so it records at the
  collection-ensure event, not on every operation.

- **H4 (correctness, HIGH)** | `storage_manifest.py` `_status_dir_path` reads
  `VAULTSPEC_RAG_STATUS_DIR` directly and ignores the `--status-dir` CLI override
  that the rest of the system honours via `cfg.status_dir`. With `--status-dir DIR` (no env), `service.json` / qdrant tree / logs land under `DIR` but the
  manifest lands under `~/.vaultspec-rag`; survey then joins a wrong-dir manifest
  and classifies every namespace `unknown`, so prune reclaims nothing. Fix:
  resolve the manifest dir via `get_config().status_dir` (function-local import).

### MEDIUM

- **M1** | `storage_ops.py` `migrate_collections`/`_copy_collection`. A
  mid-scroll failure or final `count_mismatch` reports `failed` but leaves the
  half-created target; a retry then hits `target_exists` and is wedged, and the
  partial target surveys as real points. Fix: drop the just-created target on any
  failure/mismatch before returning.

- **M2** | `storage_ops.py` delete/prune do not release the daemon's in-memory
  slot before dropping a loaded collection (the ADR/plan "return busy" behaviour).
  CLI-direct is accepted and the drop is non-corrupting (server-API, not
  filesystem), but a busy root is deleted out from under a live store instead of
  reported `busy`. Bounded consequence (collection-not-found until re-ensured);
  spec-conformance gap to document or guard.

- **M3** | `storage_manifest.py` `record_root` + `store.py` hook never stamp
  `last_indexed` (always `""`), so the planned survey `--since` filter has no
  data. Fix: stamp an ISO-8601 timestamp at the index event (couple with H3 so
  the stamp does not defeat the idempotent skip).

- **M4** | `store.py` `_record_manifest` catches only `OSError`, but
  `Path.resolve()` (RuntimeError) and JSON paths can raise other types that would
  propagate into indexing - contradicting its "never raised" docstring. Fix:
  broaden to `except Exception` with `logger.debug(exc_info=True)` (justified
  best-effort catch).

- **M5 (tests)** | `tests/integration/test_qdrant_server_mode.py` watcher
  eviction tests assert only that the doomed token disappears, not that a sibling
  survivor still surfaces - so a total search failure would pass green. Fix: add
  a positive survivor assertion (the direct-call tests already do this).

- **M6 (tests)** | `tests/integration/test_storage_ops_integration.py` migrate
  test uses a single-point collection, never exercising the multi-page
  scroll/upload loop or the count-mismatch branch (the load-bearing safety
  property). Fix: add a multi-batch case (e.g. `batch_size=2` over 5 points).

### LOW

- **L1** | `storage_safety.resolve_within` is correct and well-tested but wired
  to no actual deletion path (only migrate's client-open). Forward-looking guard;
  wire it when a local-mode tree-delete lands, or note it as such.
- **L2** | `delete_prefix` partial multi-collection drop leaves a stale manifest
  entry until the self-healing retry. Acceptable; optionally note in `reason`.
- **L3** | Cross-process manifest writes are last-writer-wins (documented);
  residual risk is a transient `unknown`, self-heals on next index. Acceptable
  for v1.
- **L4** | `test_qdrant_ready_timeout.py` generosity test pins `>= 180` rather
  than tying to the measured ~131s cold-load. Cosmetic.
- **Doc nit** | plan step `S37` names the adversarial suite as an integration
  file; it actually ships as the unit `test_storage_adversarial.py` (the
  integration invariant lives in `test_storage_ops_integration.py`).

## Recommendations

- Before merge (REVISION): fix H1 (prefix validation, even under
  `--allow-unknown`), H2 (unverifiable vs orphaned), H3 (record-once hot-path),
  and H4 (status-dir via `cfg.status_dir`). Add the M5 survivor assertion and M6
  multi-batch migrate test in the same pass; address M1 (migrate partial
  cleanup) and M4 (broaden catch). M2/M3 may follow as tracked items.
- H1 and H2 are the load-bearing safety fixes ("safety is key"): without them the
  surface can destroy out-of-scope (H1) or live-but-offline (H2) data.
- Re-run the storage suite + a broad unit pass after the fixes; the changes are
  localized and should not need new GPU runs beyond the existing real-backend
  tests.

## Resolution

Revision landed in commit `5ce0a35`:

- **H1 RESOLVED** - `delete_prefix` hard-gates on `^r[0-9a-f]{12}_$` before any
  lookup, enforced even under `--allow-unknown`; parametrized test proves
  empty/short/non-canonical prefixes are refused with no collection touched.
- **H2 RESOLVED** - `classify_root` returns `unverifiable` (reported, never
  pruned) when the root's drive/share anchor is unreachable; survey surfaces the
  state; unit test covers the unverifiable branch.
- **H3 RESOLVED** - the store manifest hook records at most once per store
  instance (`_manifest_recorded`), off the per-operation hot path.
- **H4 RESOLVED** - the manifest resolves via `get_config().status_dir`, honouring
  `--status-dir`; test fixtures `reset_config()` accordingly.
- **M4 RESOLVED** - hook catch broadened to `Exception` (logged).
- **M5 RESOLVED** - watcher eviction tests assert a kept sibling still surfaces.
- **M6 RESOLVED** - migrate test exercises multi-page paging + count-verify.

Tracked follow-ups (not blocking merge): **M1** migrate partial-target cleanup,
**M2** busy-root slot-release before drop, **M3** stamp `last_indexed`, and the
LOW items (L1 wire the safety guard to a real delete path when local-mode
tree-delete lands; L2/L3/L4 cosmetic). All gates green: ruff / ty / basedpyright,
38 no-GPU storage tests + the GPU watcher/eviction tests.

## Codification candidates

None yet. H1 and H2 point at durable safety constraints (a destructive verb must
validate its target against the canonical namespace format even under an
escape-hatch flag; orphan classification must never treat an unreachable root as
deletable), and the existing rule `namespace-deletion-needs-manifest-attribution`
already encodes the attribution intent H1 partially bypasses. But these are
first-encounter findings on an unmerged branch; per the codify discipline a
lesson qualifies only after it has held across a full cycle. Revisit codification
after the fixes land and the feature ships - the candidate slugs would be
`destructive-target-must-be-canonical` and `orphan-needs-reachable-negative`.
