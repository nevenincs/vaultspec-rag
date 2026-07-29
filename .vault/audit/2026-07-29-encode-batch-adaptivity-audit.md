---
tags:
  - '#audit'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
  - "[[2026-07-29-encode-batch-adaptivity-adr]]"
---

# `encode-batch-adaptivity` audit: `feature branch review, token-budget encode core and degradation truth`

## Scope

Formal read-only review of the complete feature branch (16 commits, merge base
`45b96e5b`, tip `5e8e6abf`) executing the accepted decision: token-budget bucket
planning with a token-denominated learned ceiling, bucket-scoped OOM retry via
per-bucket library encode calls under per-bucket GPU-lock holds, and
encode-stage observability with a rate-vs-self-baseline degradation input.
Audited dimensions: OOM-retry safety and correctness, project-rule conformance
(GPU discipline, canonical code, code-stands-alone, service surface, test
integrity), ADR conformance, and quality including registry-read concurrency.
Verdict: pass-with-findings; no critical findings; two high findings require
resolution before merge and were dispatched back to executors in-session.

## Findings

### config-doc-gate | high | new env vars undocumented; documentation gate red

`ENV_OVERRIDE_MAP` gained the encode token-budget and chars-per-token variables
(`src/vaultspec_rag/config/_types.py:140`) with no entry in the configuration
reference, so `test_configuration_doc.py::test_every_declared_variable_is_documented`
fails on the branch. An operator hitting encode OOMs has no discoverable way to
lower the token budget. The step's gate set never ran the documentation test;
it was masked in wider sweeps by a pre-existing unrelated failure sorting ahead
of it.

### calibration-guard-missing | high | the ADR's third guard test was never delivered

The accepted decision names three prove-can-fail guards; the calibration guard
("goes red when the estimator under-plans by more than its stated margin") was
not written, and no margin is stated in the tree. Nothing bounds
`ceil(len(text) / chars_per_token)` against real tokenisation, so a tokenizer or
content-mix change that makes the estimator under-plan by 2x stays green while
the OOM counter climbs in production. This is ADR-to-plan drift: the plan row
for the test step never carried the constraint forward, and the executor
delivered the plan faithfully.

### calibration-divisor | medium | estimator divisor contradicts the project's own conservative calibration

`embedding_encode_chars_per_token = 4` sits on the memory-safety path while the
existing `document_chunk_chars_per_token = 3` is documented as deliberately
conservative for token-dense content. Symbol- and numeric-dense code slices can
present ~32,000 real tokens against a 24,000 estimate, re-admitting the OOM
class on exactly the corpus profile of the originating incident (each collision
costing a discarded bucket, a cache flush, and a halved learned ceiling).

### verdict-evidence-split | medium | verdict and published evidence are independent reads of a live record

The jobs enrichment computes the rate baseline once for publication and the
degradation verdict recomputes it from scratch (`src/vaultspec_rag/server/_routes_jobs.py:482`
vs `:647`); the reporter thread can mutate the registry between the reads, so an
operator can see a degraded verdict whose own attached evidence shows a ratio
above the threshold. Secondary cost: repeated locked linear registry scans per
job on the enriched path.

### forward-items-ambiguity | medium | one field carries two meanings inside a slice

`forward.items` is the slice chunk count at slice entry but the completed-so-far
count at bucket boundaries; the CLI renders it as "{items} items" implying slice
size throughout (`src/vaultspec_rag/cli/_service_jobs_presentation.py:327`). An
operator inspecting a degraded 512-chunk slice mid-encode reads "64 items" as
the slice size.

### probe-credit-after-oom | low | a colliding call banks a recovery success

`record_success(budget)` runs even when the call absorbed an OOM
(`src/vaultspec_rag/embeddings.py:1013`, `:1165`), so the recovery probe fires
one call early after every OOM. Harmless at one in sixteen.

### concat-outside-ladder | low | the output concatenation cannot be absorbed by the ladder

The final tensor concatenation allocates outside the bucket try/except
(`src/vaultspec_rag/embeddings.py:1017`), so an OOM there propagates to the
slice instead of shrinking a bucket. Allocation is small (N x dimension).

### unread-progress-fields | low | two seam fields have no production consumer

`EncodeBucketProgress.items_total` and `.bucket_estimated_tokens` are populated
and asserted in tests but read by no production consumer.

### floor-guard-specificity | low | the floor guard accepts any conditional bare raise

The repointed OOM-floor guard accepts any `If` containing a bare `raise` in the
handler without asserting the condition tests bucket size; an unrelated
conditional re-raise would satisfy it.

### ratio-composition-reads | low | ratio numerator and denominator from separate locked reads

`progress_rate` and `progress_rate_baseline` are read under two lock
acquisitions (`src/vaultspec_rag/server/_routes_jobs.py:392`), so the published
ratio can compose values from different registry states.

### verified-clean | low | dimensions audited with no finding

OOM replan correctness (contiguous half-open buckets, provable termination to
the single-item floor, no re-encode of completed outputs, sparse mirroring
dense); allocator flush only inside the two OOM handlers; GPU-lock brackets
per-bucket forward-only with no double or missing hold and no searcher
self-deadlock; callback safety (reporting failures can never discard encoded
buckets); rate-history writes and reads under one lock; null-safety of every
new field for jobs predating them; canonical-code (ladder tests genuinely
repointed, no shims or count-based remnants); code-stands-alone clean including
an empty diff under the vault and harness trees; service-surface (verdict in
the service, CLI formats published numbers only); test integrity (both shipped
guards fail on their named assertions under their stated mutations; the
rate-baseline test replays real progress through the production registry with a
steady-rate control). The implementation was judged a faithful execution of the
accepted decision in every load-bearing respect, with the calibration surface
(the decision's one acknowledged new risk) left unmeasured and untested by the
two high findings.

### env-example-coverage | high | second documentation surface for the new env vars

`test_env_example_coverage.py::test_env_example_documents_every_env_var` also
fails on the branch: `.env.example` requires a commented default line with a
cost-stating prose comment for both new variables. Extends the config-doc-gate
finding; documenting only the configuration reference leaves the gate set red.

### duplicate-function-bodies | high | the structural dedup guard names four groups introduced by the branch

`test_process_probe_source_structure.py::TestNoStructurallyIdenticalFunctions::test_no_large_duplicate_function_bodies`
names four identical-body groups containing symbols this diff introduced:
`_encode_evidence`/`_rate_evidence` and `encode_telemetry`/`forward_telemetry`
in `src/vaultspec_rag/jobs.py`, `_job_encode`/`_job_forward` in
`src/vaultspec_rag/server/_routes_jobs.py`, and `_measure` in the presentation
duplicating `_signal_measure` and the TUI's `_opt_float`. A hardening applied
to one copy silently misses the others - the drift class the canonical-code
rule exists to prevent. This finding supersedes the canonical-code clean line
in the verified-clean entry above: that line was reasoned by eye and is
retracted; the repo's structural guard disagrees. A fifth group
(`_index_breadth.py` meta-path pair) fails the guard at the merge base already;
the branch's obligation is returning the offender set to that base state by
merging each new group behind one implementation, not allowlisting.

### base-ab-triage | low | remaining canonical-lane failures classified against a clean base checkout

A/B in a clean detached checkout of the merge base settled every open
attribution: `test_substitution_discipline`,
`test_watcher_transition_logging`, the duplicate-bodies guard's fifth group,
the ownership-guard rebinding failure, and the jobs-route auth payload
assertion all fail at base and are pre-existing on the default branch, outside
this feature's scope. The canonical test lane at the reviewed tip therefore
carries exactly three branch-caused reds (the two documentation surfaces and
the duplicate-bodies groups), all dispatched in-session.

## Recommendations

- Document both encode env vars in the configuration reference AND the
  operator env template (closes config-doc-gate and env-example-coverage);
  dispatched in-session to the telemetry executor.
- Merge each newly-duplicated function group behind one implementation so the
  structural guard's offender set returns to its merge-base state (closes
  duplicate-function-bodies); dispatched in-session to the telemetry executor.
- Deliver the calibration guard with a stated margin measured against the real
  pinned tokenizer on a token-dense worst-case corpus, and reconcile the
  estimator divisor with the measurement (closes calibration-guard-missing and
  calibration-divisor); dispatched in-session to the encode-core executor.
- Thread the once-computed rate baseline into the degradation verdict so the
  verdict and its evidence share one read (closes verdict-evidence-split);
  dispatched in-session to the telemetry executor.
- Render the bucket-boundary items count distinctly from the slice size in the
  jobs presentation (closes forward-items-ambiguity); dispatched in-session.
- The four low findings are deferred with this record as their home; none
  blocks merge. The median-baseline blind spot (a collapse occupying more than
  half a run drags the median down to itself and the verdict back to healthy)
  is an accepted limitation of the decided statistic; changing the baseline
  statistic is a decision a follow-on amendment to the governing decision
  record must make, informed by production telemetry.
