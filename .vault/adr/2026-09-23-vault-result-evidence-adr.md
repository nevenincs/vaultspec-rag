---
tags:
  - '#adr'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:e7b363f3c92ef810ac62d2940152f314d7a9dd2fc551860f4b106d4c6e8c20fb'
related:
  - "[[2026-09-23-vault-result-evidence-research]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-26-storage-schema-contract-adr]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
---

# `vault-result-evidence` adr: `query-selected passages, stored locators and fp16 reranking for vault results` | (**status:** `accepted`)

## Problem Statement

A vault hit must let an agent read the answer without re-reading the whole record. Today
the right record usually ranks first, but its snippet is the opening 200 characters of
the winning chunk. That text is usually a heading and a first bullet, not the passage
that matched. Vault hits also carry no line span or section, so the caller cannot jump
to the passage either. `2026-06-12-service-concurrency-adr` D7 already required the
snippet to come from the matched passage, and D8 required a heading path in the vault
embedding input. Neither shipped. The same search spends about 95% of its time in an
fp32 reranker. Measurements are in `2026-09-23-vault-result-evidence-research`.

This record decides how vault results carry answer evidence and a locator, how that
evidence is chosen, what reranking precision the service runs, how existing indexes
reach the new shape, and which gate keeps the behaviour from regressing.

## Considerations

- **The winning chunk is not enough on its own.** Passage selection inside it saturates
  at that chunk's ceiling. The record's runner-up chunk recovers most of the misses,
  while whole-record selection adds distractors and does worse (research: winning-chunk
  and runner-up findings).
- **Precision.** fp16 reranking agrees with fp32 on every measured ranking and is about
  3x faster in service (research: reranker precision finding). That headroom pays for
  passage scoring.
- **Recoverable locators.** Chunks are verbatim, contiguous substrings of the body, so
  line spans and heading paths can be computed at index time (research: locator
  finding).
- **Additive payload fields do not bump the storage schema**
  (`2026-06-26-storage-schema-contract-adr` D1).
- **Rebuilds are explicit.** A rebuild the index needs must surface as the typed
  `full_reindex_required` refusal, never as an implicit rebuild
  (`2026-09-07-explicit-reindex-authority-adr`).
- **The reranker scores real content.** Passage scoring keeps it: the scored text is
  verbatim passage content, not a fixed-width prefix.
- **Ranking must not move unmeasured.** Document ranking already scores hit@1 0.72-0.81
  (research: reproduction finding). A snippet fix must not change document order as a
  side effect.

## Considered options

- **Snippet chooser.**
  - *CrossEncoder over passages (kept).* Most accurate on held-out cases, and reuses the
    loaded model.
  - *BM25 over passages (rejected).* CPU-only, but one case worse on held-out. A second
    scorer would be a second implementation of one behaviour.
  - *Dense passage vectors (rejected).* Multiplies index size and encode cost.
- **Selection scope.**
  - *Top-two chunks of the final record (kept).*
  - *Winning chunk only (rejected).* Capped at that chunk's ceiling.
  - *Whole record (rejected).* Less accurate, and scores every passage.
- **Where passages are segmented.**
  - *Index time, stored per chunk (kept).* One whole-document pass knows fence and
    heading state. The query path does no markdown parsing, and payload readers get
    the structure too.
  - *Query time, from the chunk text (rejected).* It would need the fence and heading
    state at the chunk's start stored anyway.
- **Ranking change (MaxP, chunk score = best passage score).** Rejected for this
  decision. It moves document order unmeasured, and the evidence gap is about which
  text is shown, not which record wins.
- **Chunk size or heading-aligned packing.** Deferred. It is a retrieval hypothesis with
  no measurement behind it. The evaluation gate below is its prerequisite.
- **Precision.**
  - *fp16 (kept).* Smallest score deviation from fp32.
  - *bf16 (rejected).* Equal speed, 13x larger score deviation.
  - *fp32 (rejected).* The latency cost.
- **Migration.**
  - *Point-schema bump surfaced as the typed rebuild refusal (kept).*
  - *GPU-free payload refresh through a metadata-digest salt (rejected).* The heading-path
    embedding change needs new vectors anyway, and the salt plus stat-gate invalidation
    would add a second migration mechanism.

## Constraints

- GPU discipline: pair assembly and the passage-length bound happen before the GPU
  lock; only the forward call holds it; score conversion follows its release.
  Splitting runs in spawn workers and stays torch-free.
- One implementation per behaviour. The two CrossEncoder construction sites
  (`src/vaultspec_rag/service.py:369`, `src/vaultspec_rag/search/_searcher.py:429`)
  become one. The out-of-memory backoff around predict is shared by chunk reranking
  and passage scoring. The vault embedding input is built by one function, used by the
  encoder and by donor verification alike.
- Additive payload and result fields only. Removing or renaming existing ones is out of
  scope.
- Code and document hits keep today's behaviour. Document hits share the 200-character
  cut, but their extractor-supplied units need their own passage model, which is
  deferred.

## Implementation

**Structural passages at index time.** A torch-free leaf module makes one pass over a
vault body:

- It tracks fenced blocks and the heading stack.
- It emits passages: blank-line-delimited paragraphs, lists, tables and fences.
- It enforces a 1,200-character bound, splitting an oversized passage at list items,
  then at lines, then at sentence boundaries inside an overlong line.
- It merges tiny neighbours under the same heading.
- Each passage carries its body offsets, its 1-based file line span (frontmatter
  included), and its `section` breadcrumb. The breadcrumb is headings below the H1
  joined with ` > `, the format document hits already use.

`split_document` keeps its current chunk boundaries and attaches, per chunk:

- the chunk's own `line_start`, `line_end` and `section`;
- the passages that fall inside it, clipped at chunk boundaries, as offsets into the
  chunk's stored `content`.

The fields are additive on the vault chunk payload and its typed schema, and count as
structural payload keys.

**Query-selected snippets.** After the vault pipeline settles its final page (group,
graph nudge, intent prior, status filter, top-k cut), the searcher collects candidate
passages for each result:

- passages from its winning chunk;
- passages from that record's next-best chunk, if one sits in the already reranked
  candidate window. No extra retrieval runs.

One batched CrossEncoder forward scores every (query, passage) pair on the page. Each
result takes its best passage:

- `snippet` becomes that verbatim passage;
- `line_start`, `line_end` and `section` become the passage's.

A result with one candidate passage skips scoring. With the reranker disabled, the
first passage of the winning chunk is used. A legacy point without passages yields its
chunk text cut at the same bound, with no locator. Ranking and scores do not change.

**Result contract.**

- `SearchResult` gains `section`. For vault hits, the line fields describe the snippet
  passage in file coordinates.
- The in-process CLI JSON path serializes through the same result model as the service,
  which removes the leaked `rerank_text` and the missing `section`.
- The human renderer shows vault hits as `path:start-end`, with the section and the
  passage.
- The MCP tools pass the fields through. Their descriptions and the user docs name the
  new fields.

**fp16 reranking.** One reranker constructor loads the CrossEncoder in the same fp16
dtype as the encoders. The service and the searcher fallback both use it.

**Heading-path embedding (completes the concurrency ADR's D8).** The vault embedding
input becomes title, section breadcrumb and chunk text, built by one function. Donor
reuse verifies the full embedding input rebuilt from the donor payload, not `content`
alone. This change ships only if the evaluation gate shows no ranking regression
against the fp16 baseline. If it regresses, D8 is amended with the evidence instead.

**Migration.** `VAULT_POINT_SCHEMA` bumps. The vault incremental converts the resulting
ledger incompatibility into the typed `full_reindex_required` refusal, naming
`vaultspec-rag index --type vault --rebuild`, as code and document already do. Until
the operator rebuilds, the published index keeps serving through the legacy-point path.

**Evaluation gate.**

- *Labelled set.* An in-repo integration quality gate runs over the frozen vault
  corpus. Its cases are written blind from the documents, with no search output in
  view: query, gold record, gold section and verbatim evidence sentence.
- *Metrics.* Gold-record hit@1 and MRR, evidence-in-snippet rate, and section-match
  rate.
- *Hard invariant.* Every vault hit's snippet occurs verbatim in the file at its
  reported line span.
- *Floors.* Recorded in a baseline file beside the existing ranking baseline, and taken
  from a passing implementation run on this set.
- *Cross-corpus check.* The issue's external query sets are re-run once and recorded in
  the feature's audit.
- *Latency.* Server-side vault search time at ten results must end at or below half of
  today's fp32 figure, passage scoring included.

## Rationale

- **Knockout.** Only a passage-level snippet with a stored locator makes a hit
  answerable in place. The research shows the evidence sits in a paragraph-sized
  window that 200 characters cannot hold. A position-chosen window misses it almost
  every time.
- **Chooser.** The CrossEncoder wins because it is already resident, is more accurate
  than BM25 on held-out cases, and at fp16 costs a fraction of the chunk rerank it runs
  beside.
- **Scope.** Top-two-chunk scope is the measured optimum: it beats both narrower and
  wider scopes.
- **Segmentation at index time.** Segmenting once over the whole document is the only
  placement that knows fence and heading state without persisting parser state.
- **Precision.** fp16 is the knockout on latency, with no measured ranking cost. It also
  aligns the reranker with the precision the encoders already use.
- **Migration.** Folding migration into one typed rebuild matches the explicit-reindex
  decision. The heading-path embedding needs new vectors anyway, so a GPU-free payload
  path would buy nothing.

## Consequences

- **Snippets grow.** They go from 200 to up to 1,200 characters, so a ten-result JSON
  or MCP page grows by roughly 10 KB. Agents get the answering passage and a jumpable
  span instead of a heading.
- **Latency drops.** fp16 more than pays for the passage forward.
- **Operators must rebuild each vault index once.** Status and jobs name the command.
  Until then, results keep today's shape. The rebuild costs about a minute per 800
  records.
- **Payloads grow** by a passage list per chunk. Direct-Qdrant readers ignore the new
  fields.
- **Some evidence stays out of reach.** When the evidence chunk is outside the reranked
  window, the snippet cannot show it. The gate measures how often. Fetching the
  record's remaining chunks is the follow-up if that rate matters.
- **Shape-pinning tests change with the contract.** The result-shape, payload-parity,
  metadata-subset and CLI-render tests, plus the typesafe test that asserts snippet
  text.
- **Future work has an instrument.** Chunk-size and packing experiments, MaxP ranking,
  and document-hit passages now have a measurement gate and a passage model to reuse.
