---
tags:
  - '#research'
  - '#document-chunk-bounding'
date: '2026-07-23'
modified: '2026-07-24'
related:
  - "[[2026-07-23-chunk-id-uniqueness-research]]"
  - "[[2026-07-23-index-job-backend-resilience-adr]]"
---

# `document-chunk-bounding` research: `unbounded hook-emitted document units and the reserved-memory ceiling guard`

A resident 0.3.4 service failed every document index update for one root across
a two-hour window on 2026-07-23 with `cuda_memory_ceiling`, each failure naming
`slice-0` of a large corpus PDF. The question was whether those PDFs are
genuinely too large to embed. They are not. Two independent defects compose to
produce the symptom: preprocess-hook-emitted document units are the only chunk
class in the pipeline that is never size-bounded, and the memory guard that
converts the resulting spike into a job failure enforces the CUDA caching
allocator's retained pool against the same ceiling as live demand, so a job
fails on retention history and the failure is attributed to whichever file
happened to be first after a reset. Either defect is separately actionable; the
second is what makes the first terminal and unattributable.

## Findings

### Hook-emitted units are the only unbounded chunk class

`_document_chunks_from_output` in `src/vaultspec_rag/indexer/_chunk_worker.py:538`
branches on whether the preprocessor returned pre-chunked units. The
`units is None` branch delegates to `_document_chunks_from_text`
(`_chunk_worker.py:387`), which splits through `TextSplitter` and is bounded.
The `units` branch at `_chunk_worker.py:556` builds one `DocumentChunk` per unit
with `content=unit.text` verbatim and applies no size bound of any kind.

Every other chunk-producing path in the pipeline caps characters:

| Path               | Bound                                        | Locator                                          |
| ------------------ | -------------------------------------------- | ------------------------------------------------ |
| Vault / markdown   | `vault_chunk_chars` = 3000 (~750 BPE tokens) | `src/vaultspec_rag/config.py:583`                |
| Raw text documents | `TextSplitter` default `chunk_size` = 512    | `src/vaultspec_rag/indexer/_chunking.py:46`      |
| Code               | `ASTChunker(chunk_size=1500)`                | `src/vaultspec_rag/indexer/_ast_chunker.py:32`   |
| Hook-emitted units | none                                         | `src/vaultspec_rag/indexer/_chunk_worker.py:556` |

The vault bound is additionally epoch-tracked (`vault_content_epoch` in
`src/vaultspec_rag/indexer/_config_epoch.py:357`), so changing it re-chunks the
corpus. No equivalent exists for unit text.

The pipeline's slice packer treats an oversized chunk as a hard error rather
than a re-chunk trigger: `iter_weighted_document_slices` raises `ValueError`
when a single chunk's estimated weight exceeds the queue ceiling
(`src/vaultspec_rag/indexer/_streaming.py:730`). The design assumption is that
whatever produced the chunk already bounded it - true for code and markdown,
false for hooks.

### The unit schema bounds every field except the one that is embedded

`PreprocUnit` in `src/vaultspec_rag/indexer/_preprocess_schema.py:104` constrains
`title` and `section` to 4096 characters, `anchor` to 8192, and unit metadata to
16 KB, while `text` carries only `Field(min_length=1)` - a floor with no ceiling.
`PreprocOutput` (`_preprocess_schema.py:122`) similarly caps the unit *count* at
100_000 and document metadata at 64 KB without ever bounding unit text. The
enforceable contract is therefore 100_000 units of unbounded text each, and the
only effective ceiling anywhere in the chain is
`preprocess_max_emitted_bytes` = 10 MB (`src/vaultspec_rag/config.py:674`).

That value is a transport limit on the hook subprocess's total emitted output -
a runaway guard on an IPC boundary - not a semantic bound on one embedding
input. Because the units branch applies no bound of its own, the transport cap
became the last constraint in front of the encoder, which is a category error:
a number sized to answer "how much may a subprocess emit" is being asked to
answer "how large may one embedding input be".

The schema's own docstring records how the gap arose. It describes the fields as
"exactly one of `units` (pre-chunked) or `text` (extracted plain text, which the
indexer then runs through the normal text splitter)" - documenting that `text`
is split and, by omission, treating `units` as already correct. "Pre-chunked" is
an assertion made by the hook that nothing validates, while the same schema
declines to trust that hook about a 4096-character title.

The consequence is that the two branches of `_document_chunks_from_output`
treat an identical payload incompatibly: 10 MB emitted as `text` becomes roughly
20_000 separator-bounded chunks, and the same 10 MB emitted as one unit becomes
exactly one chunk. The outcome differs by four orders of magnitude based only on
which field the hook populated.

### The bounded splitter is structure-aware, not merely size-capped

`TextSplitter` (`src/vaultspec_rag/indexer/_chunking.py:35`) descends an ordered
separator list per language - for markdown `\n#`, `\n##`, `\n###`, `\n####`,
then paragraph `\n\n`, then line, word, and finally character
(`_chunking.py:77`). `_recursive_split` (`:131`) applies the next separator to
any fragment still over `chunk_size` and only falls back to fixed-width slicing
when structural separators are exhausted, with `chunk_overlap` preserving
continuity across boundaries. Markdown chunking therefore respects headings and
paragraph boundaries and still guarantees a maximum.

This matters for framing the gap: the pipeline is not missing a bounded
splitter, and the bound is not a crude character cut. A structure-aware splitter
with a hard ceiling already exists and is applied to markdown, code, and raw
document text. The units branch routes around it entirely.

Two qualifications on reuse. First, the document branch instantiates it as
`TextSplitter(language="text", chunk_overlap=0)` (`_chunk_worker.py:398`), which
selects the `text` separator list - paragraph, line, word, character - with no
markdown heading separators and no overlap. The heading-aware behaviour belongs
to the `markdown` configuration and is not what the document path currently
gets. Second, the splitter's bound is expressed in characters
(`_chunking.py:46`, `:136`) while the constraint that actually matters at the
encoder is the model's token window, so any reuse must state how a character
bound is derived from a token budget - a fixed chars-per-token ratio, or a
tokenizer-measured split. Token-aware splitting is a distinct mechanism this
research did not evaluate.

### The failing corpus emits one unit per PDF page

The observed root routes `src/cadrumo/_data/corpus/**/*.pdf` through a
command-form hook. That extractor emits one `PreprocessUnit` per non-empty page,
titled by page number (`dev/docs/preprocess/_pdf.py:155` in the consuming
project). Its `split_units_by_budget` helper groups units across output sidecars
to respect a per-sidecar byte budget; it never splits an individual unit.

A dense tabular page in that corpus runs several thousand characters, so a
page-unit chunk is materially larger than the 512-character text default and the
3000-character vault cap. Slices are packed primarily by chunk count
(`max_chunks` = `embedding_batch_size` = 64, `_document_indexer.py:474`), and
the dense forward then sub-batches that slice at `embedding_encode_batch_size`
= 32 (`_document_indexer.py:535`). Neither figure bounds tokens: per-chunk token
volume is unbounded on the units branch, so a forward pass over page-units
carries a multiple of the token volume both settings were tuned for, and
allocates accordingly. This is consistent with the failure label
`after-dense-forward`. The byte ceiling that could in principle constrain this
does not bind in practice - `index_queue_max_bytes` is 128 MB
(`config.py:633`) against slices measured in hundreds of kilobytes - so chunk
count is the only limit that actually applies.

### Document point identity has two branches, and the failing corpus uses the locator one

`document_point_id` (`src/vaultspec_rag/indexer/_document_identity.py:51`) hashes
a payload whose `location` component comes from `_locator_identity` (`:36`).
That helper returns `{"unit_ordinal": n}` only when the unit carries no locator
or a locator of kind `none`; whenever a real locator is present it returns
`{"kind", "value", "end"}` and the unit ordinal is not part of the identity at
all. The payload also carries `DOCUMENT_ID_VERSION`, so a deliberate identity
change has an existing versioning lever.

This matters directly for any scheme that splits one unit into several. The
failing PDF extractor emits page locators, so its units take the locator branch:
a discriminator added *beneath the unit ordinal* would not enter the identity,
and every fragment of one page would hash to the same point id. That is a
duplicate id within a single commit unit - the exact condition the ledger
rejects and that commit `5ec437c9` addressed on the code side. A fragment
discriminator must therefore extend the `location` identity on both branches,
not the unit ordinal alone.

### Oversized units are silently truncated, not just expensive

The dense model loads with `max_seq_length=2048`. A unit whose tokenization
exceeds that window is truncated by the encoder, so the tail of an oversized
page is never embedded and never retrievable. This failure is silent: it
produces no error, no job failure, and no test signal, and it degrades recall
on exactly the documents the corpus exists to make searchable. It applies to
every hook-emitted unit above the window, including on runs that report success.

### The ceiling guard enforces retained allocator pool alongside demand

`MemoryBudget` enforces two CUDA readings against one shared ceiling, in order:
`peak_cuda_allocated_mb` at `src/vaultspec_rag/memory_probe.py:488` and
`peak_cuda_reserved_mb` at `:498`, either of which yields
`cuda_memory_ceiling`. The class contract states the arrangement directly -
allocated and reserved memory share one ceiling. Demand enforcement therefore
already exists; the question this research bears on is whether the *reserved*
comparison should exist at all, because it is the one that fires under
retention.

`peak_cuda_reserved_mb` is `max(memory_reserved(), max_memory_reserved())`
(`memory_probe.py:163`).
`reserved` is the CUDA caching allocator's retained pool. PyTorch does not
return those blocks to the driver except through `empty_cache()`, so the reading
ratchets upward over a long-lived daemon's life and does not fall when tensors
release.

The per-job mitigation cannot address this. `reset_cuda_peak_memory_stats`
(`memory_probe.py:167`) is invoked at each job's budget construction
(`_document_indexer.py:412`, `_codebase_indexer.py:452`), but
`reset_peak_memory_stats()` rebases the peak counter to the *current* reserved
value; it releases no memory. When the allocator already retains 11 GiB the
reset yields a peak of 11 GiB immediately.

Two live measurements taken on 2026-07-23 separate retention from demand:

| State                                              | allocated | reserved | gap     |
| -------------------------------------------------- | --------- | -------- | ------- |
| Freshly restarted idle daemon (`/metrics`)         | 3691 MB   | 3703 MB  | 12 MB   |
| `code` job on root `main` after sustained indexing | 8016 MB   | 11330 MB | 3314 MB |

On a fresh process the two readings track within 12 MB. After sustained
indexing a 3.3 GB gap of pure allocator retention opens, against a 12288 MB
ceiling (`config.py:648`). Peak *allocated* never approached the ceiling, so the
`:488` check never fired; peak *reserved* crossed it, so the `:498` check did.
The quantity that decided these job failures is therefore fragmentation history,
not the work the job was asked to do - which is an argument about the reserved
comparison specifically, not about ceiling enforcement as such.

The headroom is structurally tight independent of the above: roughly 3.5 GB of
the 12288 MB ceiling is permanently held by the three resident models (dense,
sparse, reranker), per the idle measurement. Separately,
`index_cuda_allocator_fraction` = 0.8 (`config.py:649`) permits the allocator to
reserve about 13.1 GB on a 16376 MB device - above the ceiling the guard treats
as fatal, so the allocator is licensed to enter a range the guard cannot
tolerate.

### The same reserved reading also drives the support-profile projection

The budget guard is not the only consumer of the reserved high-water. Both
indexers project a corpus's CUDA dimension for support-profile admission from
the same reading. The managed-service profile's CUDA limit is 12 GiB, equal to
the enforcement ceiling (`src/vaultspec_rag/config.py:648`), so a projection
computed from reserved rejects a corpus under allocator retention for exactly
the reason the guard fails jobs - surfacing as a corpus-limit rejection rather
than a ceiling breach. Correcting the guard alone would therefore relocate the
failure rather than remove it. This was established during implementation on
2026-07-23 rather than by the original survey, which examined only the
enforcement site.

### The guard misattributes the failure to an innocent file

`slice-0 ... after-dense-forward` is the first checkpoint sampled after a job's
peak-stats reset. Because the retained reserve is already near the ceiling from
earlier work, whichever file leads the next job trips the guard. The recorded
failures name specific corpus PDFs, but those filenames identify the first file
processed, not the cause. The latch behaviour compounds this: the first
violating observation and its outcome are latched, and every subsequent
observation re-raises it (`memory_probe.py` class contract, lines 239-241).

A practical consequence for triage: reducing slice size cannot clear this
failure, because the reserve is already held before the slice executes. Restart
of the process does clear it, which is why a fresh daemon indexes successfully
for a period and then degrades - the pattern seen across the 2026-07-23 job
history.

### Option space

For the chunking gap, the evidence favours routing unit text through the same
bounded splitter the `units is None` branch already uses, carrying
`title`/`section`/`anchor`/`locator` onto each resulting sub-chunk. That
requires a sub-ordinal discriminator in the point identity so ids stay unique
and replay-stable, structurally the same construction as the per-file emit
ordinal added for code chunks in commit `5ec437c9`. An alternative - rejecting
oversized units back to the hook author - was considered and is weaker: it makes
every hook re-implement bounding the pipeline already owns, and offers no path
for corpora whose natural unit genuinely exceeds the window.

For the guard, the substantive question is whether the reserved comparison
should retain an enforcement role at all, given that the allocated comparison
beside it already gates on demand. The options are removing reserved from
enforcement while continuing to report it, giving it a separate and higher
ceiling of its own, and calling `empty_cache()` immediately before the peak
reset so the rebase reflects genuinely retained memory. The last is
complementary to either of the first two rather than an alternative to them.
The trade being made is that reserved is the reading that would catch genuine
device exhaustion caused by fragmentation, so removing it narrows protection in
exchange for not failing well-sized jobs.

### Not investigated

Whether other consuming projects ship hooks emitting units above the token
window was not surveyed; only the one failing root's extractor was read. The
tokenized length distribution of the failing corpus was not measured - the
character-count comparison stands in for it. No attempt was made to reproduce
the reserved ratchet under controlled load; the two live readings are
observational.

## Sources

- `src/vaultspec_rag/indexer/_chunk_worker.py:387`, `:538`, `:556`
- `src/vaultspec_rag/indexer/_chunking.py:35`, `:46`, `:77`, `:131`
- `src/vaultspec_rag/indexer/_preprocess_schema.py:104`, `:122`
- `src/vaultspec_rag/config.py:674`
- `src/vaultspec_rag/indexer/_ast_chunker.py:32`
- `src/vaultspec_rag/indexer/_config_epoch.py:357`
- `src/vaultspec_rag/indexer/_streaming.py:683`, `:730`
- `src/vaultspec_rag/indexer/_document_indexer.py:412`, `:474`, `:535`
- `src/vaultspec_rag/indexer/_document_identity.py:36`, `:51`
- `src/vaultspec_rag/indexer/_codebase_indexer.py:452`
- `src/vaultspec_rag/memory_probe.py:163`, `:167`, `:488`, `:498`
- `src/vaultspec_rag/config.py:583`, `:633`, `:648`, `:649`
- commit `5ec437c9`
- `dev/docs/preprocess/_pdf.py:155` (consuming project, read at 2026-07-23)
- Live service `/metrics` and `server jobs` readings, 2026-07-23 (observational,
  not reproducible from this repository)
