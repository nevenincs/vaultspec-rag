---
tags:
  - '#audit'
  - '#adr-plan-coverage-triage'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - "[[2026-07-25-index-drift-circuit-accounting-adr]]"
  - "[[2026-07-25-document-index-drift-parity-adr]]"
  - "[[2026-07-24-vault-true-incremental-adr]]"
  - "[[2026-07-23-ci-self-hosted-gpu-runner-adr]]"
  - "[[2026-07-21-preprocess-batch-hooks-adr]]"
  - "[[2026-07-14-qdrant-long-paths-adr]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-06-13-provisioning-setup-adr]]"
  - "[[2026-03-07-mcp-sync-tools-adr]]"
  - "[[2026-07-25-index-resume-drift-race-plan]]"
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# `adr-plan-coverage-triage` audit: `plan coverage for the nine ADRs with no plan`

## Scope

Nine accepted ADRs carried no implementation plan. Each was read whole, its
decided behaviour located in the current source by meaning and confirmed by
symbol, and classified as implemented, partially implemented, superseded, or
untouched.

A completion figure was treated as evidence of nothing. The corpus had just been
reconciled after twenty-four plans reporting "Planned, 0%" turned out to describe
finished work in a pre-taxonomy format, so plan state was read only to locate
candidate coverage and every verdict below rests on source read in the tree at
`f4118867`.

Verdicts: one live and unbuilt, seven already delivered, one already retired in
place. Nothing is recommended for archiving.

## Findings

### vault-true-incremental-unbuilt | high | the only decision of the nine with no implementation

`[[2026-07-24-vault-true-incremental-adr]]` decides that vault change detection
splits its fingerprint into a normalized-body digest and an
indexed-frontmatter-subset digest, excluding the volatile `modified:` stamp.
None of it exists. `_hash_documents`
(`src/vaultspec_rag/indexer/_vault_indexer.py:642-662`) still calls
`hashlib.file_digest(f, "blake2b")` over the raw whole file, and the sidecar
write at `src/vaultspec_rag/indexer/_vault_indexer.py:971-984` does the same. A
search for `body_hash`, `frontmatter_hash`, `subset_hash`, and
`indexed_frontmatter` across the package returns nothing. The second amplifier
the ADR names is also still live: the watcher's escalation to an unscoped
full-corpus pass remains at `src/vaultspec_rag/watcher_retry.py:255` and
`src/vaultspec_rag/watcher.py:1648`, reached through
`_retry_generation_for_attempt`. The modules moved out of `server/` since the ADR
was written, but the behaviour is unchanged.

### drift-circuit-accounting-delivered | low | delivered under an existing plan step

`[[2026-07-25-index-drift-circuit-accounting-adr]]` decides the breaker counts
faults only and drift gets its own counter reported alongside job state. Both
halves are in the tree. `CodeDriftOwner.snapshot`
(`src/vaultspec_rag/indexer/_drift_owner.py:112-127`) states the rule in its own
docstring - a remediated run succeeds, so the breaker never hears about it - and
returns the separate `superseded_paths`, `deferred_paths`, `collisions_observed`,
and `retry_budget` counters. `_generation_lifecycle.py:109-116` exposes them as
`drift_snapshot()`, and `_codebase_indexer.py` threads `drift=` onto every
result-construction site (1034, 1051, 1922, 2162, 2377). The job record carries
the field with the matching rationale at `src/vaultspec_rag/jobs.py:571-578`.

This ADR is already governed by `[[2026-07-25-index-resume-drift-race-plan]]`,
which lists it in `related:` and closes it as step `W03.P05.S11` - "Count faults
only in the circuit breaker and record drift outcomes in their own counter
reported alongside job state" - against
`src/vaultspec_rag/indexer/_run_policy.py`. That plan is complete. A second plan
would fragment tracking across concurrent plans for one decision.

### document-drift-parity-satisfied | low | a scope decision, satisfied by construction

`[[2026-07-25-document-index-drift-parity-adr]]` decides that the document index
does **not** adopt the drift signal; its own Implementation section reads
"Nothing is implemented in the document index." The tree matches: the document
indexer builds its result with `reuse=` and no `drift=`
(`src/vaultspec_rag/indexer/_document_indexer.py:766`), and `CodeDriftOwner`
remains a code-index component with no document-side caller. This ADR is also
listed in `[[2026-07-25-index-resume-drift-race-plan]]`'s `related:`. It is
unplannable by construction - there is no work it authorises - and it stays live
because it governs a future contributor's decision to copy the mechanism across.

### ci-gpu-runner-delivered | low | delivered, with the trigger narrowed by a later revision

`[[2026-07-23-ci-self-hosted-gpu-runner-adr]]` decides a tier split with the GPU
tier on a self-hosted runner behind a trusted-event gate. The `gpu-tests` job
exists at `.github/workflows/ci.yml:145-222`: `runs-on: [self-hosted, windows,
gpu, cuda]`, a CUDA visibility check, Qdrant binary provisioning, `HF_TOKEN` from
a repo secret, and the tier driven through the shared `just dev test gpu` recipe
(`justfile:289-324`), with `.github/actionlint.yaml` enumerating the custom
labels.

Two divergences, both later revisions rather than gaps. The gate is
`github.event_name == 'workflow_dispatch'` (`ci.yml:173`), strictly narrower than
the ADR's `!= 'pull_request' || head.repo.full_name == github.repository`; the
in-file comment records why - on a single GPU runner shared with the live
service, auto-running on every push wedged the runner and shared-GPU contention
made results non-deterministic. The security property the ADR called load-bearing
is preserved and strengthened, since `workflow_dispatch` requires write access.
Separately, the cheap tiers the ADR placed on GitHub-hosted Linux now also run on
`[self-hosted, Linux, X64]`. Neither divergence is a defect; both are undocumented
relative to the ADR.

### preprocess-batch-hooks-delivered | low | opt-in batch manifest is shipped

`[[2026-07-21-preprocess-batch-hooks-adr]]` decides an opt-in `batch = true`
manifest invocation. The validation the ADR's constraints specify - `batch` valid
only on a `command` rule carrying `{paths}`, rejected with `{path}` or
`entry_point` - is at `src/vaultspec_rag/indexer/_preprocess_config.py:564-587`.
Manifest substitution with injection neutralisation is at
`src/vaultspec_rag/indexer/_preprocess_runner.py:539`, per-rule grouping before
pool dispatch at `src/vaultspec_rag/indexer/_chunk_producer.py:286`, and batch
dispatch at `src/vaultspec_rag/indexer/_chunk_worker.py:301,646,1108,1143`. The
rule's `batch` flag is surfaced through the CLI at
`src/vaultspec_rag/cli/_preprocess.py:118` and carried in the config epoch at
`src/vaultspec_rag/indexer/_config_epoch.py:196,291`.

### qdrant-long-paths-delivered | low | verbatim child paths shipped with a regression test

`[[2026-07-14-qdrant-long-paths-adr]]` chose extended-length (`\\?\`) paths for
the Qdrant child's storage env. `_qdrant_child_path`
(`src/vaultspec_rag/qdrant_runtime/_supervise.py:103-127`) implements exactly
that: absolute-resolve, then `\\?\` for drive paths and `\\?\UNC\` for UNC,
passing through non-Windows and already-prefixed paths. The dedicated regression
test the ADR required spawns a supervisor against a storage dir padded past 140
characters and creates a real collection
(`src/vaultspec_rag/tests/integration/test_qdrant_long_paths.py:29-68`).

### mcp-search-scope-delivered | low | delivered and mechanically guarded, amendment included

`[[2026-06-30-mcp-search-scope-adr]]` is `accepted` and carries its own SB7
amendment restating the surface parametrically per content kind. The guard its
Consequences demanded exists and enforces the amended tool set rather than the
superseded five-name one: `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`
asserts the surface is exactly the search, refresh, convenience, status, and
clean tools (`:81`), that no admin or lifecycle tool survives (`:84`), the
read-only and idempotent annotations (`:87`), refresh non-destructiveness
(`:95`), explicit destructive annotation on the clean tools (`:104`), absence of
a destructive clean input on refresh (`:113`), display titles (`:122`), and a
declared output schema (`:144`).

Corrected on 2026-07-26 by
`[[2026-07-26-adr-plan-coverage-triage-corpus-reconciliation-audit]]`: the guard
enforces the amended tool *set*, but not as a parametric *rule*. SB7's own prose
claims the guard was changed to assert a rule "rather than a frozen five-name
list"; it is a twelve-name literal set at `:31-44`. The delivery verdict stands;
the original wording here overstated what the guard does.

### provisioning-setup-delivered | low | front door and readiness verb both shipped

`[[2026-06-13-provisioning-setup-adr]]` decides a unified opt-out setup front
door plus a readiness verb. The front door is `install`
(`src/vaultspec_rag/cli/_install.py:51`), carrying `--local-only`
(`:183-186`), the finer per-dependency skips mapped onto the provisioning skip
token set (`:259-270`), `dry_run`, and the shared sync vocabulary through
`install_run` (`:272-290`). The readiness verb is `service doctor`
(`src/vaultspec_rag/cli/_service_doctor.py:36-43`), which reports the two axes
the ADR named - installed dependencies via `api.get_readiness` (torch, models,
the Qdrant binary on disk) and the live service.

### mcp-sync-tools-already-retired | low | retired in place; archiving would take 77 documents

`[[2026-03-07-mcp-sync-tools-adr]]` is the strongest retirement candidate by age
and is already retired correctly: frontmatter carries `superseded_by:
'2026-06-18-mcp-service-client-adr'` and its heading reads `(**status:**
`superseded`)`. It is the one supersession marker among the nine, and it needs no
further action.

Archiving it is not available as a targeted operation and would be destructive.
Its feature tag is `#gpu-rag-stack`, not a tag of its own, so
`vaultspec-core vault feature archive gpu-rag-stack --dry-run` reports **77
documents** moving to `.vault/_archive/`, including ten still-governing
foundational ADRs - `2026-03-06-gpu-only-rag-stack`,
`2026-03-07-blake2b-file-hashing`, `2026-03-07-manual-node-walking`,
`2026-03-07-path-resolve-engine-cache`, `2026-03-07-qdrant-filter-on-prefetch`,
`2026-03-07-qdrant-payload-indexes-local`, `2026-03-07-qwen3-no-document-prompt`,
`2026-03-07-score-normalization`, `2026-03-07-threading-lock-for-singleton`, and
`2026-03-07-vaultgraph-cache` - plus the project's entire early audit history.

## Recommendations

- Execute `[[2026-07-25-vault-true-incremental-plan]]`, authored against
  `vault-true-incremental-unbuilt`. It is the only one of the nine that needs
  building. Sequence it after the in-flight throughput plan, which the ADR's own
  constraints require and which shares the same files.
- Author no plan for `drift-circuit-accounting-delivered` or
  `document-drift-parity-satisfied`. Both are already carried by
  `[[2026-07-25-index-resume-drift-race-plan]]` through its `related:` frontmatter;
  the first is closed as `W03.P05.S11` and the second authorises no work at all.
  A separate plan for either would spread one decision across concurrent plans.
- Archive nothing. Every retirement candidate among the nine turned out to govern
  shipping behaviour or to be retired already. The only ADR genuinely out of force
  is `mcp-sync-tools`, which already carries its supersession marker, and the sole
  mechanism that could remove it takes 77 documents and ten live ADRs with it.
- Two divergences under `ci-gpu-runner-delivered` are undocumented against their
  ADR: the GPU tier's trigger is dispatch-only rather than trusted-event, and the
  cheap tiers moved off GitHub-hosted runners. Both are deliberate and reasoned in
  the workflow file. Whether the ADR is amended to ratify them, as
  `[[2026-06-30-mcp-search-scope-adr]]` was amended by its own SB7, is a decision
  for a follow-on record rather than this audit.
- The nineteen plans converted from the pre-taxonomy format have Steps with no
  execution records and will report them missing permanently. That is an honest
  gap in the history, not a defect, and backfilling it would fabricate a record of
  work nobody witnessed.
