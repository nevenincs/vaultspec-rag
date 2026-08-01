---
tags:
  - '#adr'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:8ca27db1a7a5341f551503446f4c9f4c7ae622288cf0dc632fda76a2bc6a21de'
related:
  - '[[2026-07-25-archive-restore-contract-archive-path-reference]]'
  - '[[2026-07-14-storage-autoprune-safety-adr]]'
  - '[[2026-07-25-storage-conformance-adr]]'
  - '[[2026-07-14-storage-namespace-hygiene-adr]]'
  - '[[2026-07-21-storage-prealloc-reclaim-adr]]'
  - '[[2026-07-27-archive-restore-contract-research]]'
---

# `archive-restore-contract` adr: `what a snapshot archive promises and who may read it back` | (**status:** `accepted`)

## Problem Statement

Automated reclamation destroys point-bearing namespaces. `archive_prefix` in
`src/vaultspec_rag/storage_ops.py` snapshots every collection of the prefix
first and raises on any failure, and `run_maintenance_cycle` refuses the drop
when it does. That archive is the entire justification for letting an unattended
cycle destroy semantic data: `2026-07-14-storage-autoprune-safety-adr` chose
archive-then-drop over drop-without-archive because it keeps a recovery path,
and rejected the middle option as failing the data-safety mandate.

No such path exists. Nothing in the package reads an archive back. `sweep_archive`
is the archive tree's only other consumer and it only deletes. The one test that
touches `archive_prefix` asserts on the JSON manifest and on file existence,
never on the `.snapshot` artifact. The accepted decision therefore rests on a
premise this code has never tested in either direction - that these files can
reconstitute a namespace.

A second problem sits underneath it. The archive tree is not structurally
coherent today, so a restore built over it would fail on real archives.
`sweep_archive` enumerates and deletes individual files rather than archives, so
the byte cap evicts oldest-first across the whole tree and can remove a
namespace's snapshots while leaving its manifest - a record describing data that
is gone. The copied document-metadata evidence carries the source file's
modification time through `copy2`, so retention can expire it on a clock
unrelated to the archive's own age. What retention leaves behind decides whether
there is anything to restore, so it is decided here rather than after.

A decision is needed now because the surface this premise authorises is
unattended, and every cycle that archives-then-drops spends real data against it.

## Considerations

- `2026-07-14-storage-autoprune-safety-adr` makes recoverability the stated
  reason the data tier may destroy at all; without it, the chosen option
  collapses into the one that record rejected.
- The data is derived. A namespace is embeddings of a root's files, and that
  same record names reindexing as the remedy with the archive covering the
  window in between. That bounds what a restore must be worth, not whether it
  must exist.
- A namespace reaches the archive path only once classified `orphaned` - its
  root continuously absent for the data grace window - and the live-indexing
  race was closed separately. Snapshot consistency under concurrent writes is
  therefore outside this path's reach; this record neither establishes that
  Qdrant property nor depends on it.
- The prefix is a one-way hash of the resolved root path (`root_collection_prefix`
  in `src/vaultspec_rag/store.py`), so a restore under a different root does not
  reuse the collection names the archive was taken from.
- `2026-07-25-storage-conformance-adr` already settled the adjacent case: a
  namespace copy carries the source identity rather than being restamped,
  because copying shape while dropping provenance manufactures conformance that
  was never established.
- That record also supplies the three-verdict vocabulary - conforming,
  nonconforming, unverifiable - in which `unverifiable` is the accurate answer
  to absent evidence and never authorises destruction.
- Its step stamping identity into the snapshot manifest is authored and still
  open, so a restore landing today reads a manifest carrying prefix, root,
  schema generation, collection names, point counts and metadata files, and no
  identity.
- The pinned client exposes recovery of a collection from a location on the
  server host's own filesystem. The daemon supervises Qdrant on that host and
  the archive dir is a sibling of its storage dir, so the mechanism is already
  available and needs no new dependency.
- The storage CLI verbs open a client against the managed server directly rather
  than routing through the daemon (`src/vaultspec_rag/cli/_service_storage.py`),
  and `migrate_collections` already establishes a copy verb that skips rather
  than overwrites a pre-existing target.
- Maintenance is read-and-drop and lifecycle-inert, so a stage that creates
  collections does not belong on the scheduled tick.
- The real-server integration harness that already exercises `archive_prefix`
  end to end exists in `src/vaultspec_rag/tests/integration/test_document_store.py`,
  so a round trip against a supervised Qdrant costs a test, not a rig.

## Considered options

**Ship nothing; stop auto-deleting point-bearing namespaces.** The strongest
challenger. It withdraws the destruction the unproven archive authorises, and
the autoprune record's own measurement was that the entire reclaim it was
written for was zero-point namespaces. Rejected: point-bearing dangling
namespaces are the large ones, a deleted worktree leaves multiple GB of them,
and withdrawing the tier trades a demonstrated disk-exhaustion hazard for an
undemonstrated data-loss one. Its constraint is adopted in narrowed form.

**Prove the archive by test only, ship no verb.** Cheap, and it answers the
literal complaint. Rejected: it leaves an operator holding an artifact proven
readable and no way to read it, and a capability only tests can reach proves
nothing about production.

**Verify each archive by restoring it before the drop.** The strongest form of
the guarantee - every deletion backed by a restore that actually ran. Rejected
on its trigger condition: it inflates peak disk during the cycle whose reason
for existing is disk exhaustion, and it makes the scheduled tick a
collection-creating actor against maintenance being read-and-drop.

**Restore in place, over the prefix the archive came from.** Rejected: the
prefix survives the root's return, so in-place can land stale vectors on a
namespace the operator has already reindexed. Silently replacing current data
with older data is a worse failure than the one being fixed.

**Restore as a migration, converting an old schema generation forward.**
Rejected: the governing schema decision chose clean reindex over in-place
migration and the conformance record restates it. A restore that converts
becomes the migration engine this project declined to build.

**An operator verb restoring to a named destination and refusing every
ambiguity, over an archive proven readable once end to end and vouched for
individually at write time.** Chosen.

## Constraints

- Server mode only. Snapshots are a server facility, the storage manifest is
  server-mode-only, and a local store has one namespace and no prefix.
- Never reachable from the scheduled maintenance path. Restore creates
  collections; maintenance stays read-and-drop and lifecycle-inert, and the
  import-graph regression that keeps maintenance out of the lifecycle helpers
  gains the reverse direction.
- No new dependency and no new archive format. The mechanism is the pinned
  client's recovery-from-location call against the supervised server.
- No migration engine, per the governing schema decision.
- No change to the grace machinery, the classifier, or `delete_prefix`.
  Automatic deletion keeps requiring classification and a persisted continuous
  grace window, any live or unverifiable observation keeps resetting the clock,
  and an unknown or unverifiable namespace is still never auto-touched.
- The identity field this record wants in the snapshot manifest is authored
  under the storage-conformance plan and not yet closed. Restore must behave
  correctly against archives carrying no identity, which is every archive
  written before that step lands.
- Any test writing the identity sidecar or taking the machine lock points the
  Qdrant storage-dir environment variable at a temp path.

## Implementation

**D1 - The archive is an atomic unit.** Retention and the byte cap operate on
whole archive directories, never on files inside them, and an archive's age is
the age of its own manifest rather than of whichever file happens to be oldest.
Eviction removes the directory entire. A partial archive then cannot exist, so
no reader ever has to decide what half an archive means.

**D2 - Each archive is vouched for at write time, before the drop it
authorises.** After the snapshots are moved and the manifest written,
`archive_prefix` re-reads what it produced: every collection it recorded has its
snapshot file present and non-empty, and the point counts in the manifest are
the counts the live collections still report. A failure raises exactly as every
other archive failure already does, so the caller refuses the drop and the
namespace survives to the next cycle with its grace clock intact. This is a
stat-and-count check - it creates nothing, reads no vectors, and adds no
meaningful time or disk to a cycle running under disk pressure. It catches the
failure class that actually exists here: a snapshot the server reported making
that is missing, truncated, or landed elsewhere. It deliberately does not
establish that Qdrant can parse the file, which is a property of the format
rather than of an instance.

**D3 - The format is proven once, end to end, against a real supervised
server.** An integration test indexes a small root, archives it, drops the
namespace, restores it under a fresh root, and asserts the restored namespace
answers a search with the results the original gave. The project's guard
obligation governs it: the proof is observed failing for its intended reason -
a corrupted snapshot body must make the restore fail rather than pass quietly -
and both directions are recorded. This is the only place the readability claim
is ever established.

**D4 - Restore is an operator verb and never automatic.** `server storage restore` takes an archive directory and a destination root, derives the
destination prefix from that root through the existing hash, and recovers each
collection the manifest names into the destination namespace. It reports through
the same sync vocabulary as the other storage verbs, offers the same dry-run
preview returning the exact target list and mutating nothing, and emits one
structured envelope on every exit path in JSON mode. The behaviour lives with
the other storage operations in `src/vaultspec_rag/storage_ops.py`; the CLI
adapts to it.

**D5 - It restores to a namespace, never over one.** Every destination
collection must be absent. A destination with any collection present is refused
whole, with no force flag, because the case that matters is an operator who has
already reindexed the returned root and would be trading current vectors for
older ones. Naming the same root the archive came from is legitimate and yields
the same prefix; it is refused only when that namespace is currently populated.
The canonical-prefix gate `delete_prefix` enforces applies unchanged.

**D6 - The restored namespace carries the archive's identity, never the running
configuration's.** Whatever produced the archived vectors produced them, and a
restore relabelling them as current manufactures the conformance the copy path
was already forbidden to manufacture. The manifest entry written for the
destination carries the archived per-collection identity and the archived schema
generation verbatim. An archive carrying no identity restores to a namespace
reported `unverifiable`, which is the accurate answer and never authorises
destruction.

**D7 - A mismatch degrades; it never converts and never blocks.** Because
identity is carried rather than restamped, a restored namespace built by a
different model at matching geometry presents as `nonconforming` through the
existing degradation surface with the rebuild remedy already paired to it, and a
geometry disagreement refuses at the existing ensure step as it does for any
collection. Restore asserts nothing about conformance itself: it delivers an
honest record and leaves the judgement to the machinery that already owns it.

**D8 - What it refuses outright.** An archive whose manifest is absent or
unparseable. An archive naming a collection whose snapshot file is missing -
refused whole, never restored partially, because a half-restored namespace looks
complete to search. A destination holding any existing collection. A
non-canonical destination prefix. Any invocation in local mode. Each refusal
names its reason and mutates nothing.

**D9 - The automatic destroyer's reach narrows to what it can vouch for.** After
D2, a point-bearing namespace is destroyed automatically only when it is
orphaned, attributable, past its continuous grace window, and its archive
completed and passed the integrity check. This is where the
constrain-destruction option is adopted: the tier is not withdrawn, but it no
longer proceeds on the word of a write nobody read.

## Rationale

The knockout is that the autoprune record already decided this. It chose
archive-then-drop precisely because that option keeps a recovery path, and
rejected dropping without an archive as failing the data-safety mandate. If
nobody can walk the path, the two options are one option under two names, and
what actually ships is the branch that record rejected. Building the verb adds
no promise; it makes the existing one true. Declining to build it would require
reopening that record and re-deciding the data tier - a larger change than the
verb, and one the measured waste profile does not call for.

The three-way split follows from what each mechanism can establish. Readability
of the format is one fact about Qdrant and this manifest, true or false once,
and a single real round trip settles it - which is why D3 is a test rather than
a runtime stage. Integrity of one archive is a different fact, true or false per
instance, and cheap enough to check every time, which is why D2 runs inline.
Proving an instance by restoring it establishes the same fact D2 covers at
ruinous cost: it doubles peak disk in the cycle whose trigger is disk
exhaustion, and puts collection creation on a tick that must stay read-and-drop.
Paying the expensive mechanism for the cheap one's fact buys nothing.

D6 is why this record needs no mismatch policy of its own. The conformance
record settled the identical question for the copy path on reasoning that
transfers without amendment - provenance travels with the vectors or it is
fabricated - and carrying identity turns every identity question a restore could
raise into a verdict that machinery already renders and already surfaces with a
remedy. Deciding mismatch here instead would build a second comparator against
the one that exists.

D1 is not housekeeping. A restore over the current sweep would be a verb that
fails on real archives, because the byte cap can leave a manifest describing
snapshots it has already deleted. Shipping recovery without fixing what
retention leaves behind would deliver a path that works only on archives young
enough never to have needed it.

## Consequences

**Gains.** The premise the data tier rests on stops being a presumption: the
format is established once against a real server, each archive is vouched for
before the deletion it authorises, and an operator who needs one can use it. A
restored namespace lands with honest provenance and inherits the existing
degradation surface rather than growing a second one.

**Honest difficulties.** D3 establishes the format for the snapshots this code
writes against the pinned server; it is not a standing guarantee across a Qdrant
upgrade, and a version bump is exactly where it would quietly stop holding. D2
raises the cost of a bad archive from a silent bad file to a refused
reclamation, which is the correct trade but means a host with a failing disk
reclaims less and reports more. D1 coarsens retention: archives expire whole, so
a large one is evicted as a unit and the byte cap becomes less precise. Every
archive written before the identity field lands restores to an `unverifiable`
namespace, and the surfaces must make that read as an unknown rather than as
damage. A restore of a large namespace is a long, disk-hungry operation an
operator can start with little warning.

**Pathways opened.** A verified round trip is the precondition for anything else
that would trade data for a snapshot: a pre-rebuild safety copy, an
operator-initiated archive of a live root, a move between hosts. The atomic
archive unit is also what an inventory verb would enumerate, if the archive tree
ever needs one.

**Pitfalls to avoid.** Letting restore acquire a force flag - the refusal on a
populated destination is the whole safety property. Letting it convert a schema
generation, which turns it into the migration engine this project declined to
build. Reaching it from the maintenance tick. Restamping identity onto the
destination. Restoring an archive partially. Treating D2's integrity check as
evidence that the snapshot parses.
