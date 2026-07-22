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

# `large-index-resilience` audit: `run ledger`

## Scope

Reviewed commits `34fb194`, `98104c4`, and `fd56bbb` against the accepted
large-index resilience decision and W02.P05 S20-S21. The review covered the
production SQLite ledger and its real-file tests for transaction boundaries,
signature compatibility, structural and logical corruption, immutable
completion, row-wise iteration, compaction ownership, concurrent access, and
test integrity. Follow-up commits `5a45e96`, `7a97d85`, and `3746e99` were
re-reviewed as remediation landed.

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

### file-completeness-materialization | medium | File completeness materializes every segment

`file_complete` uses `fetchall` and constructs full ordinal collections even
though commit-unit segment counts are intentionally unknown until the final
segment. A pathological large file can make this authority proportional to all
of its segments. Replace this with bounded iteration or aggregate SQL that
proves one kind, one final marker, a contiguous ordinal range, and matching
count without materializing all rows.

### compaction-phase-authority | medium | Generic finalization can claim compaction before compaction runs

`advance_finalization` accepts `compacted` as the next phase while the
generation is still running, but the actual `compact` operation requires a
successful generation and is the operation that deletes obsolete rows. A
caller can therefore advance to `compacted` and finish successfully without
executing compaction. Reserve the compacted transition for `compact`, and
reject it through the generic external-phase method.

### corruption-and-concurrency-tests | medium | The test matrix omits logical corruption and concurrent writers

The real SQLite tests cover incompatible schema versions, a file that is not
SQLite, and—after `3746e99`—mismatched signature evidence. They do not cover a
structurally valid database with missing tables, malformed enum or JSON fields,
two ledger instances operating concurrently, or a forced mid-transaction
rollback. Add real thread or process contention, rollback, partial-schema, and
malformed-row cases without mocks or patches.

### test-integrity | low | Existing tests use production behavior and real SQLite

The reviewed test module imports production types directly and uses real
temporary SQLite databases. It contains no fake, mock, stub, patch,
monkeypatch, skip, or expected-failure shortcut, and its fixture helpers only
construct valid inputs rather than mirroring ledger decisions.

## Recommendations

All high-severity checkpoint-integrity findings were resolved by `5a45e96`,
`7a97d85`, and `3746e99`. Before W02.P06 depends on concurrent or long-lived
ledger readers, address iterator/write contention, bounded file-completeness
evaluation, exclusive compact-phase authority, and typed partial-schema and
malformed-row handling. Add the corresponding real concurrency, rollback, and
corruption tests.

The final focused review run passed all five ledger tests in 1.31 seconds.
Ruff and Ty reported no finding in the reviewed production and test files.
