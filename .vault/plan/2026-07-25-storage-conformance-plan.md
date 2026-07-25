---
tags:
  - '#plan'
  - '#storage-conformance'
date: '2026-07-25'
modified: '2026-07-25'
tier: L2
related:
  - '[[2026-07-25-storage-conformance-adr]]'
  - '[[2026-07-25-storage-conformance-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `storage-conformance` plan

### Phase `P01` - establish the durable identity record

Creates the per-collection identity the rest of the plan compares against, and stops the manifest from overwriting the record a verifier would read.

- [x] `P01.S01` - Record the pre-change suite baseline and the current manifest record shape so later regressions stay attributable; `src/vaultspec_rag/tests/`.
- [x] `P01.S02` - Add the per-collection identity record type and its manifest serialization, defaulting absent identity to unknown rather than to current values; `src/vaultspec_rag/storage_manifest.py`.
- [x] `P01.S23` - Add the local-mode identity sidecar under the per-root storage directory, and the backend-dispatching accessor pair every caller uses instead of either home; `src/vaultspec_rag/storage_identity.py`.
- [x] `P01.S03` - Stamp the effective dense model, sparse model, dense width, distance, vector names, and schema generation when a collection is created; `src/vaultspec_rag/store.py`.
- [x] `P01.S04` - Preserve a stored schema generation and identity when recording a root instead of overwriting them with current values; `src/vaultspec_rag/storage_manifest.py`.
- [x] `P01.S05` - Cover the preserve with a guard test, and prove it fails when the overwrite is restored; `src/vaultspec_rag/tests/test_storage_manifest.py`.
- [x] `P01.S24` - Cover the local sidecar round-trip and confirm a local root records no manifest entry; `src/vaultspec_rag/tests/test_storage_identity.py`.

### Phase `P02` - verify on the ensure seam

Adds the three-verdict conformance check where every read and write already passes, refusing on geometry and degrading on model identity.

- [x] `P02.S06` - Read live collection geometry back from the backend behind the existing per-collection ensure cache so it never reaches the query path; `src/vaultspec_rag/store.py`.
- [x] `P02.S07` - Add the three-verdict conformance evaluator over stamped identity and live geometry, feeding the existing compatibility comparator; `src/vaultspec_rag/store_schema.py`.
- [x] `P02.S08` - Refuse a dense width, distance, or vector-name disagreement at the ensure step with a message naming expected and actual; `src/vaultspec_rag/store.py`.
- [x] `P02.S09` - Report a model-identity disagreement at equal width as nonconforming without raising, leaving the collection readable; `src/vaultspec_rag/store.py`.
- [x] `P02.S10` - Report a namespace carrying no stamped identity as unverifiable, never as a failure; `src/vaultspec_rag/store.py`.
- [x] `P02.S11` - Cover the three verdicts with guard tests, and prove each fails against a deliberately conforming fixture; `src/vaultspec_rag/tests/test_store_conformance.py`.

### Phase `P03` - surface the verdict to an operator

Makes a non-conforming namespace legible where degradation is already authored and where storage is already surveyed, each with a remedy attached.

- [x] `P03.S12` - Author the nonconforming verdict as a live-service degraded reason where degradation is already authored; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P03.S13` - Pair the conformance degradation with its rebuild remediation command in the existing degraded-family registry; `src/vaultspec_rag/cli/_status_labels.py`.
- [x] `P03.S14` - Report the per-collection verdict and stamped identity in the storage survey payload; `src/vaultspec_rag/storage_survey.py`.
- [x] `P03.S15` - Render the survey verdict and stamped models in the storage CLI view; `src/vaultspec_rag/cli/_service_storage.py`.
- [x] `P03.S16` - Cover the degradation surfacing with a guard test, and prove it fails when the reason is dropped; `src/vaultspec_rag/tests/test_server_routes.py`.

### Phase `P04` - close the propagation holes

Stops a copied or archived namespace from inheriting conformance it never established.

- [ ] `P04.S17` - Carry the source identity through a namespace copy instead of stamping current values onto the destination; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P04.S18` - Record the stamped identity in the archive snapshot manifest so a restore can be judged; `src/vaultspec_rag/storage_manifest.py`.
- [ ] `P04.S19` - Keep an unverifiable namespace out of automated reclamation candidacy; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P04.S20` - Cover the copy carry and the reclamation exclusion with guard tests, and prove each fails when its carry is reverted; `src/vaultspec_rag/tests/test_storage_ops.py`.

### Phase `P05` - close out

Proves the whole surface green, records the guard failure proofs, and reviews the delivered feature.

- [ ] `P05.S21` - Run the full suite, lint, type, and citation gates and reconcile the result against the recorded baseline; `src/vaultspec_rag/`.
- [ ] `P05.S22` - Review the delivered feature against the authorizing decision and record the audit; `src/vaultspec_rag/`.

## Description

Implements `2026-07-25-storage-conformance-adr` end to end, grounded in
`2026-07-25-storage-conformance-research`. The plan gives the service a durable
record of what produced each collection, verifies it where every read and write
already passes, and makes a non-conforming namespace visible to an operator with a
remedy attached.

The ordering is forced by one dependency: nothing can be verified until something
is stamped, and nothing stays stamped while the manifest overwrites itself. `P01`
therefore establishes the durable record and stops the self-relabelling before
`P02` adds any comparison. `P03` surfaces the verdict, and `P04` closes the
propagation holes that would let a namespace inherit conformance it never earned.

A hard boundary applies throughout. The code indexer, the run ledger, and the run
checkpoint are mid-refactor under a separate in-flight plan and are out of bounds;
the ADR's constraint section commits this work to the store, the manifest, the
health author, and the status renderer. Any step that appears to need one of those
modules is a signal to stop and re-scope, not to edit across the boundary.

This feature is almost entirely guards and negative assertions, so the project's
guard-test obligation governs every step that adds one: the guard is observed
failing for its intended reason before it is trusted, and both directions are
recorded in that step's record.

## Steps

## Parallelization

`P01` is a hard prerequisite for everything else and admits no parallelism with
later Phases: `P02` compares a record `P01` creates, and comparing a record that
is still being overwritten produces a check that certifies its own last write.

Within `P01`, the manifest shape and the stamp-at-create work are sequential
(`S01` before `S02`), while the relabelling fix (`S03`) touches a different
function and may proceed alongside `S02`.

`P02` is strictly sequential; each step narrows the verdict the previous one
produced.

`P03` and `P04` share no code and may run in parallel once `P02` lands. `P03`
touches the health author, the status renderer, and the survey payload; `P04`
touches the copy path and the archive manifest.

`P05` is the closeout and runs last.

## Verification

The plan is complete when every Step is closed and each criterion below holds.

- A newly created collection carries a stamped identity recording dense model,
  sparse model or its absence, effective dense width, distance, vector names, and
  storage schema generation; asserted by test.
- Opening a store no longer rewrites a stored schema generation or identity.
  Proven by a test that writes a stale record, opens the store, and asserts the
  stored value survived unchanged.
- A collection whose stamped dense model differs from the running configuration at
  equal width is reported `nonconforming` and does not raise; a search against it
  still returns results.
- A dense-width disagreement is refused at the ensure step with a message naming
  the expected and actual width, before any retry budget is consumed.
- A namespace stamped before this feature existed is reported `unverifiable`, does
  not degrade the service, and is never treated as a reclamation candidate.
- A `nonconforming` verdict appears in the live service degraded reasons with a
  paired remediation command, and is visible on the status surface.
- The storage survey payload reports the per-collection verdict and stamped
  identity.
- A copied namespace carries the source identity rather than a fabricated current
  one; asserted by test.
- Every guard added by this plan has a recorded failure proof in its Step Record:
  the mutation applied, the observed failure and its reason, and the restored
  green run.
- The full suite passes at or above the pre-change baseline recorded in `P01.S01`,
  and lint, type, and citation gates are clean.
