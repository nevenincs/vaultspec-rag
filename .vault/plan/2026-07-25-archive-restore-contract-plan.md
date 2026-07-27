---
tags:
  - '#plan'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-07-27'
tier: L2
related:
  - '[[2026-07-25-archive-restore-contract-adr]]'
  - '[[2026-07-25-archive-restore-contract-archive-path-reference]]'
  - '[[2026-07-27-archive-restore-contract-research]]'
---

# `archive-restore-contract` plan

## Description

Implements `2026-07-25-archive-restore-contract-adr` end to end. That record
decided that a restore ships as an operator verb, that it restores to a named
destination and never over a populated one, that it carries the archived
provenance rather than restamping it, and that the archive's readability is
established once end to end while each individual archive is vouched for at
write time before the deletion it authorises.

The ordering is forced by two dependencies. Nothing can be restored reliably
until an archive is a coherent whole, because today's retention sweep deletes
files rather than archives and can leave a manifest describing snapshots it has
already removed; `P01` therefore fixes what retention leaves behind and adds the
write-time integrity gate before any reader exists. And the round trip in `P03`
cannot be written until the primitive it exercises exists, so `P02` precedes it.
`P04` is the thin adapter and carries no behaviour of its own.

Two boundaries apply throughout. The scheduled maintenance path stays
read-and-drop and lifecycle-inert: no module reachable from the tick may reach
the restore operation, and `P03` regression-guards that direction. And restore
never converts a schema generation - the governing schema decision chose clean
reindex over in-place migration, and a restore that converts becomes the
migration engine this project declined to build.

The identity field `P02` reads from the snapshot manifest is authored under the
storage-conformance plan and still open there. This plan does not duplicate that
step; it requires only that restore behaves correctly when the field is absent,
which is the state of every archive written so far.

Almost every step here adds a guard or a negative assertion, so the project's
guard-test obligation governs them: each is observed failing for its intended
reason before it is trusted, and both directions are recorded in that step's
record.

## Steps

### Phase `P01` - make an archive an atomic, vouched-for unit

Stops retention from shredding an archive into a partial one, and stops a namespace being destroyed on the word of an archive nobody re-read.

- [x] `P01.S01` - Record the pre-change baseline of the storage suite so any later regression stays attributable; `src/vaultspec_rag/tests/test_storage_ops.py`.
- [x] `P01.S02` - Stamp an archive's own completion timestamp into its snapshot manifest so retention has an age that belongs to the archive; `src/vaultspec_rag/storage_manifest.py`.
- [x] `P01.S03` - Expire and evict whole archive directories on that stamp instead of individual files on their own modification times, so the byte cap can never leave a manifest describing deleted snapshots; `src/vaultspec_rag/storage_ops.py`.
- [x] `P01.S04` - Re-read a completed archive before returning it, asserting every recorded snapshot file exists non-empty and every recorded point count still matches the live collection, and raise as every other archive failure already does; `src/vaultspec_rag/storage_ops.py`.
- [x] `P01.S05` - Cover the whole-archive sweep and the integrity gate with guard tests, and prove each fails when its check is removed; `src/vaultspec_rag/tests/test_storage_ops.py`.

### Phase `P02` - build the restore primitive in the storage domain

Reads an archive back into a named destination namespace, carrying the archived provenance and refusing every ambiguity rather than guessing at one.

- [ ] `P02.S06` - Add the archive reader that parses a snapshot manifest and refuses an absent, unparseable, or incomplete archive whole, mutating nothing; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P02.S07` - Add the restore operation that derives the destination prefix from a named root through the existing root hash and recovers each recorded collection into it, reporting through the storage sync vocabulary; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P02.S08` - Refuse a destination holding any existing collection, a non-canonical destination prefix, and any local-mode invocation, each naming its own reason; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P02.S09` - Write the destination manifest entry from the archived per-collection identity and archived schema generation rather than current values, leaving an identity-less archive unverifiable; `src/vaultspec_rag/storage_manifest.py`.
- [ ] `P02.S10` - Support a dry-run that returns the exact destination collection list and mutates nothing, matching the other storage operations; `src/vaultspec_rag/storage_ops.py`.
- [ ] `P02.S11` - Cover every refusal and the identity carry with guard tests, and prove each fails when its refusal is lifted or its carry reverted to current values; `src/vaultspec_rag/tests/test_storage_ops.py`.

### Phase `P03` - prove the round trip and keep it off the automatic path

Establishes end to end against a real supervised server that an archive reconstitutes a searchable namespace, and regression-guards restore out of scheduled maintenance.

- [ ] `P03.S12` - Add the end-to-end round trip against a real supervised server: index a root, archive it, drop the namespace, restore under a fresh root, and assert the restored namespace answers a search with the results the original gave, with the Qdrant storage-dir environment variable pointed at a temp path; `src/vaultspec_rag/tests/integration/test_storage_archive_restore.py`.
- [ ] `P03.S13` - Prove that round trip can fail by corrupting the archived snapshot body and observing the restore refuse rather than pass quietly, and record both directions; `src/vaultspec_rag/tests/integration/test_storage_archive_restore.py`.
- [ ] `P03.S14` - Extend the maintenance inertness regression so no module reachable from the scheduled tick can reach the restore operation; `src/vaultspec_rag/tests/test_adr_regression.py`.

### Phase `P04` - adapt the operator surface

Exposes the primitive as a storage verb carrying the group's existing preview, vocabulary, and structured-envelope contract.

- [ ] `P04.S15` - Add the restore verb to the storage command group as a thin adapter over the storage operation, carrying the group's dry-run preview, confirmation, and unreachable-server exit codes; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `P04.S16` - Emit exactly one structured envelope on every exit path of the verb in JSON mode, refusal and success alike; `src/vaultspec_rag/cli/_service_storage.py`.
- [ ] `P04.S17` - Cover the verb's refusal exit codes and its single-envelope contract, including the JSON-without-yes refusal the other destructive verbs enforce; `src/vaultspec_rag/tests/test_storage_adversarial.py`.

### Phase `P05` - close out

Runs the gates, records the guard failure proofs, and reviews the delivered feature against the authorizing decision.

- [ ] `P05.S18` - Run the full suite, lint, type, and citation gates and reconcile the result against the recorded baseline; `src/vaultspec_rag/`.
- [ ] `P05.S19` - Review the delivered feature against the authorizing decision and record the audit; `src/vaultspec_rag/`.

## Parallelization

`P01` is a hard prerequisite for `P02` and `P03`: a reader written against a
tree retention can shred file-by-file would be tested only on archives young
enough never to have needed it. Within `P01`, the manifest stamp and the sweep
change are sequential (`S02` before `S03`), while the write-time integrity gate
(`S04`) touches a different function and may proceed alongside them.

`P02` is strictly sequential up to `S10`; each step narrows what the previous
one accepts.

`P03` and `P04` share no code and may run in parallel once `P02` lands. `P03`
touches the integration suite and the inertness regression; `P04` touches only
the CLI adapter. Within `P03`, the inertness extension (`S14`) has no dependency
on the round trip and may run first.

`P05` is the closeout and runs last.

## Verification

The plan is complete when every Step is closed and each criterion below holds.

- An archive whose total pushes the tree over its byte cap is evicted whole:
  after the sweep, no archive directory contains a manifest without the snapshot
  files it names; asserted by test.
- An archive expires on its own recorded completion stamp, not on the
  modification time of a copied metadata file that predates it; asserted by a
  test whose copied file carries a deliberately old modification time.
- An archive whose snapshot file is truncated or removed after the move causes
  `archive_prefix` to raise, and the maintenance cycle reports the namespace
  failed rather than removed; the namespace still exists after the cycle and its
  grace stamp is unchanged.
- A namespace archived, dropped, and restored under a fresh root answers a
  search with the results the original gave, against a real supervised server.
- Corrupting the archived snapshot body makes that round trip fail on its
  restore assertion rather than pass; recorded in the step record with the
  restored green run.
- A restore into a destination holding any existing collection is refused with
  its own reason, mutates nothing, and exits non-zero; there is no flag that
  overrides it.
- A restore of an archive naming a collection whose snapshot file is missing is
  refused whole; no destination collection is created.
- A restored namespace's manifest entry carries the archived per-collection
  identity and archived schema generation verbatim; a restore from an
  identity-less archive reports `unverifiable` and never becomes a reclamation
  candidate. Asserted by test.
- No module reachable from the scheduled maintenance tick imports or names the
  restore operation; asserted by the inertness regression.
- The restore verb emits exactly one structured envelope on every `--json` exit
  path, success and refusal alike.
- Every guard added by this plan has a recorded failure proof in its Step
  Record: the mutation applied, the observed failure and its reason, and the
  restored green run.
- The full suite passes at or above the baseline recorded in `P01.S01`, and
  lint, type, and citation gates are clean.
