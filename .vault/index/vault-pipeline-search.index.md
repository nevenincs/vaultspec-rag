---
generated: true
tags:
  - '#index'
  - '#vault-pipeline-search'
date: '2026-08-14'
modified: '2026-09-02'
body_schema: 'body-v2'
body_hash: 'sha256:df0e998f41f961de7522782e9703373f90755c29c123fec118611b8a486cc7d1'
related:
  - '[[2026-06-24-vault-pipeline-search-W01-P01-S01]]'
  - '[[2026-06-24-vault-pipeline-search-W01-P01-S02]]'
  - '[[2026-06-24-vault-pipeline-search-W01-P01-S03]]'
  - '[[2026-06-24-vault-pipeline-search-W01-P02-S04]]'
  - '[[2026-06-24-vault-pipeline-search-W01-P02-S05]]'
  - '[[2026-06-24-vault-pipeline-search-W01-P02-S06]]'
  - '[[2026-06-24-vault-pipeline-search-W02-P03-S07]]'
  - '[[2026-06-24-vault-pipeline-search-W02-P03-S08]]'
  - '[[2026-06-24-vault-pipeline-search-W02-P03-S09]]'
  - '[[2026-06-24-vault-pipeline-search-W02-P03-S10]]'
  - '[[2026-06-24-vault-pipeline-search-W02-P03-S11]]'
  - '[[2026-06-24-vault-pipeline-search-W03-P04-S12]]'
  - '[[2026-06-24-vault-pipeline-search-W03-P05-S13]]'
  - '[[2026-06-24-vault-pipeline-search-W03-P05-S14]]'
  - '[[2026-06-24-vault-pipeline-search-W03-P05-S15]]'
  - '[[2026-06-24-vault-pipeline-search-W03-P05-S16]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S17]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S18]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S19]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S20]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S21]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S22]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P06-S23]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P07-S24]]'
  - '[[2026-06-24-vault-pipeline-search-W04-P07-S25]]'
  - '[[2026-06-24-vault-pipeline-search-W05-P08-S26]]'
  - '[[2026-06-24-vault-pipeline-search-W05-P08-S27]]'
  - '[[2026-06-24-vault-pipeline-search-W05-P08-S28]]'
  - '[[2026-06-24-vault-pipeline-search-W05-P09-S29]]'
  - '[[2026-06-24-vault-pipeline-search-W05-P09-S30]]'
  - '[[2026-06-24-vault-pipeline-search-W06-P10-S31]]'
  - '[[2026-06-24-vault-pipeline-search-W06-P10-S32]]'
  - '[[2026-06-24-vault-pipeline-search-adr]]'
  - '[[2026-06-24-vault-pipeline-search-audit]]'
  - '[[2026-06-24-vault-pipeline-search-plan]]'
  - '[[2026-06-24-vault-pipeline-search-research]]'
---

# `vault-pipeline-search` feature index

Auto-generated index of all documents tagged with `#vault-pipeline-search`.

## Documents

### adr

- `2026-06-24-vault-pipeline-search-adr` - `vault-pipeline-search` adr: `intent-aware pipeline ranking and result shape for vault search` | (**status:** `accepted`)

### audit

- `2026-06-24-vault-pipeline-search-audit` - `vault-pipeline-search` audit: `live persona testimonials`

### exec

- `2026-06-24-vault-pipeline-search-W01-P01-S01` - Author the graded-relevance rubric table keyed on intent x doc_type x status
- `2026-06-24-vault-pipeline-search-W01-P01-S02` - Author the intent-tagged labeled query set with hand-graded gold judgments
- `2026-06-24-vault-pipeline-search-W01-P01-S03` - Enrich the synthetic corpus generator with status markers and pipeline-role edges
- `2026-06-24-vault-pipeline-search-W01-P02-S04` - Implement role-aware NDCG, Authoritative-at-k, MRR, and role-precision metrics
- `2026-06-24-vault-pipeline-search-W01-P02-S05` - Add the quality-marked integration harness driving a real index against the gold set
- `2026-06-24-vault-pipeline-search-W01-P02-S06` - Capture and commit the baseline ranking report on the current reranker
- `2026-06-24-vault-pipeline-search-W02-P03-S07` - Parse status from the ADR H1 and strip the status suffix from the displayed title
- `2026-06-24-vault-pipeline-search-W02-P03-S08` - Carry status on VaultDocument and VaultChunk and write it to the Qdrant payload
- `2026-06-24-vault-pipeline-search-W02-P03-S09` - Add related and status fields to SearchResult
- `2026-06-24-vault-pipeline-search-W02-P03-S10` - Map related and status from Qdrant rows in the vault search path
- `2026-06-24-vault-pipeline-search-W02-P03-S11` - Reindex and regression-test that status and related are present on results
- `2026-06-24-vault-pipeline-search-W03-P04-S12` - Add orientation and debug intent weight profiles and the per-type cap to config
- `2026-06-24-vault-pipeline-search-W03-P05-S13` - Implement the multiplicative per-(type x status) reweight function
- `2026-06-24-vault-pipeline-search-W03-P05-S14` - Compose the intent prior post-rerank and select the active profile in vault search
- `2026-06-24-vault-pipeline-search-W03-P05-S15` - Implement the per-type result cap to prevent one type crowding the top-k
- `2026-06-24-vault-pipeline-search-W03-P05-S16` - Tune the weight profiles against the gold set and record the improvement over baseline
- `2026-06-24-vault-pipeline-search-W04-P06-S17` - Add the explicit --intent orientation or debug flag and its validation
- `2026-06-24-vault-pipeline-search-W04-P06-S18` - Add doc-type union selection with audit included and index excluded
- `2026-06-24-vault-pipeline-search-W04-P06-S19` - Add the --status control with the default active set and opt-in widening
- `2026-06-24-vault-pipeline-search-W04-P06-S20` - Thread intent, status, and doc-type-union params through the HTTP search client
- `2026-06-24-vault-pipeline-search-W04-P06-S21` - Accept and validate the new search params in the server route
- `2026-06-24-vault-pipeline-search-W04-P06-S22` - Thread the new params into the searcher entry points and apply them
- `2026-06-24-vault-pipeline-search-W04-P06-S23` - Mirror the new params on the MCP search_vault tool for adapter parity
- `2026-06-24-vault-pipeline-search-W04-P07-S24` - Render the frontmatter metadata line with doc_type, feature, status, date, related
- `2026-06-24-vault-pipeline-search-W04-P07-S25` - Add human and JSON result-shape tests for the enriched fields
- `2026-06-24-vault-pipeline-search-W05-P08-S26` - Remove the quality and benchmark verbs from the production CLI command group
- `2026-06-24-vault-pipeline-search-W05-P08-S27` - Relocate run_quality_probe and run_benchmark capability under the test tree
- `2026-06-24-vault-pipeline-search-W05-P08-S28` - Regenerate the bundled CLI reference for the removed verbs
- `2026-06-24-vault-pipeline-search-W05-P09-S29` - Add the per-intent persona ranking-testimonial integration test
- `2026-06-24-vault-pipeline-search-W05-P09-S30` - Run the full acceptance gate and produce the A/B delta report
- `2026-06-24-vault-pipeline-search-W06-P10-S31` - Reindex the real vault on the new code and capture orientation persona live-search testimonials
- `2026-06-24-vault-pipeline-search-W06-P10-S32` - Capture debugging persona live-search testimonials and the consolidated verdict

### plan

- `2026-06-24-vault-pipeline-search-plan` - `vault-pipeline-search` plan

### research

- `2026-06-24-vault-pipeline-search-research` - `vault-pipeline-search` research: `intent-aware pipeline ranking for vault search`
