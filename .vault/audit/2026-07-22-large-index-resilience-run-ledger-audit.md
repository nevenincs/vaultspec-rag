---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:84628ee8ceb7a2b141cb1d39738bf154e0361043c9706a3dc2097b75fbbcb828'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` audit: `run ledger`

## Scope

Reviewed commits `34fb194`, `98104c4`, and `fd56bbb` against the accepted
large-index resilience decision and W02.P05 S20-S21. The review covered the
production SQLite ledger and its real-file tests for transaction boundaries,
signature compatibility, structural and logical corruption, immutable
completion, row-wise iteration, compaction ownership, concurrent access, and
test integrity. Follow-up commits `5a45e96`, `7a97d85`, and `3746e99` were
re-reviewed as remediation landed. Commit `ec6fa09` was then reviewed for the
four remaining medium-severity remediations and the bounded atomic metadata
publication helper. Commit `19e23de` was reviewed as the final publication-temp
ownership remediation.

## Findings

### publication-evidence | high | File outcomes remained mutable after publication began

The original `record_file_state` implementation checked only terminal state,
so file evidence could change after metadata publication and before successful
completion. Commit `5a45e96` resolves this by freezing file-state mutation when
finalization leaves `ingesting`, with real regression coverage.

### indexed-evidence | high | Indexed state initially required no confirmed storage units

The original ledger accepted a converged indexed outcome without any matching
commit unit. Commit `7a97d85` resolves the zero-evidence case transactionally by
requiring a complete storage-confirmed segment sequence before indexed state is
recorded.

### terminal-resume | high | Failed and interrupted generations abandoned confirmed work

The original `start_generation` resumed only running rows while failure,
cancellation, and incomplete rebuild states were immutable. Commit `7a97d85`
resolves this by reactivating a compatible non-success generation in place and
retaining its confirmed units and destructive intent.

### compaction-ownership | high | Compaction deleted terminal generations from other domains

The original compaction query deleted every terminal generation except the
retained identifier. Commit `7a97d85` scopes deletion to the retained source
type and collection and verifies that another published content domain remains
intact.

### indexed-membership-freeze | high | A later segment can invalidate an indexed path

After a path has one complete segment sequence and an indexed file state, the
ledger still accepts another segment or another final marker for that path.
`file_complete` then becomes false while the converged indexed state remains
eligible for publication. Commit-unit membership must freeze once indexed, and
the ledger must reject multiple final markers or any segment after the final
ordinal.

Commit `3746e99` resolves this finding by enforcing contiguous insertion,
rejecting additions after the file-end unit, and freezing unit membership once
the path is indexed. The same transaction also enforces generation-wide point
identity uniqueness.

### indexed-digest-binding | high | Indexed hashes are not bound to committed source evidence

The completeness check does not compare `FileState.content_hash` with the
upsert units' `source_digest`. A complete sequence for one digest can therefore
be certified as indexed under another digest, allowing metadata to describe
different bytes than storage. Indexed state must require one complete upsert
sequence whose digest equals the state hash.

Commit `3746e99` resolves this finding by returning completion evidence with the
committed digest and requiring exact equality before indexed state is accepted.

### logical-signature-corruption | high | Stored signature JSON is trusted independently of its fingerprint

SQLite `quick_check` cannot detect valid-row semantic tampering. Resume compares
the requested fingerprint only with the stored fingerprint column, then builds
the returned signature from independently stored JSON without recomputing or
comparing it. A row with changed signature JSON and its old fingerprint can
resume incompatible work. Reconstruct and validate the canonical signature and
raise a typed corruption or compatibility error before resume.

Commit `3746e99` resolves this finding by reconstructing and rehashing the
canonical signature before returning a generation. Its real SQLite regression
alters valid signature JSON and verifies typed corruption refusal.

### iterator-write-contention | medium | Row-wise generators retain a read transaction while yielding

`iter_units`, `iter_point_ids`, and `iter_file_states` bound Python row batches,
but keep one SQLite connection and cursor open across caller yields. Without
write-ahead logging, a slow or partially consumed iterator can retain a read
lock and make a concurrent writer exhaust the five-second busy timeout. Use a
reader/writer-safe journal mode or keyset pagination that releases the read
transaction between bounded batches, and verify concurrent reader/writer
progress with separate real connections.

Commit `ec6fa09` resolves this finding with keyset pagination that closes each
bounded read connection before yielding its batch. The real SQLite regression
pauses a one-row iterator, commits through another connection, and then proves
iteration continues through both the original and newly committed rows.

### file-completeness-materialization | medium | File completeness materializes every segment

`file_complete` uses `fetchall` and constructs full ordinal collections even
though commit-unit segment counts are intentionally unknown until the final
segment. A pathological large file can make this authority proportional to all
of its segments. Replace this with bounded iteration or aggregate SQL that
proves one kind, one final marker, a contiguous ordinal range, and matching
count without materializing all rows.

Commit `ec6fa09` resolves this finding with grouped SQL evidence for count,
ordinal bounds and sum, and the unique final marker. The materialized result is
bounded by mutation kind and digest rather than segment count.

### compaction-phase-authority | medium | Generic finalization can claim compaction before compaction runs

`advance_finalization` accepts `compacted` as the next phase while the
generation is still running, but the actual `compact` operation requires a
successful generation and is the operation that deletes obsolete rows. A
caller can therefore advance to `compacted` and finish successfully without
executing compaction. Reserve the compacted transition for `compact`, and
reject it through the generic external-phase method.

Commit `ec6fa09` resolves this finding by rejecting `compacted` in
`advance_finalization`; only the successful-generation `compact` transaction
can now record that phase, with direct regression coverage.

### corruption-and-concurrency-tests | medium | The test matrix omits logical corruption and concurrent writers

The real SQLite tests cover incompatible schema versions, a file that is not
SQLite, and—after `3746e99`—mismatched signature evidence. They do not cover a
structurally valid database with missing tables, malformed enum or JSON fields,
two ledger instances operating concurrently, or a forced mid-transaction
rollback. Add real thread or process contention, rollback, partial-schema, and
malformed-row cases without mocks or patches.

Commit `ec6fa09` resolves the release-blocking portion of this finding. Startup
now rejects missing tables and columns with a typed compatibility error, row
conversion wraps malformed generation, file-state, and commit-unit values as
typed corruption, and real SQLite coverage exercises a missing table and a
malformed generation enum. The paused iterator test also proves writer progress
through a distinct connection. A forced mid-transaction rollback remains a
useful low-severity expansion because transaction rollback is already exercised
by SQLite's context-manager boundary rather than custom rollback logic.

### publication-temp-ownership | medium | Concurrent publishers share one temporary file

`publish_meta_from_file_states` streams bounded, ordered, converged ledger rows,
flushes and synchronizes the completed file, and preserves the prior sidecar
when row validation fails. Its temporary pathname is nevertheless fixed per
target. Two publishers can therefore open and truncate the same temporary file.
On Windows a real overlapping-call probe made one publisher fail with a sharing
violation; on platforms that permit replacement of an open file, one handle can
continue writing the inode after it becomes the published target, exposing a
partially written sidecar and breaking the atomic replacement guarantee. Give
each invocation a unique temporary file in the target directory, replace only
that owned file, and add a real overlapping-publisher regression.

Commit `19e23de` resolves this finding. Each invocation now creates and owns a
unique temporary file in the target directory, writes through its original file
descriptor, and replaces the target only after synchronization and close. The
real two-thread regression overlaps publication after both temporary files are
open, requires both publishers to complete, proves the resulting sidecar
contains one whole generation, and verifies that no temporary file remains.

### test-integrity | low | Existing tests use production behavior and real SQLite

The reviewed test module imports production types directly and uses real
temporary SQLite databases and the production metadata publisher. It contains
no fake, mock, stub, patch, monkeypatch, skip, or expected-failure shortcut, and
its fixture helpers only construct valid inputs rather than mirroring ledger
decisions.

## Recommendations

All high- and medium-severity ledger and metadata-publication findings were
resolved by `5a45e96`, `7a97d85`, `3746e99`, `ec6fa09`, and `19e23de`. A forced
mid-transaction rollback and additional malformed file-state and commit-unit
rows remain lower-severity test-matrix expansions.

The final focused review run passed all eight ledger tests in 1.47 seconds.
Ruff and Ty reported no finding in the reviewed production and test files. The
real overlapping metadata-publication regression passed and left no temporary
files behind.
