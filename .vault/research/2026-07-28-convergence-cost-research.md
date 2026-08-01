---
tags:
  - '#research'
  - '#convergence-cost'
date: '2026-07-28'
modified: '2026-07-28'
body_schema: 'body-v1'
body_hash: 'sha256:ae8618d4a7110db60896abde7355949e5b714874ee11fe99d3fd89232df3816e'
related:
  - "[[2026-03-07-blake2b-file-hashing-adr]]"
---

# `convergence-cost` research: `Why a menial watcher event costs a full-tree rehash`

Operators observe minute-long full-worktree hashing after trivial file changes on large
projects (tens of thousands of files). The question: does the watcher pipeline actually
rehash the whole tree on a change signal, and if so, where and why. Conclusion: the scoped
incremental path works as designed, but the retry/convergence state escalates to unscoped
mode on several common, benign events, and the unscoped pass proves files unchanged by
reading and rehashing every byte of every admitted file - there is no stat-evidence gate
anywhere in the indexer.

## Findings

### The scoped incremental path is proportional to the change set

The watcher hands exact changed paths through `submit_watcher_job` into
`incremental_index(changed_paths=...)`; the scoped branch hashes only those paths and
diffs them against the persisted hash sidecar (`src/vaultspec_rag/watcher_execution.py:74`,
`src/vaultspec_rag/indexer/_codebase_indexer.py:1302`). When the watcher is healthy, a
menial change costs O(changed files). The sidecar maps relative path to blake2b-512 hex
(`src/vaultspec_rag/indexer/_code_meta.py:163`).

### The unscoped pass rehashes every admitted file with no stat gate

`_scan_and_hash_incremental_inputs` feeds the full scan into `_hash_changed_paths`, which
opens and digests every file (`src/vaultspec_rag/indexer/_codebase_indexer.py:613`,
`src/vaultspec_rag/indexer/_codebase_indexer.py:1267`). The sidecar stores only hashes,
never `(size, mtime_ns)`, so proving a file unchanged costs reading all of it. A grep over
the indexer package finds no `st_mtime` use in any change-detection path. The document
domain repeats the pattern: unscoped selection hashes every discovered file
(`src/vaultspec_rag/indexer/_document_indexer.py:904`), and the vault domain hashes every
document per pass (`src/vaultspec_rag/indexer/_vault_indexer.py:633`), though the vault
corpus is small enough that the cost is minor there.

### Unscoped escalation fires on common, benign events

The durable retry state promotes `unscoped_required` aggressively
(`src/vaultspec_rag/watcher_retry.py`):

- `record_interrupted` forces `unscoped_required=True` unconditionally
  (`src/vaultspec_rag/watcher_retry.py:584`). A coalesced admission - a watcher event
  arriving while an equivalent job runs, routine under rapid saves - settles through
  exactly this path (`src/vaultspec_rag/watcher_execution.py:168`).
- `record_success` forces `unscoped_required=True` whenever a newer convergence
  generation is pending (`src/vaultspec_rag/watcher_retry.py:544`) - i.e. whenever a
  change arrives mid-attempt, the follow-up pass is a full-tree rehash.
- `record_failure` escalates (`src/vaultspec_rag/watcher_retry.py:271`), as do crash
  recovery markers (`src/vaultspec_rag/watcher_retry.py:759`) and construction over a
  pending bit (`src/vaultspec_rag/watcher_retry.py:241`).

Yet the convergence slot retains the exact dirty set in memory across non-success
terminals: held paths return to pending on anything but success
(`src/vaultspec_rag/watcher_runtime.py:328`), and the coalesce branch never captures at
all, deliberately keeping every watcher path dirty
(`src/vaultspec_rag/watcher_execution.py:157`). For a live instance, the volatile scope
survives; only a different or future process genuinely lacks it. The instance-scoped
promotion mechanism for that case already exists: `_refresh_scope_unlocked` escalates any
pending generation the refreshing instance did not scope
(`src/vaultspec_rag/watcher_retry.py:824`), and construction promotes a loaded pending bit
(`src/vaultspec_rag/watcher_retry.py:241`).

### The governing hash decision predates the code corpus

The accepted record `2026-03-07-blake2b-file-hashing-adr` rejected mtime as the change
detector (1-2s resolution claim, portability) and chose pure content hashing. It was
decided for the vault document corpus, before code indexing at today's scale. It evaluates
mtime only as the sole authority; it never considers the git-style split - stat evidence
as a rehash-avoidance gate, content hash as the sole authority, rehash on any stat
mismatch or racy timestamp. Modern filesystems record nanosecond-resolution mtimes
(`st_mtime_ns`); the 1-2s figure describes FAT-era timestamps.

### Alternatives sighted

- Persisting stat evidence inside the published hash sidecar: rejected from consideration
  early - the sidecar value type is a bare hex digest consumed by ledger publication and
  parity tests; widening it would touch the publication schema and every consumer.
- OS file-change journals (USN/FSEvents) for restart-time scope recovery: not
  investigated; heavy platform surface for the same benefit a stat gate yields.

### Not investigated

- Whether `watchfiles` overflow/rescan events inject additional unscoped passes beyond
  the retry-state escalations above.
- Chunk-worker read amplification (the pipeline re-reads admitted files to chunk; #155
  already merged hash-and-chunk into one read).

## Sources

- `src/vaultspec_rag/watcher_execution.py:74`, `:157`, `:168`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:613`, `:1267`, `:1302`
- `src/vaultspec_rag/indexer/_code_meta.py:163`
- `src/vaultspec_rag/indexer/_document_indexer.py:904`
- `src/vaultspec_rag/indexer/_vault_indexer.py:633`
- `src/vaultspec_rag/watcher_retry.py:241`, `:271`, `:544`, `:584`, `:759`, `:824`
- `src/vaultspec_rag/watcher_runtime.py:328`
- Unverified general-knowledge claim: git's racy-index handling (stat cache trusted only
  when entry mtime predates index write time) as the reference design for safe stat
  gating.
