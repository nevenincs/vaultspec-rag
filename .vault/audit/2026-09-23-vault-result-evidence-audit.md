---
tags:
  - '#audit'
  - '#vault-result-evidence'
date: '2026-09-23'
modified: '2026-09-23'
body_schema: 'body-v2'
body_hash: 'sha256:f205ee8012acc7c4f83124b8aa4678fd6d0bd51cf8cd380c3ecb247fcb64963c'
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

### heading-path-embedding | medium | The section path in the vault embedding input regresses ranking and was not shipped

With `title :: section` prepended to the vault embedding input, measured on the frozen
gates against the same code without it:

- MRR fell from 0.665 to 0.659.
- Section match fell from 18/36 to 17/36.
- The testimonial gate failed: `adr/2026-06-12-service-concurrency-adr` dropped out of
  the top five for "decision on gpu lock scope".

The same gates at `32bcda8a` pass 11 of 11.

Per the ADR's gate condition, the input stays `title` + blank line + chunk text,
byte-identical to before (`src/vaultspec_rag/indexer/_slicing.py`
`vault_embed_input`). Only the single builder and full-input donor verification shipped
(`2a2ee276`). Template section names such as "Implementation" or "Considered options"
recur across every record, which is the likely mechanism; it was not isolated further.

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

### reindex-remedy | low | The service-level latest-failure finding still points at logs for a refused index

- Project `status` names `vaultspec-rag index --rebuild --type <source>` under each
  source whose job was refused (`362df18c`).
- The service-level "latest indexing job failed" finding in `server status` still
  offers only the job log. Its health record carries no source
  (`src/vaultspec_rag/server/_lifespan.py:1077-1085`).
- That area belongs to the in-flight `status-messages` work and was left untouched.

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

### plan-close-review | high | The plan cannot close while the latency target is unmet without authorization; open

The plan-close review of `2a2ee276`..`97f0380e` found one high finding, one medium and
four lows. The high is open; the rest are resolved.

- **High, open.** `P06.S09` was closed with the plan's latency criterion recorded as
  failed and no persisted authorization. S09 is reopened pending the user's decision
  between restating the target and a follow-on decision on the chunk rerank (see
  search-latency).
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

## Recommendations

- **search-latency:** A follow-on ADR must decide whether vault search trades ranking
  fidelity for latency (chunk candidate window, reranker token bound), or whether the
  plan's latency target is restated as "faster than the fp32 baseline". Either choice
  should be measured on the evidence, intent-ranking and testimonial gates, which now
  make that measurable.
- **heading-path-embedding:** Amend `2026-06-12-service-concurrency-adr` D8 with this
  finding, as the ADR's gate condition requires.
- **reindex-remedy:** Carry the failed job's source on the service health record, so
  the service-level finding can name the same rebuild command. Done under the
  `status-messages` feature.
- **evidence-gate:** Any later chunking experiment (smaller or heading-aligned chunks)
  should target the out-of-chunk misses and be judged on the evidence gate first.
