---
generated: true
tags:
  - '#index'
  - '#archive-restore-contract'
date: '2026-08-25'
modified: '2026-08-25'
body_schema: 'body-v1'
body_hash: 'sha256:467b8eae3e493751e01b57a6beeed71ed331b7b98c92cde2b020fbb276b51fca'
related:
  - '[[2026-07-25-archive-restore-contract-P01-S01]]'
  - '[[2026-07-25-archive-restore-contract-P01-S02]]'
  - '[[2026-07-25-archive-restore-contract-P01-S03]]'
  - '[[2026-07-25-archive-restore-contract-P01-S04]]'
  - '[[2026-07-25-archive-restore-contract-P01-S05]]'
  - '[[2026-07-25-archive-restore-contract-P01-summary]]'
  - '[[2026-07-25-archive-restore-contract-P02-S06]]'
  - '[[2026-07-25-archive-restore-contract-P02-S07]]'
  - '[[2026-07-25-archive-restore-contract-P02-S08]]'
  - '[[2026-07-25-archive-restore-contract-P02-S09]]'
  - '[[2026-07-25-archive-restore-contract-P02-S10]]'
  - '[[2026-07-25-archive-restore-contract-P02-S11]]'
  - '[[2026-07-25-archive-restore-contract-P03-S12]]'
  - '[[2026-07-25-archive-restore-contract-P03-S14]]'
  - '[[2026-07-25-archive-restore-contract-P04-S15]]'
  - '[[2026-07-25-archive-restore-contract-P04-S16]]'
  - '[[2026-07-25-archive-restore-contract-P04-S17]]'
  - '[[2026-07-25-archive-restore-contract-adr]]'
  - '[[2026-07-25-archive-restore-contract-archive-path-reference]]'
  - '[[2026-07-25-archive-restore-contract-plan]]'
  - '[[2026-07-27-archive-restore-contract-p01-s01-baseline-review-audit]]'
  - '[[2026-07-27-archive-restore-contract-p01-s02-timestamp-review-audit]]'
  - '[[2026-07-27-archive-restore-contract-research]]'
  - '[[2026-07-27-archive-restore-contract-windows-qdrant-recovery-audit]]'
---

# `archive-restore-contract` feature index

Auto-generated index of all documents tagged with `#archive-restore-contract`.

## Documents

### adr

- `2026-07-25-archive-restore-contract-adr` - `archive-restore-contract` adr: `what a snapshot archive promises and who may read it back` | (**status:** `accepted`)

### audit

- `2026-07-27-archive-restore-contract-p01-s01-baseline-review-audit` - `archive-restore-contract` audit: `p01 s01 baseline review`
- `2026-07-27-archive-restore-contract-p01-s02-timestamp-review-audit` - `archive-restore-contract` audit: `p01 s02 timestamp review`
- `2026-07-27-archive-restore-contract-windows-qdrant-recovery-audit` - `archive-restore-contract` audit: `windows qdrant recovery`

### exec

- `2026-07-25-archive-restore-contract-P02-S06` - Add the archive reader that parses a snapshot manifest and refuses an absent, unparseable, or incomplete archive whole, mutating nothing
- `2026-07-25-archive-restore-contract-P02-S07` - Add the restore operation that derives the destination prefix from a named root through the existing root hash and recovers each recorded collection into it, reporting through the storage sync vocabulary
- `2026-07-25-archive-restore-contract-P02-S08` - Refuse a destination holding any existing collection, a non-canonical destination prefix, and any local-mode invocation, each naming its own reason
- `2026-07-25-archive-restore-contract-P02-S09` - Write the destination manifest entry from the archived per-collection identity and archived schema generation rather than current values, leaving an identity-less archive unverifiable
- `2026-07-25-archive-restore-contract-P02-S10` - Support a dry-run that returns the exact destination collection list and mutates nothing, matching the other storage operations
- `2026-07-25-archive-restore-contract-P02-S11` - Cover every refusal and the identity carry with guard tests, and prove each fails when its refusal is lifted or its carry reverted to current values
- `2026-07-25-archive-restore-contract-P03-S14` - Extend the maintenance inertness regression so no module reachable from the scheduled tick can reach the restore operation
- `2026-07-25-archive-restore-contract-P04-S15` - Add the restore verb to the storage command group as a thin adapter over the storage operation, carrying the group's dry-run preview, confirmation, and unreachable-server exit codes
- `2026-07-25-archive-restore-contract-P04-S16` - Emit exactly one structured envelope on every exit path of the verb in JSON mode, refusal and success alike
- `2026-07-25-archive-restore-contract-P04-S17` - Cover the verb's refusal exit codes and its single-envelope contract, including the JSON-without-yes refusal the other destructive verbs enforce
- `2026-07-25-archive-restore-contract-P01-S01` - Record the pre-change baseline of the storage suite so any later regression stays attributable
- `2026-07-25-archive-restore-contract-P01-S02` - Stamp an archive's own completion timestamp into its snapshot manifest so retention has an age that belongs to the archive
- `2026-07-25-archive-restore-contract-P01-S03` - `P01.S03` whole archive eviction
- `2026-07-25-archive-restore-contract-P01-S04` - `P01.S04` completed archive integrity gate
- `2026-07-25-archive-restore-contract-P01-S05` - `P01.S05` archive guard coverage
- `2026-07-25-archive-restore-contract-P01-summary` - `archive-restore-contract` `P01` summary
- `2026-07-25-archive-restore-contract-P03-S12` - Add the end-to-end round trip against a real supervised server: index a root, archive it, drop the namespace, restore under a fresh root, and assert the restored namespace answers a search with the results the original gave, with the Qdrant storage-dir environment variable pointed at a temp path

### plan

- `2026-07-25-archive-restore-contract-plan` - `archive-restore-contract` plan

### reference

- `2026-07-25-archive-restore-contract-archive-path-reference` - `archive-restore-contract` reference: `what the archive path writes, keeps, and offers a reader today`

### research

- `2026-07-27-archive-restore-contract-research` - `archive-restore-contract` research: `Archive restore evidence`
