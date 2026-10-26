---
tags:
  - '#audit'
  - '#stale-search-hits'
date: '2026-10-26'
modified: '2026-10-26'
body_schema: 'body-v2'
body_hash: 'sha256:9f119d05a123d5d669ad1687d793c7ae495b0ea97ba14b96d6eb5d2968e66c83'
related:
  - "[[2026-10-26-stale-search-hits-plan]]"
---

# `stale-search-hits` audit: `delivered freshness and explicit repair authority`

## Scope

Integrated review of S01 on branch `feature/stale`, including the working-tree implementation, focused guide, governing decision refinements and final verification. The scope covers final delivered pages for code, vault, documents and combined search; safe bounded file reads; publication fencing; post-response audit scheduling; canonical incremental admission and operator rebuild remediation; CLI/MCP preservation; and runtime shutdown.

Verdict: PASS. No unresolved critical, high, medium or low code findings. The principal agent performed the architecture, source/test implementation and integrated review. Delegated work was limited to read-only context, records/documentation and existing CPU test runs.

## Findings

No unresolved findings. Canonical evidence is captured before retrieval and validated after disk comparison. Unavailable, unsafe, over-budget or racing observations stay unverifiable. A single page shares file bytes across domains and charges attempted reads against its byte budget. Stale hits retain indexed snippets, scores and ordering. Vault stamp-only changes reuse the established semantic fingerprint.

The runtime coordinator owns bounded observations and one audit worker, not publication or job authority. It starts after response delivery, coalesces root/source reports, rechecks continuing drift, and requests only ordinary incremental work through the request runtime's existing JobManager. Exact projection or proven compatibility blockers, and canonical repair-job full-reindex refusals, project executable root/source/port-specific rebuild remediation. Missing/conflicting audit evidence is deferred. Shutdown closes intake and prevents late repair admission. Current verified hits retire their corresponding observation without allowing an old worker completion to overwrite newer state.

### full-matrix-vault-identity | high | Real vault proof keys differ from displayed source paths

The extended user-requested validation exposed a false-negative in the initial feature: real VaultRunCheckpoint evidence is keyed by document identity, for example `adr/stored.document`, while delivered vault paths are root-relative, for example `.vault/adr/stored.document.md`. The initial synthetic proof fixture seeded the physical path and did not expose this mismatch. Lookup by the displayed path therefore left real vault hits unverifiable. S01 is reopened; the work originally named S07 and now consolidated into S05 corrects the lookup with shared existing ID math, without migrating stored identities or changing public paths. The fork patch has real checkpoint coverage for default and alternate docs roots; original integration and live verification remain pending the accelerated baseline hold.

### full-matrix-substitutions | high | New tests introduced undeclared production behavior substitutions

The full substitution-discipline guard reports 16 new sites in `test_search_drift.py` and 6 in `test_search_hit_freshness.py`. S05 replaces convenient audit/job/route substitutes with actual file, checkpoint, store and job components, directly exercised queue policy, and actual live delivery/repair coverage. Read-sharing and send ordering use scoped real-execution profiling reviewed by the principal; no production function is replaced and no allowance/suppression is added. Original integration and live verification remain pending.

### full-matrix-pin-alignment | medium | Staged dependency update moved the client beyond the reviewed server minor

The pre-existing staged uv.lock and installed client are1.20.0; the source pin remains1.19.0, and the strict matching-minor guard correctly fails. S08 prepares reviewed 1.20.0 constants after reproducing all 6 outgoing archive and 6 outgoing executable digests, then deriving all 12 new digests through the same canonical default-source helper without executing downloads. The user explicitly approved including the existing staged dependency update with the pin change. No operator index rebuild or unrelated service upgrade is authorized by this correction.

### full-matrix-test-contracts | medium | Exact serialization and malformed-null setup need current real contracts

S04 adds the authorized freshness fields to the explicit wire-key guard while retaining rank and private-content assertions. S06 establishes malformed optional-null payloads with a real full point upsert: client1.20 payload merging removes null keys, so the old fixture did not contain the value it claimed to audit. The repaired fixture retrieves and verifies the malformed value before asserting audit rejection. Both guards have intended-failure/restored-pass evidence; no assertion is loosened to accept the old failing outcome.

### full-matrix-complexity | low | Existing Windows anchor discovery exceeds the configured limit

The full gate reports `_gather_windows_targets` cognitive score 22, unchanged before the stale-hit feature. S03 extracts precise-anchor admission while preserving client priority, main-thread resolution, fallback, deduplication and handle ownership. The isolated patch scores 10 (helper 4), passes the configured complete complexity gate and has 37 passing Windows unit cases plus 2 POSIX-only skips.

### full-matrix-prerequisites | low | Source checkout initially lacks monitor and frontend prerequisites

The initial full CPU run records 8337 passed, 40 failed, 10 setup errors and 27 skipped. Most failures/errors arise from missing source-checkout monitor pins/binary or node_modules. The supported npm-ci and develop-monitor build now succeeded, verified the pinned Bun artifact and installed a development-provenance monitor; authored package/lock files were unchanged. Final CPU rerun must re-evaluate those failures and previously prerequisite-skipped browser cases. Separate provisioning 72, Windows 90 and hosted TypeSafe 5 live cases pass. The full accelerated lane is still running under the sole supervised GPU borrower; MPS is unavailable on this Windows host.

### full-matrix-integrated-checkpoint | low | Corrections integrated; final runtime verification pending

The principal integrated the five reviewed patches after the sole accelerated borrower released its source hold. S03, S04, S06 and S08 are committed separately with explicit pathspecs, plan closures and ledger entries. The staged dependency update was included only after the user explicitly authorized it. The real-component and canonical vault identity correction is integrated but S05 remains open for actual stale-delivery/repair verification. Integrated package Ruff, format, ty, basedpyright, configured complexity including Xenon, absolute-import, nesting and Pylint gates all exit zero. The pin covering subset passes 117 cases with one existing Windows permissions skip. The original isolated guards remain byte-identical and retain their intended-failure/restored-pass evidence.

The first resident accelerated selection completed with 871 passed, 13 failed, 4 setup errors and 2 Linux-only skips. Failures show model admission refusing insufficient free GPU memory and one Windows safetensors paging-file error1455, rather than stale-hit assertion failures. The failed first invocation prevented the canonical runner from starting its subprocess-GPU selection, so that selection is explicitly scheduled after the new feature live test. Only test-owned service state may be stopped/replaced; unrelated Ollama remains untouched. The final CPU matrix is running against the integrated source with the source-checkout prerequisites prepared. Runtime evidence is still pending; these observations do not establish a final PASS.

### full-matrix-retirement-race | medium | An older current-page snapshot can remove a newer audit

Integrated review found that `SearchDriftAuditor.snapshot` captured audit objects under the lock, then later removed the root/source key unconditionally when its delivered page proved current. A concurrent newer observation could replace that key between capture and removal. S05 now includes identity-fenced atomic retirement, prepared by the principal in the isolated validation worktree while the original CPU matrix retains its source hold. A direct pure queue-policy guard proves an older observation cannot delete its replacement and that the actual current observation can retire. Removing the identity condition fails at the intended newer-observation assertion; exact restoration passes. The combined drift, freshness and substitution-discipline selection passes34 tests and scoped lint/format/ty/basedpyright/Pylint pass. Main integration remains pending CPU completion; no temporary mutation remains.

### full-matrix-cpu-reconciliation | low | Integrated CPU defects corrected and transient failures reproduced unchanged

The final canonical Python matrix (`uv run --no-sync python -m dev test python`) ran on the integrated source at95feef7c: 8403 passed,15 platform skips,3 failed,0 errors in639.64seconds. It exercised the previously missing monitor and frontend browser prerequisites. The new live observer's `isinstance(timestamp,int)` claim accepted bool and was correctly rejected by the published-value architectural guard; the principal strengthened the assertion to explicitly reject bool, with no exemption or guard change. The principal also integrated the identity-fenced retirement correction. The final focused original-checkout selection covering drift, freshness, substitution discipline, numeric narrowing and vault producers passes310 tests. Package Ruff and final affected-file format, ty and basedpyright checks all exit zero.

The extraction-space and stopped-service browser cases pass unchanged in independent Sol6.1Medium reproduction: original extraction case1pass and complete real download-fault file34pass; affected browser1pass and related browser/bridge confirmation4pass. No assertions, timeouts or production behavior were changed. The volume fixture can legitimately observe more than128MiB freed between its reserve snapshot and extraction under concurrent cleanup. The browser evidence shows a generic lifecycle bridge failure and no JavaScript errors; its underlying exception was not retained, so its precise transient cause remains unproven. These serial passes resolve targeted verification without pretending the original parallel matrix was green.

The final LunaMax dead-code run reports canonical wrapper0, raw Vulture3 with only the same3 reviewed false positives (type-only OwnershipState cast, required Protocol repo_id, context-manager traceback parameter), and deptry0 over378 files; no new finding arises from the shared vault identity helper or audit retirement. Independent full Ruff/format, ty/basedpyright, Pylint, cognitive complexity/Xenon, import/nesting and frontend lint/format/build evidence remains applicable. Live verification, its delivery-order mutation proof and remaining accelerated/performance selections are still pending. External Ollama leaves only6.7GiB free against a12GiB admission floor after stopping the old test-owned borrower; it remains untouched without user authorization. The canonical installer has provisioned pinned1.20.0 into a fresh test-owned status/storage namespace.

### full-matrix-feature-resolution | low | Feature corrections pass real runtime verification

The high canonical-vault proof and undeclared-substitution findings are resolved in the integrated source. A shared strict docs-relative identity mapping now queries real VaultRunCheckpoint keys and maps evidence back to physical cache paths; producer identity math is canonical and stored identities/public paths remain unchanged. All22 undeclared substitutions were removed without guard allowances. Identity-fenced retirement also resolves the newer-observation race, with a pure queue-policy mutation failure followed by exact restored pass.

The new live subprocess test passes against canonically provisioned Qdrant1.20.0: an actual code rebuild is followed by a same-size disk edit, combined search retains the old indexed snippet and marks it stale, the completed HTTP body precedes audit intake, the real durable repair job is incremental with publication authority and integrity attribution, and subsequent search reports current hits. The initial supervised run passes in116.84seconds and the final restored proof run passes in90.80seconds. Deliberately moving audit intake before the response causes the named delivery-correlation assertion to fail because the response request ID has not yet been observed. Exact route source bytes are restored with SHA2566a4ee3ae1020073df87474d3fbc4b0ea9b2e941bec424a68f6ba0e1ad0ba8af1; the normal node passes. An initial readiness-refused attempt is preserved separately and is not counted as mutation proof. The proof runner originally expected the later timestamp assertion; independent paired-artifact validation correctly records the earlier correlation assertion catching the same ordering violation.

Native installation/status and canonical resolve_binary/verify_native_binary also confirm the reviewed1.20.0 Windows executable SHA2563e86f79bd516097586afb5ceacf6b843bc9e32b8e4b311d94b63a3cc11432a40, distinct from its archive digest. Only fresh test-owned status/storage was used. The user explicitly chose to keep Ollama running; its temporary release of GPU allocation was natural, with no stop or configuration change by this work. Current integrated feature review for S01/S05 is PASS with no unresolved code findings. S02 full-matrix review remains PENDING until remaining resident retries, subprocess-GPU and performance commands report their outcomes.

## Verification

- 24 new CPU tests pass in `.pytest-tmp/stale-feature-tests.log`: actual file and ledger comparisons, same-size/same-mtime edits, changes beyond shown lines, deletion, vault semantic stamps, document bytes, mixed-domain shared reads, publication races, unsafe/offline roots, final combined service serialization, coalescing, incremental authority, rebuild blockers, job refusal projection, shutdown, post-response scheduling and CLI/MCP round trips.
- 349 existing CPU regressions pass with no skips: 249 search/CLI/MCP/publication cases in `.pytest-tmp/stale-regression.log`, 62 admission/dispatch/rebuild cases in `.pytest-tmp/stale-job-regression.log`, and 38 lifecycle/startup cases in `.pytest-tmp/stale-lifecycle-regression.log`.
- Four mutation sequences failed at their named assertions and passed after restoration: proof fence, incremental-only admission, audit blockers including transient missing proof, and shutdown admission. Evidence is in `.pytest-tmp/stale-mutation-*-fail.log` and matching pass logs. No mutation remains on disk.
- Package Ruff lint, touched-file format checks, ty and strict basedpyright checks pass. Scoped pylint, configured cognitive complexity and guide mdformat checks pass. The initial complexity, module-length and formatting findings were corrected within S01 rather than suppressed.
- GPU inference/end-to-end execution was not run: another process owns the machine GPU. This change adds no inference implementation or model-stack behavior. Existing CPU boundary tests verify the service and adapter paths under isolated state.

The supplemental full-matrix review is REVISION REQUIRED until the high findings above are integrated and verified. The initial PASS records the earlier focused review at 15c1146c8 and is not a claim about these later full-matrix findings.

## Recommendations

No follow-on decision or implementation revision is required for this scope. Full rebuild execution remains an operator action under the existing lifecycle. Per-hit unverifiable status is an intentional limit of bounded point-in-time checks, and is separate from published-generation readiness.
