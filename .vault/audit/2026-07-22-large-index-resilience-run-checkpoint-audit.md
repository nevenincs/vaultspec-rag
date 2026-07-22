---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `large-index-resilience` audit: `run checkpoint bridge`

## Scope

Reviewed commit `7f0b6ca` and the current shared-worktree remediation of
`CodeRunCheckpoint` against the accepted large-index resilience decision and
W02.P06 S22-S25. The review covered deterministic segment projection,
storage-first checkpoint boundaries, bounded resume filtering, full and
incremental manifest authority, scoped deletion, metadata publication,
signature invalidation, durable progress, and real-test integrity. The
underlying ledger invariants and the already-reviewed atomic metadata writer
were treated as governing contracts.

## Findings

### unresolved-publication-filter | high | Failed file states are removed before fail-closed publication

Commit `7f0b6ca` calls `iter_file_states` with `converged_only=True`, so chunk,
embedding, admission, or storage failures never reach
`publish_meta_from_file_states` and cannot trigger its unresolved-state
rejection. The helper can replace metadata and advance the durable phase while
known failures remain. The current worktree removes this filter and adds a real
unresolved-row regression, which is the correct direction, but the ordering
finding below must also be resolved so rejection remains recoverable.

### pending-segment-materialization | high | Resume filtering retains every pending segment

Commit `7f0b6ca` accumulates `pending_segments` into a list and returns a tuple.
That retains all chunk-bearing segments supplied by a file or stream and
reintroduces the unbounded host-memory behavior S22-S25 are meant to remove. The
current worktree converts this method to a generator, resolving this finding;
retain a generator-based regression that proves only demand-sized input is
consumed.

### multi-unit-checkpoint-window | high | One store mutation is followed by several ledger commits

`record_confirmed_segments` is documented as running after a shared store
mutation, then records each segment in a separate ledger transaction. A crash
between the store return and those commits can therefore replay the whole slice,
not at most the last unrecorded commit unit. The current worktree replaces it
with singular `record_confirmed_segment`, aligning one caller-confirmed storage
mutation with one ledger transaction and resolving the helper-side defect. The
pipeline must preserve that one-to-one call boundary rather than upserting a
multi-segment slice first.

### incremental-manifest-authority | high | Current-generation changed rows are not a complete sidecar

The committed helper replaces the sidecar solely from the active generation's
file states. Unchanged incremental paths have no current-generation upsert units
and cannot be recorded as indexed because the ledger correctly requires
storage-confirmed evidence. They are consequently omitted from unscoped and
scoped incremental publication. The current ledger worktree begins carrying a
compatible successful manifest forward, but finalization still needs an
authoritative completeness gate and an explicit safe outcome when no compatible
published ledger generation exists. In particular, the first incremental run
after adopting the ledger must import or reconcile the legacy published
manifest, or escalate to a full rebuild, rather than publish only changed rows.

The current worktree resolves the helper-side authority gap by carrying only a
content-compatible successful generation, recording its parent identity, and
rejecting the first incremental attempt with an instruction to run full
reconciliation when no compatible manifest exists. Its new finalization gate
also rejects incomplete upsert evidence. Keep these changes and add a real
full-to-incremental preservation test before closing the finding.

### deletion-manifest-state | high | Confirmed deletion leaves the carried indexed hash publishable

`record_confirmed_deletion` records an idempotent delete unit but does not remove
or tombstone the path's carried indexed file state. With manifest carry-forward,
metadata publication therefore writes the deleted path and its old hash back to
the sidecar. Add an explicit converged deletion outcome, bind it to the confirmed
delete unit, exclude it from indexed metadata, and verify scoped and unscoped
deletion across restart.

The current worktree partially remediates this by removing the path state after
a confirmed `delete_path` unit. The unit commit and manifest removal are separate
transactions, however, and finalization does not reject a `delete_path` that
still has a carried file state. A crash between those transactions can therefore
leave a confirmed deletion whose old hash remains publishable. Commit both local
evidence changes together or add a finalization conflict check and a real
between-boundary restart regression.

### finalization-freeze-order | high | Unresolved publication permanently freezes repair

`publish_metadata` advances to `stale_reconciled` before it validates and writes
the metadata rows. Advancing out of `ingesting` freezes every file state. After
the current worktree correctly passes unresolved rows to the publisher, a
rejection leaves the generation running at `stale_reconciled` but unable to
replace the failed state after retry. Prove ingestion completeness before the
first finalization transition, then perform atomic publication and advance the
metadata phase only after success.

The current worktree resolves this finding by running a bounded readiness check
inside the transaction that would leave `ingesting`. An unresolved row now
raises without advancing the phase, so a retry can replace the file state.

### carried-evidence-conflict | high | Partial replacement can coexist with stale converged evidence

A carried indexed row remains converged while new commit units for the same path
are being recorded. Until the final new segment replaces that file state, the
generation contains current partial storage evidence alongside an old published
hash. Nothing currently prevents finalization in that condition. Before leaving
ingestion, reject every path whose current-generation mutation evidence is not
matched by a current converged outcome; use the carried evidence-generation
identity as provenance, not as permission to publish through a partial update.

The current worktree resolves this finding for upserts: finalization rejects
incomplete unit sequences and requires every upsert path's digest to match an
indexed state. The deletion conflict remains tracked separately above.

### deletion-resume-identity | medium | The helper cannot skip an already confirmed deletion

The segment path exposes `pending_segments`, but deletion has only a post-store
recording method. A restart caller cannot ask the checkpoint whether the exact
deletion unit is already committed without reconstructing private unit logic,
and reconstructing the original point-ID tuple after deletion may be impossible
from storage. Expose a deterministic deletion-unit or pending-deletion contract
whose identity survives the store mutation and prove that confirmed deletions
are skipped after restart.

### point-identity-semantics | medium | Publication consumers cannot request retained point IDs

S25 requires deterministic point identities to stream through the ledger
contract. The checkpoint exposes no such iterator, while the ledger's generic
point iterator includes IDs from both upsert and delete units. A stale-identity
consumer could therefore preserve deleted IDs if it treats that stream as the
retained generation set. Expose an upsert-only retained-ID iterator or a typed
unit-kind filter and verify bounded ordering and deletion exclusion.

### signature-configuration-contract | medium | Compatibility depends on an arbitrary stringified mapping

`open` accepts an unconstrained configuration mapping and fingerprints it with
`json.dumps(default=str)`. Callers can omit segmentation-affecting inputs or
pass values whose string form is unstable, allowing incompatible work to resume
or compatible work to invalidate. Replace this with a closed, typed canonical
signature payload containing every storage- and segmentation-affecting field;
reject unsupported values instead of stringifying them.

### verification-matrix | medium | The committed tests cover only full-segment resume and one drift field

The two committed tests use real ledger files and production types, but do not
exercise incremental manifest preservation, scoped deletion, unresolved-state
recovery, lazy iterator consumption, point-ID streaming, or one-unit replay
around the store/checkpoint boundary. During review, concurrent schema work also
temporarily made two of three current-worktree tests fail because the new
`evidence_generation_id` column was required but not supplied by
`record_file_state`. Keep the schema and writer change atomic, then add the
missing real-behavior matrix before integration is considered complete.

### test-integrity | low | The checkpoint tests use production behavior and real SQLite

The reviewed tests import production checkpoint, ledger, policy, segment, and
chunk types directly and use real temporary SQLite files. They contain no fake,
mock, stub, patch, monkeypatch, skip, or expected-failure shortcut.

## Recommendations

Do not integrate the checkpoint bridge until metadata publication has a complete
incremental manifest authority, confirmed deletions remove or tombstone carried
state, and finalization proves every current mutation has a recoverable converged
outcome before freezing ingestion. Preserve the current generator and singular
checkpoint remediations, expose typed deletion-resume and retained-point-ID
contracts, and replace the open-ended configuration mapping with canonical
signature inputs.

The initial focused run against the moving shared worktree passed Ruff and Ty.
One of three checkpoint tests passed; two failed with the transient
`evidence_generation_id` schema/writer mismatch described above. Re-run the
checkpoint and ledger suites together after the concurrent ledger edit settles.

After the schema writer settled and the readiness gate landed, a combined
checkpoint-and-ledger run passed nine of eleven tests. The two remaining
failures are assertion drift: the checkpoint test expects `ValueError` instead
of the typed `RunLedgerStateError`, and the older ledger test still expects a
generation containing a failed file state to finalize. Ruff and Ty remain
clean.
