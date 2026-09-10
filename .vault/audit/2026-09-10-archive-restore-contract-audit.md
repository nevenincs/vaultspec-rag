---
tags:
  - '#audit'
  - '#archive-restore-contract'
date: '2026-09-10'
modified: '2026-09-10'
body_schema: 'body-v2'
body_hash: 'sha256:238612202991ad65a78e6e0f872324666112eb7d7d8a3dc862acd4bbb5564172'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
  - "[[2026-07-25-archive-restore-contract-adr]]"
---

# `archive-restore-contract` audit: `final implementation review`

## Scope

Reviewed the delivered feature on `main` HEAD against every decision the
authorizing record makes (D1-D9), plus the outstanding closeout Steps: the
whole-archive atomic sweep and write-time integrity gate, the restore
primitive's refusals and identity carry, the real round trip and its
corruption counterpart, the maintenance-inertness guard, and the operator
CLI adapter. The archive and restore implementation moved modules during an
unrelated later refactor (`storage_ops.py` split into `storage_archive.py`,
`storage_restore.py`, and sibling modules); this review reads the current
locations, not the plan's original citations.

## Findings

### atomic-archive-unit | low | whole-archive eviction and write-time integrity gate match D1/D2

`archive_prefix` (`src/vaultspec_rag/storage_archive.py:114`) snapshots every
collection of a prefix, moves each snapshot into the archive directory, and
raises on the first failure before any drop is authorised, matching D1/D2.
`storage_reclamation.py:565` calls it inside a `try` that redecides the
namespace `failed` rather than dropping on any transport failure, and
re-counts live points after the archive to catch a write landing mid-copy
(`storage_reclamation.py:581-595`), consistent with D9's "vouched for before
the drop" requirement. No gap found.

### restore-refusals | low | D5/D8 refusals and D6 identity carry are implemented as decided

`restore_archive` (`src/vaultspec_rag/storage_restore.py:388`) refuses local
mode, a non-canonical destination prefix, an archive collection colliding
with the destination prefix itself, and any destination already holding a
collection, each with its own named reason and no force flag, matching D5
and D8. `_refuse_unnamed_snapshots` additionally refuses an archive whose
directory holds snapshot artifacts its manifest does not name, closing the
half-restore failure mode D8 calls out. The destination manifest entry is
written from the archived identity and schema generation rather than the
running configuration (`storage_restore.py:444-457`, `record_restored_archive`
in `storage_manifest.py`), matching D6. No gap found.

### round-trip-and-corruption-proof | low | D3's real-server proof and its guard exist and cover both directions

`src/vaultspec_rag/tests/integration/test_storage_restore_integration.py`
carries the real-server proof D3 requires:
`test_restored_namespace_answers_the_search_the_original_answered` indexes,
archives, drops, and restores a namespace and asserts the restored
collection answers the same fixed query with the same ranked bodies the
original gave, and `test_restore_rolls_back_after_a_real_corrupt_snapshot_failure`
corrupts one archived snapshot's bytes and asserts the restore raises
(POSIX) or refuses with a named reason (Windows) rather than completing,
leaving neither collection created. Together these are the "both directions"
D3 and the guard-test obligation require: the positive path (this plan's
prior `P03.S12`) and the negative path this closeout resolves as already
present under the renamed file. No gap found.

### windows-recovery-limitation | low | a real upstream limitation is handled as an honest refusal, not silently

An earlier review in this feature's history
(`2026-07-27-archive-restore-contract-windows-qdrant-recovery-audit.md`)
found that the pinned Windows Qdrant server cannot complete a real snapshot
recovery due to a filesystem access error inside the server's own recovery
path. The delivered code does not paper over this: every restore attempt on
`sys.platform == "win32"` returns a typed refusal
(`WINDOWS_SERVER_ARCHIVE_RESTORE_UNSUPPORTED_REASON`) rather than attempting
and silently failing, and the round-trip and corruption tests both assert
that refusal branch explicitly. This is the honest difficulty the ADR's
Consequences section already anticipates for a pinned-server dependency, not
an unresolved defect. No gap found.

### maintenance-inertness | low | the scheduled tick still cannot reach restore

`src/vaultspec_rag/tests/test_adr_regression.py` asserts, by import-graph
scan, that no module reachable from the maintenance cycle imports
`storage_restore`, references `restore_archive`, or names `RestoreRequest`,
and that the assertion is mutation-proved against a fixture naming the
operation. No gap found.

## Recommendations

None. Every decision in the authorizing record (D1-D9) is implemented and
covered by a real-server or import-graph test; the one open item this
review surfaces is operational rather than architectural - the Windows
pinned-server recovery limitation already carries its own typed refusal and
needs no further code change from this feature.
