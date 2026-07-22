---
tags:
  - '#research'
  - '#code-document-index-boundary'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - "[[2026-06-11-preprocess-hooks-audit]]"
  - "[[2026-07-21-large-index-resilience-research]]"
---

# `code-document-index-boundary` research: `source admission versus document corpus indexing`

The production incident reported a 21,675-file, 260,768-chunk code rebuild even though the
consumer repository contained only 3,485 Python files. A bundled document corpus contributed
1,596 PDF, workbook, schema, markup, and sidecar files; 28 admitted XSDs could not be decoded as
UTF-8. This research traces why those documents entered the code collection, why dry-run
did not expose the true admission set, how restart-from-zero amplified the error, and which
correction preserves an honest code/document boundary.

## Findings

### F1. The consumer followed the shipped preprocessing contract

The corpus was not admitted by an accidental broad glob. The audited consumer configuration
deliberately registered its bundled HTML, PDF, XLS, and XLSX sources for the resident
indexer, and excluded only duplicate extracted sidecars. The incident inventory found a
large mixed set of JSON, Markdown, HTML, PDF, XLSX, XLS, XSD, and smaller text tails.

Vaultspec RAG implements that intent literally. A preprocess match is tested before the
extension, size, and binary gates in
`src/vaultspec_rag/indexer/_codebase_indexer.py:361-398`, and the scoped path repeats the
same widening at `src/vaultspec_rag/indexer/_codebase_indexer.py:1730-1762`. Ignore specs
still win, so a repository can contain the workload immediately by ignoring the corpus
root.

### F2. A reviewed storage compromise erased the content-domain boundary

The preprocessing research and ADR originally selected a dedicated `preproc_docs`
collection because extracted units are neither source code nor vault records
(`.vault/research/2026-06-10-preprocess-hooks-research.md:110-123` and
`.vault/adr/2026-06-10-preprocess-hooks-adr.md:161-175`). Review accepted a smaller v1
deviation that stores those units as `CodeChunk` rows in `codebase_docs`; the amendment is
recorded at `.vault/adr/2026-06-10-preprocess-hooks-adr.md:231-241` and the approving audit
at `.vault/audit/2026-06-11-preprocess-hooks-audit.md:74-82`.

That deviation is the primary defect. The public `--type code` boundary cannot distinguish
ordinary source from extracted documents, so code rebuild, counts, progress, watcher
triggers, search results, and recovery all treat the two workloads as one corpus.

### F3. Parser capability is also being used as admission policy

`LANGUAGE_MAP` mixes AST-capable source languages with Markdown, JSON, HTML, YAML, TOML,
plain text, properties, XML, and XSD; `SUPPORTED_EXTENSIONS` is derived directly from that
map (`src/vaultspec_rag/indexer/_chunking.py:153-193`). Thus XSD and many corpus manifests
are admitted even when preprocessing is disabled. The binary probe only tests for a NUL
byte (`src/vaultspec_rag/indexer/_chunking.py:309-318`), while the worker performs strict
UTF-8 decoding and warns/skips only after admission
(`src/vaultspec_rag/indexer/_chunk_worker.py:225-239`). Legacy-encoded XSDs therefore
consume scan and hashing work and produce decode failures instead of being rejected by the
source boundary.

The durable correction must separate "can split this format" from "belongs in this index."
Directory-name heuristics such as automatically excluding every `data/` or `corpus/` tree
are unsafe; legitimate repositories can keep source or schemas there. Admission must be an
explicit, shared policy with a reasoned disposition.

### F4. The advertised dry-run is not equivalent to a real index run

`scan_codebase_files` constructs an indexer and calls `scan_files` without initializing
the preprocess context (`src/vaultspec_rag/api.py:584-602`). The admission bypass consults
only that context, initialized as `None`; real full, unscoped, and scoped runs initialize
it before scanning. The CLI dry-run calls this API and returns before applying
`--no-preprocess` (`src/vaultspec_rag/cli/_index.py:138-181` and `:552-577`). It therefore
under-reports the PDF/workbook set that a real run will process, removing the operator's
only preflight visibility into this failure.

### F5. Restart-from-zero magnifies bad admission but is a separate defect

A full build streams upserts before publishing its metadata sidecar. If the first run dies,
the collection can be non-empty while metadata is absent; `_needs_embed_rebuild` interprets
that state as a clean-rebuild requirement on the next attempt
(`src/vaultspec_rag/indexer/_codebase_indexer.py:1398-1470`, `:1587-1594`, and
`src/vaultspec_rag/indexer/_code_meta.py:82-100`). The accepted large-index ledger remains
necessary for legitimate large codebases, but it must not be used to make an incorrectly
classified document corpus merely survivable.

### F6. The large-index acceptance floor is based on contaminated input

The current resilience research calls the 250,872-chunk mixed incident workload a legitimate
code-index acceptance floor (`.vault/research/2026-07-21-large-index-resilience-research.md:63-68`),
and D6 requires the default code profile to admit it
(`.vault/adr/2026-07-21-large-index-resilience-adr.md:201-209`). The new incident evidence
invalidates that interpretation, not the resource-bounding or checkpoint decisions. The
code profile needs a comparable true-source fixture; a retained document workload needs a
separately named profile. Plan step W04.P13.S47 must be amended accordingly.

### F7. Admission, execution, and epoch identity can observe different configurations

`_resolve_scan_inputs` loads preprocessing rules for scan and epoch calculation, while
`_begin_preprocess_run` reloads them independently for worker execution
(`src/vaultspec_rag/indexer/_codebase_indexer.py:190-240` and `:287-297`). Full and
incremental entry points call those operations separately, and the watcher owns another
reloadable copy (`src/vaultspec_rag/watcher.py:192-234`). A configuration change between
reads can therefore admit with one policy, execute another, and stamp a third identity.

The correction needs one immutable resolved-policy snapshot per run. Every classifier,
worker input, epoch, checkpoint signature, and dry-run projection must consume that same
snapshot. A watcher configuration event can affect multiple content kinds and must schedule
an unscoped reconciliation rather than guess one destination from the new filesystem state.

Target migration also conflicts with the accepted degrade-on-error rule. If a legacy rule
without a target is merely dropped, a lower-priority rule or default source policy can admit
the path as code. A routing-schema defect must instead produce a structured
`migration_required` refusal before storage mutation; it cannot be treated as an absent rule.

### F8. The preprocessing execution and cache contracts are not generically faithful

`PreprocessRule.options` is documented and parsed but never delivered to command or
entry-point execution (`src/vaultspec_rag/indexer/_preprocess_config.py:82-123`,
`:374-405`, and `src/vaultspec_rag/indexer/_preprocess_runner.py:264-317`). The cache key is
only source hash, invocation string, and output-schema version
(`src/vaultspec_rag/indexer/_preprocess_cache.py:64-82`). It excludes source path, options,
and an explicit extractor version. Two byte-identical files at different paths can therefore
share incorrect path-dependent output, and changing options or project-local extractor code
can reuse stale output.

The output contract also accepts `source_path`, title, section, and metadata, but the current
conversion trusts the host path while silently discarding title, section, and metadata
(`src/vaultspec_rag/indexer/_preprocess_schema.py:45-86` and
`src/vaultspec_rag/indexer/_chunk_worker.py:95-144`). A generic v2 contract must bind output
to the invoked source, actually deliver normalized options, preserve declared document
metadata, and use a path-safe execution fingerprint with an explicit version lever. Content-
addressable cache sharing may be an opt-in only for extractors that declare path independence.

### F9. Hash-only failure records incorrectly certify convergence

A readable file that fails UTF-8 decoding or chunking returns its hash with zero chunks, and a
preprocess skip does the same (`src/vaultspec_rag/indexer/_chunk_worker.py:342-414`). Full and
scoped indexers write those hashes into ordinary metadata
(`src/vaultspec_rag/indexer/_codebase_indexer.py:899-904` and `:1871-1876`). Later
incremental runs see unchanged bytes and do not retry, even though cache documentation says
transient skips are retried. `on_error=passthrough` also discards its preprocess disposition
and can raw-decode a file that was admitted only because a transform matched.

Per-file state must distinguish successfully indexed, policy-rejected, retryable extraction
failure, terminal extraction failure, and decode/chunk failure. Only success or a stable
policy rejection is converged. Retryable work remains a durable convergence obligation under
the service retry/circuit policy. Passthrough stays in its declared content kind and must pass
that kind's raw admission and decoder; it never crosses into code implicitly.

### F10. Matched inputs and aggregate expansion are not bounded

Preprocess matches bypass the 10 MB source gate, then workers call `read_bytes` before hashing
or invoking the extractor (`src/vaultspec_rag/indexer/_codebase_indexer.py:382-400` and
`src/vaultspec_rag/indexer/_chunk_worker.py:342-371`). The emitted-size setting is named in
bytes but counts Python characters (`src/vaultspec_rag/indexer/_preprocess_runner.py:116-121`),
and its per-file limit does not bound aggregate extracted bytes or chunks.

Document admission therefore needs profile and per-rule source-byte ceilings, streaming
hashing, weighted batch-input accounting, correctly measured emitted bytes, aggregate
extracted-byte/chunk limits, and the same interruptible queue, RSS, CUDA, no-progress, and
checkpoint controls as code. A code-only job must not start document extractors.

### F11. Public routing and lifecycle are two-domain and contain unsafe fallthroughs

Index and clean accept only `vault`, `code`, and `all`; status and jobs expose only vault and
code. Search already uses `docs` as an alias for vault, while server routes treat any non-vault
value as code (`src/vaultspec_rag/cli/_search.py:438-460` and
`src/vaultspec_rag/server/_routes.py:380-421`, `:568-587`). Adding a content kind without
exhaustive parsing could silently route an unknown value back into the code collection.

The new public type needs a non-conflicting canonical token, strict normalization, and explicit
branches everywhere. Counts, status, clean, jobs, HTTP, MCP, storage schema advertisement,
snapshot/migration, search filters, reranking, and structured partial `all` outcomes must all
name the third domain. Existing `docs` behavior cannot be silently reinterpreted.

### F12. Recovery must cover both missing and stale sidecars

The known first-run failure leaves points with no metadata and causes another clean rebuild.
There is also a symmetric destructive case: a clean rebuild drops the collection but leaves
the old complete sidecar, streams only part of the new collection, and can then be interrupted
(`src/vaultspec_rag/indexer/_codebase_indexer.py:1419-1477`). The next incremental run may
trust the old hashes and preserve the partial collection because `_needs_embed_rebuild` checks
the marker, not generation completeness (`src/vaultspec_rag/indexer/_code_meta.py:96-110`).

Migration cannot rely on the sidecar alone. A bounded store scan plus fresh classification and
a durable generation ledger must handle missing, stale, and partial metadata. Route changes
populate and checkpoint the destination before deleting the origin, tolerate replay between
the two mutations, and refuse all mutation when routing configuration is invalid. Existing
source point IDs can remain stable; document points receive their own collection-local scheme,
while content kind belongs in generation and checkpoint identity.

### Options

**O1 - Consumer policy only.** A consumer can exclude any unwanted paths with its own
`.vaultragignore`; ignore already outranks preprocess, and the membership epoch forces an
unscoped reconciliation that prunes old points. That is external repository policy, not an
upstream implementation. It does not correct dry-run or domain conflation in Vaultspec RAG.

**O2 - Shared code-admission policy, no document index.** Introduce one admission function
used by full scan, scoped scan, watcher, and dry-run. Preprocess rules no longer widen code
membership unless they explicitly opt in as code; text-format capability no longer implies
default code membership. This makes `--type code` honest and preserves unconventional
source through explicit rule intent, but document hooks cease to be searchable until a
separate content domain exists.

**O3 - Restore the dedicated document domain.** Implement O2 and restore the original D12
separation: preprocessed documents receive their own collection/content kind, index job,
search type, counts, metadata, lifecycle, and checkpoint signature. `--type code` indexes
source only; `--type all` includes both; an explicit document type preserves valuable
document search without charging every code rebuild for it. Complete O3 also requires the
immutable policy snapshot, fail-closed schema migration, per-kind recovery state, bounded
preprocessing, and public lifecycle corrections in F7-F12. This is the architecturally
complete correction and the recommended durable outcome, but it is a cross-surface feature
that requires an approved ADR and plan.

### Recommended sequence

O1 is outside this repository. For upstream, choose O3 and make O2's shared admission
disposition its first implementation slice. Classification is driven only by explicit rule
intent and format capability; no consumer directory, package, or domain name enters source,
tests, comments, or defaults. Include a versioned admission-policy fingerprint in
membership/checkpoint identity so deployment reconciles existing mixed points. Use one
immutable policy snapshot, reject unmigrated routing before mutation, and represent failed
files as unresolved work rather than successful hashes. Keep the large-index ledger work,
but replace the contaminated code acceptance fixture and test the document workload under
its own independently bounded profile.

The remaining architecture choice is whether document-target preprocessing ships with its
own searchable content kind immediately (O3) or whether the first release only prevents it
from widening code membership (O2). O3 preserves the full generic preprocessing capability
and is recommended.
