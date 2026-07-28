---
tags:
  - '#adr'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
related:
  - "[[2026-03-07-blake2b-file-hashing-adr]]"
  - '[[2026-07-28-convergence-cost-research]]'
---

# `convergence-cost` adr: `Stat-evidence rehash gate and scoped convergence retention` | (**status:** `accepted`)

## Problem Statement

Watcher-triggered convergence on a large project costs minutes of full-tree hashing after
trivial changes. `2026-07-28-convergence-cost-research` establishes the two causes: the
unscoped incremental pass proves files unchanged by rehashing every byte, and the durable
retry state escalates to unscoped mode on benign, routine events (coalesced admissions,
success with a newer pending generation). A decision is needed on how to make convergence
cost proportional to actual change without weakening the content-hash authority chosen by
`2026-03-07-blake2b-file-hashing-adr`.

## Considerations

- Content hashes must remain the sole indexing authority; the prior record's grounds for
  rejecting mtime-as-authority stand (`2026-03-07-blake2b-file-hashing-adr`).
- The convergence slot provably retains the exact dirty set across non-success terminals
  in a live process (`2026-07-28-convergence-cost-research`).
- Cross-process and cross-restart safety must not regress: a process that never scoped a
  pending generation must still converge unscoped.
- A wrong "unchanged" verdict is silent corruption; a wrong "changed" verdict is only a
  wasted rehash. Any gate must fail toward rehashing.

## Considered options

- Stat-evidence gate in an advisory sidecar (chosen): per-file `(size, mtime_ns, hash, hashed_at)`; reuse the recorded hash only on exact stat match outside a racy
  window. Pro: unscoped cost drops to O(stat + changed bytes); authority unchanged;
  cache loss degrades to today's behavior. Con: one more sidecar to maintain.
- Widen the published hash sidecar to carry stat evidence: rejected - the sidecar value
  type is a bare digest consumed by ledger publication and parity tests; widening it
  couples an advisory cache to the publication schema.
- Trust mtime alone as change detector: rejected - re-litigates and loses to
  `2026-03-07-blake2b-file-hashing-adr`; a stale mtime would silently skip real changes
  with no hash backstop.
- OS change journals for restart scope recovery: rejected - large platform-specific
  surface for a benefit the stat gate already delivers.
- Keep unconditional unscoped escalation, gate only the hashing: rejected as sole fix -
  correct but leaves scoped convergence rarer than it can safely be; the two fixes
  compose.

## Constraints

- `st_mtime_ns` granularity varies by filesystem and platform timer; the racy window must
  absorb coarse timestamps rather than assume nanosecond fidelity.
- The gate sidecar is written outside the ledger transaction; it must be atomic and its
  absence, staleness, or corruption must only ever cause extra hashing, never a skipped
  reindex beyond what stat-identity already implies.
- Durable retry-state invariants (`unscoped_required` implies `convergence_pending`;
  attempt identity wholly present or absent) must hold across the change.

## Implementation

One shared gate module owns stat evidence for all three domains. It loads an advisory
sidecar mapping relative path to `(size, mtime_ns, hash, hashed_at)`, answers "may this
file's recorded hash be reused" by exact `(size, mtime_ns)` match plus a racy-window
check (the recorded mtime must predate the recorded hashing instant by a safety margin),
records fresh evidence for every file actually hashed, and persists atomically after a
run. The codebase indexer's single hashing loop, the document indexer's unscoped
selection, and the vault indexer's document hashing all consult the gate; a miss, a stat
failure, a corrupt sidecar, or a racy entry falls through to `hashlib.file_digest`
exactly as today. Deleted files are pruned on persist.

In the retry state, `record_interrupted` and `record_success` stop forcing
`unscoped_required=True`; each preserves the prior value (success clears it when no newer
generation is pending, exactly as it clears `convergence_pending`). Failure, crash
recovery, construction over a loaded pending bit, and refresh-time promotion of a
generation the instance did not scope keep escalating unchanged - those are the paths
where volatile scope genuinely may not exist.

## Rationale

The gate keeps the knockout property of `2026-03-07-blake2b-file-hashing-adr` - content
hash as sole authority - while removing the O(total bytes) unchanged-proof cost that
record never priced in at code-corpus scale. Fail-toward-rehash means every degraded
state (missing cache, coarse timestamps, mid-write races) converges to current behavior,
so the gate cannot introduce a new silent-staleness class beyond deliberate
stat-identity forgery, which git's identical design accepts. Scope retention is decided
by where the volatile dirty set provably lives
(`2026-07-28-convergence-cost-research`): the live instance retains it, so only
process-boundary paths need the unscoped safety net, and those paths already own their
escalation.

## Consequences

- Unscoped convergence cost becomes O(stat calls + changed bytes); minutes become
  seconds on tens of thousands of files.
- Coalesced and mid-attempt-superseded watcher events converge scoped instead of
  triggering full-tree passes.
- A new sidecar exists per domain; it is advisory, atomic, and prunable, but it is one
  more artifact in the data directory.
- Files whose content changes while `(size, mtime_ns)` is deliberately restored inside
  the racy window are missed until any stat-visible change - the standard, accepted
  stat-cache limitation.
- The retry-state test surface changes: interruption and success no longer assert
  unconditional escalation, and new tests must pin the preserved escalation paths.
