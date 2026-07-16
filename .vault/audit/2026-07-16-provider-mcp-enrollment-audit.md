---
tags:
  - '#audit'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# `provider-mcp-enrollment` audit: `S51 correction review`

## Scope

Review the S51 correction for structured project-surface diagnostics, fail-before-
mutation topology safety, Core 0.1.45 filesystem compatibility, real-test integrity,
and the bounded verification claims needed before the independent S52 release audit.

## Findings

### project-surface-probe | high | Raw diagnostic read could block or skip unsafe nodes

The first review found that `Path.exists()` followed by unrestricted `read_text()`
could block on a POSIX FIFO after topology preflight had already refused it. A broken
relative project symlink returned false from `exists()` and therefore retained the S50
report truncation. The correction now classifies with non-following `lstat`, decodes
only verified regular files, and maps every non-regular project node directly into the
shared MCP-extra and requested torch-config inspection-error contract.

Real directory and broken-relative-link cases preserve exact topology and populate both
component error fields plus the generic topology diagnostic. A capability-defined FIFO
case uses a bounded real worker and cleanup unblocking path without a skip marker, mock,
patch, or fake. The final Windows-accessible surfaces pass 58 torch-config tests and 183
install integration tests under Core 0.1.45; Ruff, formatting, Ty, BasedPyright,
complexity, and diff hygiene are green. The finding is resolved in S51.

### linked-project-false-positive | high | Valid live project links were reported as unreadable

The first correction treated every project symlink as an inspection error. A valid
live relative link inside the workspace is supported topology, so an unrelated required
node failure could incorrectly mark MCP-extra and torch-config inspection as failed.
The final implementation opens project content through a nonblocking descriptor,
validates the opened node with `fstat`, prevents link following where the platform
supports it, and resolves only live relative targets that remain inside the workspace.

The matrix regression proves that a valid live relative project link remains readable
when an unrelated workspace node triggers topology refusal: component actions stay
skipped, the generic topology error remains, and link plus target bytes are unchanged.
Broken, directory, and special project nodes continue through the shared component-error
contract. The finding is resolved in S51.

S51 verdict: **PASS — no actionable findings after resolution of both HIGH review
findings**. This verdict is limited to the corrective surface and does not grant
release readiness.

## Recommendations

Run S53 from a clean commit and restart every package, provider, host-recognition, and
publication gate from zero. The Windows ledger is 2,269 total, 1,832 selected, and 437
excluded test items. The POSIX ledger is 2,270 total, 1,833 selected, and 437 excluded
test items; Linux CI must collect and execute the POSIX-only FIFO regression because
this Windows review cannot grant that item execution credit.

## S54 correction review

### completion-deadline-enforcement | medium | The first bounded helper could credit a late terminal response

The first S54 review found that the 120-second deadline was checked only after each
administrative poll and after terminal-state recognition. A slow request could
therefore return `done` after expiry and still pass, while the environment-configurable
per-request timeout could extend the observed wait beyond the declared completion
contract.

The final helper computes the remaining wall-clock budget before each real service
poll, supplies that value as the poll's HTTP timeout, checks expiry again after the
response, and only then accepts an exact-job terminal phase. Timeout failure retains
the final job payload and full service envelope. The existing exact `done` assertions
remain authoritative, so `error` and `failed` responses terminate polling without being
converted into success. The finding is resolved in S54.

S54 verdict: **PASS — no actionable findings after resolution of the MEDIUM
deadline-enforcement finding**. This verdict is limited to the job-completion test
correction and does not grant release readiness or waive the complete platform-aware
release campaign.

## S56 bounded fixture review

### intent-corpus-gold-selection | high | Gold-aware corpus narrowing invalidates the established ranking gate

The process boundary correctly bounds the complete child-side model construction,
indexing, reranker load, and query execution, and the real GPU selector and four-test
module terminate green. The same change replaces the quality gate's established full
real-vault corpus with a 50-document subset selected from the seven features already
named by the labeled query set. `_feature_corpus_sources` admits every gold exec stem
while admitting only the first three non-gold exec links per feature; `_copy_feature_corpus`
therefore uses the judgment set itself to decide which competing documents may enter the
retrieval corpus. The original baseline indexed 694 real vault documents specifically so
ADRs, research, plans, exec records, and unrelated vocabulary genuinely competed; the
current vault contains 1,111 Markdown documents, of which this harness indexes 50. A
four-of-four green result on the reduced set cannot establish the accepted full-corpus
ranking contract and can hide regressions by removing hard negatives. The exact
`corpus_documents == 50` assertion also turns incidental feature-index growth into a
brittle test failure rather than proving a semantic corpus invariant.

Recommendation: keep the whole-fixture process boundary, but build the child corpus by
copying the full real vault under the same exclusions as the established harness. If
runtime needs reduction, define and approve a retrieval-quality sampling contract that
is independent of gold judgments, includes deterministic hard negatives, and is
validated against the full-corpus baseline before replacing the gate.

### partial-cache-completeness | medium | Config-only cache detection disables bounded online repair

`models_are_cached` and `ensure_model_snapshots` classify a repository as complete when
`try_to_load_from_cache` finds only `config.json`. That API answers whether one named file
exists; it does not establish that model weights, tokenizer assets, SentenceTransformers
modules, sparse-encoder files, or reranker files are present. An independent real cache
probe created a valid Hugging Face snapshot layout containing only `config.json`, and
`models_are_cached` returned true. An interrupted cold download commonly reaches config
metadata before all large blobs, so the intent worker then chooses `--local-files-only`
and the shared embedding fixture skips the acquisition worker. Both fail locally instead
of using the supported, deadline-bounded online path to repair the partial cache. The two
new HTTP regressions cover empty-cache timeout and final-response retention, but neither
covers this warm/partial boundary.

Recommendation: make cache readiness reflect the loader's actual required snapshot, or
run the bounded online-capable child whenever cache-only construction has not been proven
successful. Add a real partial-cache regression that begins with genuine repository
metadata/config but missing model assets, permits the local endpoint or supported online
source to complete the snapshot under the deadline, and then proves cache-only real model
construction succeeds.

The direct-process timeout and termination path is sound for the current Hugging Face
threaded downloader and embedded Qdrant worker on Windows and POSIX: timeout failure
terminates the child, escalates to kill after five seconds, retains a bounded output tail,
and the real loopback 504 tests pass. Keyword-only `local_files_only=False` defaults keep
normal `EmbeddingModel` and `VaultSearcher` callers online-capable, while the explicit
true path reaches dense, sparse, and reranker constructors. Test modules already ship
inside the package, so the private `-m` workers add no new package-inclusion boundary.

S56 review verdict: **FAIL — one HIGH quality-gate validity finding and one MEDIUM
partial-cache recovery finding remain actionable**. The timeout mechanism itself is
bounded, but release evidence cannot rely on the gold-aware 50-document corpus and the
cache decision does not preserve supported repair after an interrupted download.

## S56 final remediation verification

Both independent findings are resolved.

The intent-ranking worker now copies the complete project `.vault` through one
unconditional `shutil.copytree`, excluding only `data` and `*.lock`. No
feature-list, manifest traversal, gold-stem admission, or judgment-conditioned
selection remains. Gold judgments are used only to assert that labeled documents exist
after the copy. An independent filesystem comparison produced 1,111 expected source
files and 1,111 copied files with no missing or extra paths, and the corpus assertion
compares the child evidence to the current complete-vault Markdown count. The real-GPU
module passed four of four tests in 131.71 seconds, including 131.00 seconds of bounded
whole-fixture setup, while the Hugging Face endpoint was unreachable and the 600-second
deadline remained authoritative. The HIGH `intent-corpus-gold-selection` finding is
closed.

Cache readiness now resolves the local snapshot offline, requires config and tokenizer
artifacts, and distinguishes unsharded weights from indexed weights. Once a valid
non-empty weight index is present, only complete existence of every referenced shard
can return true; the unsharded `*.safetensors` and `pytorch_model*.bin` fallback is
unreachable for an incomplete indexed snapshot. The committed real-endpoint regression
seeds config, tokenizer, a two-shard index, and only shard one before asserting that the
cache is incomplete and bounded online acquisition is attempted. An independent probe
reproduced false with one shard and true after adding shard two. The persistent delayed
504 and immediate 504 regressions pass two of two, retaining the deadline, model ID,
endpoint, final metadata URL, and response diagnostics. The MEDIUM
`partial-cache-completeness` finding is closed.

Ruff, BasedPyright, focused endpoint tests, six-item collection, and `git diff --check`
are green. The keyword-only production defaults remain online-capable, explicit
cache-only behavior reaches dense, sparse, and reranker loading, direct child
termination remains bounded on Windows and POSIX for the current workers, and no
package-inclusion or service-orphan regression was identified.

S56 final review verdict: **PASS — no actionable findings remain in the bounded model
fixture remediation**. This verdict closes the S56 corrective surface only; the complete
platform-aware release campaign still starts from zero and retains its independent gate
requirements.
