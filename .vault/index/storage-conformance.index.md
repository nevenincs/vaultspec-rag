---
generated: true
tags:
  - '#index'
  - '#storage-conformance'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:df6fcc8ae73f5b1df6bbf5e82742b5d0b7c51e96f736c910380400a230f1fcf5'
related:
  - '[[2026-07-25-storage-conformance-P01-S01]]'
  - '[[2026-07-25-storage-conformance-P01-S02]]'
  - '[[2026-07-25-storage-conformance-P01-S03]]'
  - '[[2026-07-25-storage-conformance-P01-S04]]'
  - '[[2026-07-25-storage-conformance-P01-S05]]'
  - '[[2026-07-25-storage-conformance-P01-S23]]'
  - '[[2026-07-25-storage-conformance-P01-S24]]'
  - '[[2026-07-25-storage-conformance-P02-S06]]'
  - '[[2026-07-25-storage-conformance-P02-S07]]'
  - '[[2026-07-25-storage-conformance-P02-S08]]'
  - '[[2026-07-25-storage-conformance-P02-S09]]'
  - '[[2026-07-25-storage-conformance-P02-S10]]'
  - '[[2026-07-25-storage-conformance-P02-S11]]'
  - '[[2026-07-25-storage-conformance-P03-S12]]'
  - '[[2026-07-25-storage-conformance-P03-S13]]'
  - '[[2026-07-25-storage-conformance-P03-S14]]'
  - '[[2026-07-25-storage-conformance-P03-S15]]'
  - '[[2026-07-25-storage-conformance-P03-S16]]'
  - '[[2026-07-25-storage-conformance-P04-S17]]'
  - '[[2026-07-25-storage-conformance-P04-S18]]'
  - '[[2026-07-25-storage-conformance-P04-S19]]'
  - '[[2026-07-25-storage-conformance-P04-S20]]'
  - '[[2026-07-25-storage-conformance-P04-summary]]'
  - '[[2026-07-25-storage-conformance-P05-S21]]'
  - '[[2026-07-25-storage-conformance-P05-S22]]'
  - '[[2026-07-25-storage-conformance-P05-summary]]'
  - '[[2026-07-25-storage-conformance-adr]]'
  - '[[2026-07-25-storage-conformance-closing-review-audit]]'
  - '[[2026-07-25-storage-conformance-plan]]'
  - '[[2026-07-25-storage-conformance-research]]'
---

# `storage-conformance` feature index

Auto-generated index of all documents tagged with `#storage-conformance`.

## Documents

### adr

- `2026-07-25-storage-conformance-adr` - `storage-conformance` adr: `prove a collection was built by the models the code expects` | (**status:** `accepted`)

### audit

- `2026-07-25-storage-conformance-closing-review-audit` - `storage-conformance` audit: `closing review`

### exec

- `2026-07-25-storage-conformance-P01-S01` - Record the pre-change suite baseline and the current manifest record shape so later regressions stay attributable
- `2026-07-25-storage-conformance-P01-S02` - Add the per-collection identity record type and its manifest serialization, defaulting absent identity to unknown rather than to current values
- `2026-07-25-storage-conformance-P01-S03` - Stamp the effective dense model, sparse model, dense width, distance, vector names, and schema generation when a collection is created
- `2026-07-25-storage-conformance-P01-S04` - Preserve a stored schema generation and identity when recording a root instead of overwriting them with current values
- `2026-07-25-storage-conformance-P01-S05` - Cover the preserve with a guard test, and prove it fails when the overwrite is restored
- `2026-07-25-storage-conformance-P01-S23` - Add the local-mode identity sidecar under the per-root storage directory, and the backend-dispatching accessor pair every caller uses instead of either home
- `2026-07-25-storage-conformance-P01-S24` - Cover the local sidecar round-trip and confirm a local root records no manifest entry
- `2026-07-25-storage-conformance-P02-S06` - Read live collection geometry back from the backend behind the existing per-collection ensure cache so it never reaches the query path
- `2026-07-25-storage-conformance-P02-S07` - Add the three-verdict conformance evaluator over stamped identity and live geometry, feeding the existing compatibility comparator
- `2026-07-25-storage-conformance-P02-S08` - Refuse a dense width, distance, or vector-name disagreement at the ensure step with a message naming expected and actual
- `2026-07-25-storage-conformance-P02-S09` - Report a model-identity disagreement at equal width as nonconforming without raising, leaving the collection readable
- `2026-07-25-storage-conformance-P02-S10` - Report a namespace carrying no stamped identity as unverifiable, never as a failure
- `2026-07-25-storage-conformance-P02-S11` - Cover the three verdicts with guard tests, and prove each fails against a deliberately conforming fixture
- `2026-07-25-storage-conformance-P03-S12` - Author the nonconforming verdict as a live-service degraded reason where degradation is already authored
- `2026-07-25-storage-conformance-P03-S13` - Pair the conformance degradation with its rebuild remediation command in the existing degraded-family registry
- `2026-07-25-storage-conformance-P03-S14` - Report the per-collection verdict and stamped identity in the storage survey payload
- `2026-07-25-storage-conformance-P03-S15` - Render the survey verdict and stamped models in the storage CLI view
- `2026-07-25-storage-conformance-P03-S16` - Cover the degradation surfacing with a guard test, and prove it fails when the reason is dropped
- `2026-07-25-storage-conformance-P04-S17` - Carry the source identity through a namespace copy instead of stamping current values onto the destination
- `2026-07-25-storage-conformance-P04-S18` - Record the stamped identity in the archive snapshot manifest so a restore can be judged
- `2026-07-25-storage-conformance-P04-S19` - Keep an unverifiable namespace out of automated reclamation candidacy
- `2026-07-25-storage-conformance-P04-S20` - Cover the copy carry and the reclamation exclusion with guard tests, and prove each fails when its carry is reverted
- `2026-07-25-storage-conformance-P04-summary` - `storage-conformance` `P04` summary
- `2026-07-25-storage-conformance-P05-S21` - Run the full suite, lint, type, and citation gates and reconcile the result against the recorded baseline
- `2026-07-25-storage-conformance-P05-S22` - Review the delivered feature against the authorizing decision and record the audit
- `2026-07-25-storage-conformance-P05-summary` - `storage-conformance` `P05` summary

### plan

- `2026-07-25-storage-conformance-plan` - `storage-conformance` plan

### research

- `2026-07-25-storage-conformance-research` - `storage-conformance` research: `verifying stored data against the code that reads it`
