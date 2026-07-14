---
tags:
  - '#audit'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-14'
related:
  - '[[2026-07-13-index-drift-hardening-adr]]'
  - '[[2026-07-13-index-drift-hardening-plan]]'
  - '[[2026-07-13-index-drift-hardening-research]]'
---

# `index-drift-hardening` audit: `feature code review and closeout`

## Scope

Adversarial review of the full uncommitted feature (working tree versus HEAD)
before merge: the config-epoch drift sentinel (`_config_epoch.py`,
`_codebase_indexer.py`, `_vault_indexer.py`), the preprocess tri-state and TOFU
trust store (`config.py`, `_preprocess_trust.py`, `_preprocess_config.py`), the
CLI surface (`cli/_preprocess.py`, `cli/_index.py`, `cli/_process.py`,
`cli/_service_lifecycle.py`), the watcher change filter (`watcher.py`), and the
four new or reworked test modules. Reviewed against the ADR decision set
(D1-D10, including the no-back-compat owner amendment) and the binding project
rules (worker torch discipline, service-domain operability, GPU-lock scope,
test storage isolation). Priority order: the TOFU security boundary, the
drift-escalation matrix, concurrency, quality.

## Findings

### content-epoch-misses-emitted-cap | medium | the emitted-text cap escaped the content epoch

`code_content_epoch` hashed the preprocess invocation surface and `html_strip`
but not `preprocess_max_emitted_bytes`; changing the cap re-truncates any
extraction that exceeds it, producing different chunk text on unchanged bytes
with no rebuild - the exact drift class the epoch exists to catch. The ADR's D1
enumeration also omitted it (spec and implementation gap). **Fixed pre-merge:**
the cap is now a required content-epoch input, threaded from config at the
single production call site, with a sensitivity unit test.

### mode-flip-rebuild-churn | medium | alternating effective modes rebuilds the corpus each flip

The epoch is computed over the gated rule set, so the effective preprocess mode
moves the content epoch: a root served by a default-mode daemon that an
operator also indexes with the trust-all flag clean-rebuilds on every
alternation. Each rebuild is correct for the then-current mode - an operational
footgun, not a correctness bug; the one-time rebuild after `preprocess trust`
is intended. **Fixed pre-merge (documentation):** the preprocessing guide now
warns against per-run mode flags and steers to a one-time trust plus a single
steady mode per host.

### content-epoch-overreaches-on-timeout | low | timeout and failure-handling edits force a rebuild

`timeout_s` and `on_error` do not change successful extraction output, yet an
edit forces a full clean rebuild - an expensive false positive on a large
corpus. ADR-mandated composition, so recorded rather than changed. Follow-up
option: drop both from the content epoch and keep them only in the trust hash.

### gitignore-sort-drops-negation-order | low | sorted multiset misses negation reorders

Sorting the gitignore patterns kills traversal-order false positives (the
higher-value tradeoff) but means reordering a negation line relative to the
pattern it negates changes matching without changing the epoch. Edge case
judged acceptable; no fix planned.

### default-str-hash-ambiguity | low | canonical JSON stringifies non-primitive option values

A datetime option value and its ISO-string equivalent serialize identically in
the trust hash and epochs. Confined to opaque `options` values - it cannot
escalate to running a different command - so no security impact. Follow-up
option: type-tag non-primitive values in canonicalization.

### conflict-exit-code-asymmetry | low | flag-conflict exits 2 on index but 1 on server start

The same mutually-exclusive-flags usage error exits 2 via the index verb and 1
via server start's fail path. Both are documented as shipped in the CLI
reference. Follow-up option: align on 2.

### run-one-blocked-before-trust | low | the authoring aid is trust-gated

`preprocess run-one` flows through the non-strict gate (correct for security),
so an author cannot trial a rule before trusting the root; the gated case now
prints the actionable trust message. Follow-up option: a strict-resolving
trial mode with a loud bypass notice.

### Clean dimensions

The security boundary held under adversarial tracing: every executing path
(chunk worker, run-one) resolves rules through the gated loader; the strict
bypass is confined to non-executing inspect/hash/display paths; the trust
store lives outside the repo with no repo-controllable redirect; TOCTOU is
closed by re-hashing at every load; a corrupt store degrades to untrusted.
Torch discipline, writer-lock coverage of the new dispatch and escalations,
the watcher's GIL-atomic config swap, and test integrity (behavioral tests,
sentinel-based execution proofs, no mocks of code under test, no skips) all
passed with nothing found.

### full-integration-baseline-rot | medium | 11 pre-existing failures on main, none from this feature

The closeout gate ran the entire integration suite (no GPU CI exists, so this
was likely its first full local run in several release cycles) and found 12
failures plus 2 collection errors. Every one was classified with an
evidence-based discriminator - the suspect tests were re-run against pure HEAD
code (a scratch worktree with HEAD sources pinned via the import path for both
pytest and the spawned daemon):

- 2 errors in the watcher-control module: a lint-driven rename had unbound the
  `live_service` fixture (`_live_service` in signatures, fixture defines
  `live_service`) - pre-existing since the MCP-conformance era. **Fixed in
  this branch** via `usefixtures`; all three tests now pass against a real
  subprocess daemon.
- CLI index/search and testimonial failures: the plain-index-summaries rework
  changed output labels (`Codebase` to `Source code`) and search exit-code
  behavior without updating these tests - reproduced identically on HEAD.
- The empty-corpus purge regression guard and the facade end-to-end test:
  reproduced on HEAD, root-caused to qdrant-client 1.18.0's local mode on
  Windows - `delete_collection` removes the collection with
  `shutil.rmtree(ignore_errors=True)`, which silently fails on mmap-locked
  files, and a subsequent same-name `create_collection` re-opens the leftover
  storage, resurrecting deleted points. Upstream-triggered store-layer bug,
  pre-existing, independent of this feature.
- Idle-TTL and LRU eviction failures: reproduced on HEAD.
- `test_evict_busy_returns_busy`: flaky on both trees (self-declared
  timing-sensitive, "flakes do not block merge").

One environmental class was also identified and eliminated: a live resident
service on the developer machine makes every delegation-sensitive CLI test
delegate instead of running in-process; full-suite runs require the machine
singleton stopped.

**Follow-up required (separate pipeline):** the qdrant local delete-resurrect
bug deserves its own research/ADR (store-layer verify-after-delete or an
upstream pin/patch), and the stale CLI-expectation tests need reconciling with
the plain-summaries output contract.

### Process findings from execution

Two defects were caught and fixed during the execution gate rather than by the
review: the in-process env mutation performed by the index verb's mode flags
leaked across test modules until the CLI test fixture force-restored the mode
keys, and one full-suite failure of the machine-singleton reclaim test was
diagnosed as CPU contention from concurrent executor test runs (it passes
alone, in related subsets, and in the full suite on a quiet machine).

## Recommendations

- Ship the feature: verdict PASS, no critical or high findings, both mediums
  fixed pre-merge.
- Queue the four LOW follow-ups above as candidates for a later hygiene pass;
  none blocks merge.
- Promote the audit-C1 codification candidate `preprocess-config-is-code- execution` once this design holds a cycle: the TOFU half the original fix
  never shipped now exists and is enforced.
- Consider a future ADR amendment enumerating `preprocess_max_emitted_bytes`
  in D1's content-epoch input list, superseding the gap this audit closed.
