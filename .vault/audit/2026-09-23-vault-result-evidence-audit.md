---
tags:
  - '#audit'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:4bb6da902c98a133d7b5e965d2bbfe58c3df1a27b8c87ff39fd1e4dcf7bbc80b'
related:
  - "[[2026-09-23-vault-result-evidence-plan]]"
  - "[[2026-09-23-vault-result-evidence-adr]]"
---

# `vault-result-evidence` audit: `phase-close and plan-close review of vault result evidence`

## Scope

This audit covers the integrated behaviour of `2026-09-23-vault-result-evidence-plan`
against `2026-09-23-vault-result-evidence-adr`, commits `bd825c2f`..`97f0380e` on
`fix/rag-results`, and the corrections that follow the plan-close review.

Behaviour under review:

- the index-time passage and locator payload;
- the typed rebuild refusal;
- the fp16 reranker;
- query-selected snippets and the page budget;
- the single wire serializer and CLI/MCP parity;
- the P05 embedding-input measurement.

It records the outcomes the plan's Verification section names, measured on the final
code, and the phase-close review findings for P01-P04.

## Findings

### evidence-gate | low | Answers now appear in snippets on both corpora with ranking unchanged

**Frozen reference vault, 36 blind cases** (`src/vaultspec_rag/tests/quality/evidence_baseline.json`):

| Measure | Before | After |
| --- | --- | --- |
| hit@1 | 0.528 | 0.528 |
| MRR | 0.665 | 0.665 |
| Evidence in snippet | 0/36 | 15/36 |
| Section match | not reported | 18/36 |
| Hits with a line span | 0 of 360 | 360 of 360 |

Every span is verbatim at its reported lines.

**The issue's query sets, re-run on the vaultspec-core vault:**

| Set | hit@1 | MRR | Evidence in snippet | Section |
| --- | --- | --- | --- | --- |
| Dev (21) | 0.81 (unchanged) | 0.853 (unchanged) | 15 (was 0) | 15 (was 0) |
| Held-out (18) | 0.722 (unchanged) | 0.797 (unchanged) | 11 (was 1) | 11 (was 0) |

- The existing intent-ranking and testimonial gates pass on the final code.
- The issue's paragraph-level reference engine scored 18/21 and 13/18. The remaining gap
  is evidence that lies outside the two chunks a result scores; the research's
  runner-up finding measured the same ceiling.

### heading-path-embedding | medium | The section path adds nothing measurable to the vault embedding input and displaces a record from small pages; not shipped

**First measurement, confounded.** The first P05 run changed two things at once: it
added the section, and it changed the join from `title` + blank line to
`title :: section` + newline. On the frozen gates:

- MRR fell from 0.665 to 0.659.
- Section match fell from 18/36 to 17/36.
- The testimonial gate failed: `adr/2026-06-12-service-concurrency-adr` dropped out of
  the top five for "decision on gpu lock scope".

**Controlled comparison.** Each variant built fresh indexes of two corpora in one
GPU session, with per-query ranks recorded:

- the frozen reference vault, covering the evidence, intent-ranking and testimonial
  gates;
- a snapshot of the vaultspec-core vault at `1a236b8a` (869 records), for the issue's
  dev (21) and held-out (18) sets.

The shipped input reproduced every previously recorded figure. Its repeat run moved no
query, so the harness is deterministic and every movement below comes from the
input.

| Input | Frozen MRR | Section | Intent NDCG@10 | Testimonial rank | Dev MRR | Held-out MRR |
| --- | --- | --- | --- | --- | --- | --- |
| Shipped: title, blank line, text | 0.665 | 18 | 0.7709 | 2 | 0.853 | 0.797 |
| Format only: title, newline, text | 0.664 | 17 | 0.7706 | 2 | 0.853 | 0.797 |
| Section, shipped format | 0.666 | 18 | 0.7700 | out | 0.857 | 0.797 |
| First P05 input | 0.659 | 17 | 0.7703 | out | 0.857 | 0.798 |
| Leaf heading only, shipped format | 0.666 | 18 | 0.7690 | out | 0.857 | 0.797 |

- **No headline movement.** hit@1, evidence-in-snippet and external section match do
  not move for any input.
- **Section-bearing gains.** Each gains at most one rank on one query per set: dev q17
  4→3, and held-out h06 7→6 for the first input only.
- **Format caused the first run's losses.** The MRR and section-match drop came from the
  join. Format alone drops case e35 from rank 10 off the page, which costs the section
  match.
- **The section caused the testimonial failure,** in every form. The same query at ten
  results still ranks the ADR third. A five-result page reranks only 20 chunk
  candidates (`src/vaultspec_rag/search/_searcher.py:768`), and the section words move
  that record's chunk out of them. The template-name mechanism the first run guessed at
  is not needed to explain it.

The input stays `title` + blank line + chunk text (`src/vaultspec_rag/indexer/_slicing.py`
`vault_embed_input`). The section path buys no measurable ranking and costs a
pre-declared authority on small pages. `2026-06-12-service-concurrency-adr` D8's
amendment states the controlled result.

The same displacement bears on search-latency: a smaller candidate window makes it more
likely.

### search-latency | medium | Median vault search time fell 38% but missed the plan's half-of-fp32 target

Server-side time for a 10-result vault search:

- **fp32 baseline:** 1.140 s.
- **fp16 alone:** 0.43 s.
- **Final:** 0.712 s median over 18 searches (p90 1.196 s); rerank 0.403 s, passage
  scoring 0.222 s.
- **Target:** ≤ 0.570 s. Missed.

Passage scoring costs about 2.8 ms per pair at fp16, not the 1-2 ms
`2026-09-23-vault-result-evidence-research` estimated. Batch size and length-sorted
batching changed nothing; the cost is compute-bound in tokens.

A 48-pair rank-ordered page budget (`28ca88da`) cut passage time from 0.33 s to 0.22 s.
Evidence, section and ranking stayed identical on every set.

The chunk rerank alone is 0.40 s. Reaching 0.57 s needs a change to it: a smaller
candidate window or a shorter token bound. Either one changes ranking.

A service run with `VAULTSPEC_RAG_RERANKER_MAX_LENGTH=512` (chunks truncated at 512
tokens instead of 1024) on the issue's query sets:

| Set | hit@1 | MRR | Evidence in snippet |
| --- | --- | --- | --- |
| Dev | 0.81 → 0.762 | 0.853 → 0.829 | 15 → 12 of 21 |
| Held-out | 0.722 → 0.778 | 0.797 → 0.824 | 11 → 9 of 18 |

Ranking moved in both directions and evidence fell on both sets. Latency from that run
was discarded: it ran while another GPU consumer was active on the host.

### reindex-remedy | low | The service-level latest-failure finding pointed at logs for a refused index; resolved

- Project `status` names `vaultspec-rag index --rebuild --type <source>` under each
  source whose job was refused (`362df18c`).
- The service-level "latest indexing job failed" finding in `server status` offered
  only the job log, because its health record carried no source.
- Resolved in `9ed425af`. The health rollup carries the failed job's source, read
  through the accessor that handles both job record shapes
  (`src/vaultspec_rag/server/_lifespan.py:1077`). One remedy function serves the
  service finding and the per-domain one (`src/vaultspec_rag/cli/_status_labels.py:674`).
  The resilience integration test caught managed jobs, whose source lives in the job
  spec, before the accessor was used.

### inference-levers | medium | fp16 accumulation cuts both reranker forwards by a fifth with ranking unchanged; the other levers are spent or change ranking

After the user accepted the 0.712 s median and ruled the target indicative, each
untried lever was profiled. The workload was the reranker on real vaultspec-core vault
text: 40 chunk pairs and 48 passage pairs per query, over the 21 dev queries, with
medians reported.

| Lever | Chunk rerank | Passage scoring | Outcome |
| --- | --- | --- | --- |
| Current: fp16 weights, SDPA attention | 393-402 ms | 164-178 ms | baseline, exactly repeatable |
| fp16 matrix accumulation | 313-327 ms | 135-148 ms | shipped |
| Eager attention | 734 ms | 224 ms | SDPA is already the default |

- **fp16 accumulation.** Consumer CUDA cards run fp16 products with fp16 accumulation
  at twice the fp32-accumulation rate.
  - *Scope.* The switch is process-wide, so `AcceleratorContext.half_accumulation`
    holds it only around the reranker forward, under the GPU lock
    (`src/vaultspec_rag/_gpu.py`, `src/vaultspec_rag/search/_searcher.py`
    `_predict_scores`). Toggling it per call costs nothing measurable.
  - *Score drift.* Scores move by at most 0.0064.
  - *Gates.* Both corpora keep hit@1, MRR, evidence and section match identical, and
    the testimonials pass. One intent query's NDCG@10 moved from 0.505 to 0.500.
- **Compilation and flash attention.** Neither is available on this host: no Triton
  build for Windows, and flash-attn is not installed.
- **Batching.** The library already length-sorts pairs before batching, and batch size
  changed nothing earlier.
- **Tokenization.** 40 chunk pairs take about 48 ms. It runs inside the library's
  predict, which the GPU rule sanctions calling under the lock. Moving it out would copy
  the library's predict loop to shorten lock hold time, not single-search latency.
- **Candidate window and token bound.** Both change ranking. The token bound's cost is
  recorded under search-latency. The heading-path-embedding comparison shows how a
  20-candidate window already displaces an authority.

Chunk candidates run 443 / 867 / 1024 tokens at p10 / p50 / p90. The chunk rerank is
compute-bound on those tokens, so the remaining large levers change what is scored.

**Service measurement.** A service run on the same 18 searches as the 0.712 s figure
was taken while another session's test run held the host CPU at 100%. It is discarded,
and the service figure is re-measured on a quiet host.

### repo-structural-guard | high | Two whole-tree guards failed on P01-P04 additions; resolved

The phase-close review of `bd825c2f`..`32bcda8a` found two guard failures.

- `test_no_large_duplicate_function_bodies` failed:
  - `_sentences` and `_words` in `src/vaultspec_rag/_markdown_passages.py` differed only
    by a regex;
  - `vault_indexed_metadata` gained a ninth entry and matched an unrelated serializer.
- `test_no_test_substitutes_production_behaviour_undeclared` failed on the older-schema
  checkpoint test.

Resolved in `dc84c110` (one pattern-taking splitter) and `87a634a4` (the shape
registered as serialisation, the substitution declared with its reason).

### step-verification | medium | Step checks never ran the tier that holds whole-tree guards; resolved

The S04-S07 verify rows ran touched-file suites, which is why the guards above shipped
red. After the fixes, the no-accelerator lane (`python -m dev test python`) ran 5363
passed and 3 failed. The three failures fail identically at `799b4dc3`, before this
feature:

- `test_cli.py::TestHelpCleanup::test_status_help_clean`
- `test_docs_cli_surface.py::test_cli_reference_is_generated_from_live_surface`
- `dev/guards/test_child_output_decoding.py::test_no_shipped_module_decodes_a_child_ambiently`

### review-lows | low | Four lower findings from the phase-close review; resolved

- **Passage-scoring OOM.** An out-of-memory error in passage scoring failed a ranked
  search. It now keeps first passages (`66526eba`).
- **Setext headings and breaks.** Setext headings were read as text, and a thematic
  break could merge into a passage. Both fixed (`dc84c110`).
- **Stale file lines in the human view.** The CLI printed a file's current lines even
  when they no longer held the snippet. It now falls back to the snippet
  (`97f0380e`).
- **Code-hit line fields in the docs.** `docs/automation.md` had dropped them; restored
  (`97f0380e`).

Each change carries a test that fails with the fix removed. After them, the evidence,
intent-ranking, testimonial and GPU integration suites pass (41), with the evidence
metrics unchanged, and the CLI/MCP parity test passes.

### plan-close-review | high | The plan cannot close while the latency target is unmet without authorization; resolved

The plan-close review of `2a2ee276`..`97f0380e` found one high finding, one medium and
four lows. The high is open; the rest are resolved.

- **High, resolved.** `P06.S09` was closed with the plan's latency criterion recorded
  as failed and no persisted authorization, so S09 was reopened.
  - The user then ruled the target indicative, accepted the 0.712 s median, and barred
    test gating of latency. The plan's Description records that authorization.
  - The ADR's evaluation gate is amended to match.
  - The ruling also put further inference levers in scope (see inference-levers).
- **Medium, resolved** (`9518b986`). A single list item or quoted line followed by `---`
  was read as a setext heading, dropping its text.
- **Lows, resolved.**
  - The audit's commit range was too narrow; corrected (`2bc25dfb`).
  - The out-of-memory arm loaded the accelerator inside `except`; fixed (`b6ec1b8e`).
  - `passage_pairs` mutated results; fixed (`b6ec1b8e`).
  - A docs line was overwrapped; rewrapped (`2bc25dfb`).

After those fixes:

- The no-accelerator lane: 5366 passed; the 3 failures predate this feature.
- The evidence, intent-ranking, testimonial and GPU integration suites and the CUDA OOM
  test: 42 passed, evidence metrics unchanged.
- The live CLI/MCP parity test passes.

### known-defects | high | The strict type gate was red and two guard tests could not fail; resolved

The user barred a pull request while any known defect remains.

- **Type gate.** A package-wide strict basedpyright run, the check CI gates on, found
  ten errors. Most arrived with the `fix/status-messages` merge. Each was typed at its
  source rather than suppressed (`d5cdd826`).
- **Child-output decoding.** The guard that predates this feature now passes: both
  probes decode child output as UTF-8.
- **Vacuous guards.** Two negative assertions in
  `src/vaultspec_rag/tests/test_health_degraded_clears.py` tested a substring against
  a pydantic model. The model iterates its fields, so the assertions passed whether or
  not the verdict fired. They now assert the typed `JOB_FAILED` reason, and removing
  the supersession check fails both.

### install-mode-doctor | low | The doctor's install-mode mismatch is this repository's configuration, not a defect; open for the user

- **What the doctor reports.** `vaultspec-rag server doctor` reports "install mode:
  mismatch".
  - `.vaultspec/workspace.json` declares vaultspec-rag as `tool`.
  - `.mcp.json` runs the worktree build through `uv run --no-sync python -m
    vaultspec_rag.server`, the dependency launch shape (`362bfebd`).
- **Provenance.** Both files are unchanged on this branch.
- **Why no verb fixes it.** `vaultspec-rag install --mode dev --dry-run` refuses in the
  product's own repository because its owned MCP-extra requirement has drifted.
- **Who decides.** How this repository declares itself is the user's call. `P05a.S12`
  stays open for it.

## Recommendations

- **search-latency:** A follow-on ADR must decide whether vault search trades ranking
  fidelity for latency (chunk candidate window, reranker token bound), or whether the
  plan's latency target is restated as "faster than the fp32 baseline". Either choice
  should be measured on the evidence, intent-ranking and testimonial gates, which now
  make that measurable.
- **heading-path-embedding:** Amend `2026-06-12-service-concurrency-adr` D8 with this
  finding, as the ADR's gate condition requires.
- **evidence-gate:** Any later chunking experiment (smaller or heading-aligned chunks)
  should target the out-of-chunk misses and be judged on the evidence gate first.
