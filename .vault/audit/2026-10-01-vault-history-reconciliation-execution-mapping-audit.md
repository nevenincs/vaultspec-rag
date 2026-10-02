---
tags:
  - '#audit'
  - '#vault-history-reconciliation'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:9a8e5fe4db349ce32cc4064d810aca6ff26fc4b1879f3077c753bc7d5599d9ad'
related:
  - "[[2026-09-30-pipeline-performance-plan]]"
  - '[[2026-07-27-lint-defaults-completion-review-audit]]'
  - '[[2026-06-18-storage-lifecycle-adr]]'
---

# `vault-history-reconciliation` audit: `execution evidence and portable locators`

## Scope

Reconciled the 38 warning and 10 informational execution-mapping findings in the retained whole-vault check at baseline commit `3b0724c`. Owning-CLI inventory covered 167 ADRs, 274 audits, 161 execution records, 136 plans, 164 research records, 35 references, and 175 generated feature indexes. The pass concerns historical execution attribution and portable record locators; it is not a fresh implementation review of every decision in that inventory.

## Findings

### historical-mapping-recovery | low | Recover actual operations without inventing passing gates

Literal plan Step IDs were compared with retained execution bodies, audits, and selected Git diffs. Append-only execution rows record actual added, modified, deleted, or renamed historical paths at their cited commits. Historical monolith paths remain historical paths; later package extraction does not turn them into earlier additions. Existing ledger rows and notes are preserved. No completed checkbox is changed to hide a finding, and a file's existence or a closed checkbox is not treated as execution proof.

The upstream-complexity Steps of `lint-defaults` reuse the retained passing scoped rule-family review in `2026-07-27-lint-defaults-completion-review-audit` after `2ac31f1d` and `81e44ac5`. That audit reports zero findings for PLR0911, PLR0913, PLR0915, and preview PLR1702; it does not retain complete shell argv. Reused verification is limited to those acceptance criteria and asserts neither a fresh run nor success for the broader configured rules.

### retained-failed-verification | medium | The earlier repository policy failure remains a failed result

The `large-index-resilience` audit of July 22 records Ruff, formatting, and Ty passing while the repository complexity policy failed existing blocks. The S50 history records that failed aggregate check as failed, with the retained audit as provenance. It does not invent a later historical passing result. Later actual verification can be logged separately when its scope and outcome are established.

### storage-authority-reconciliation | medium | Preserve the authorized CLI-direct ruling and the earlier proposal

Git `d3be70d0` added `2026-06-18-storage-lifecycle-W02-P03-S13`, explicitly recording the user's direction to reconcile to the shipped CLI-direct design. It names S16, S17, S22, S24, S28, S30, S40, S41, and S43 as superseded or structurally inapplicable, not implemented. The old fold retained only the S13 scope and lost those cross-Step closure facts from the active ledger.

The historical addition of that shared record is attributed to its explicitly named Steps. The accepted ADR is reconciled to the witnessed authorization: only the read-only survey is daemon HTTP/MCP-owned; destructive CLI verbs use shared storage-domain functions through the managed loopback server; migration copies vectors and payloads without re-embedding. The earlier daemon-control-plane and local-maintenance proposals remain recognizable as history. Namespace attribution, confirmation, live-server collection APIs, lock discipline, and the prohibition on deleting storage files beneath a running server remain constraints. No generated policy rule is edited.

The exact original shared-record body remains available in the cited Git object; it is also retained verbatim in the ignored review artifacts. No historical implementation or GPU success is asserted for the retired scope.

### same-date-ledger-identity | medium | Two historical plans share a feature and scaffold date

Both April 2 `service-graph` plans resolve to the same default execution-ledger path in the installed CLI. Appending the phase-1 rows to the roadmap-bound ledger would misattribute history. The owning rename preserves the complete roadmap ledger body and parent binding under a descriptive roadmap ledger stem, freeing the default path for a separately bound phase-1 ledger.

The installed log verb computes the feature/date path rather than locating a previously renamed ledger by its parent binding. Future maintenance of the closed historical roadmap must account for this limitation instead of blindly reusing the default log target. No CLI implementation or plan identity is changed in this pass.

### portable-record-locators | low | Replace workstation locations without changing observations

Twenty-three record bodies replace generic absolute drive paths with named portable placeholders or relative companion-checkout locators. Windows drive-case and drive-relative examples use explicit symbolic drive and segment names, preserving their intended distinction. Windows system-directory examples retain their system-directory meaning through `%SystemRoot%`. Historical observations retain the commands, timings, identifiers, and outcomes, with explicit context for the portable location notation.

Each body mutation uses the owning edit verb and an expected original Git blob hash. No historical mechanical ledger row is rewritten. Archived stale performance records remain untouched.

### execution-evidence-limits | medium | Missing execution proof remains distinct from actual code changes

An actual code, test, or documentation change supports its mechanical operation row; it does not certify all compound acceptance criteria. Authored integration tests described as GPU-gated are not recorded as executed. Human acceptance, live-service observations, full-suite runs, and companion-repository operations require their own retained evidence. A source-only review that explicitly lacked its test binaries remains source-only.

Unresolved Steps and their exact original criteria are retained in the ignored reconciliation artifacts and summarized after the final structural check. Absence of history alone is not evidence that a Step must be reopened, and this pass does not archive active plans to conceal gaps.

### current-required-failure | high | Integrated verification remains open

Required CI run 36826003868 at 3b0724c36f3a5b550c436cff3cf9116cc36da965 failed lint job 110251725611 (three module-size failures) and Windows correctness job 110251725590 (thirteen failures). The performance plan S04 is reopened through its owning verb with append-only failed-check rows. Earlier scoped passes remain history; no overall-clean assertion is current.

### remaining-mapping-gaps | high | Historical attribution is still incomplete

An earlier interim checkpoint reported thirteen errors, six warnings, and one informational work-in-flight finding, with seventy-eight unmapped closed Steps. The initial criteria below preserve that checkpoint; subsequent attribution substantially reduces it. They are not represented as all still unresolved.

- .vault/plan/2026-04-12-index-progress-bars-phase-1-plan.md S07: Confirm a piped run emits no control sequences while an interactive run renders the bar; `src/vaultspec_rag/tests/`.
- .vault/plan/2026-04-12-vaultspec-rag-install-plan.md S01: Land the companion-side reconciling sync that tracks ownership of managed entries and prunes the orphans a previous install left behind, covered against real filesystem fixtures; `pyproject.toml`.
- .vault/plan/2026-05-30-cli-index-default-plan.md S06: Confirm by hand that a bare index run is unaffected, an unscoped rebuild refuses with a non-zero exit, and a scoped rebuild spares the other collection; `src/vaultspec_rag/tests/integration/`.
- .vault/plan/2026-05-30-cli-path-glob-plan.md S07: Confirm against a live indexed service that a code search returns the expected hits and that adding an exclude pattern visibly prunes them; `src/vaultspec_rag/tests/integration/`.
- .vault/plan/2026-05-30-service-lifecycle-plan.md S06: Walk the full lifecycle against a live daemon, confirming the status file appears and is removed, the heartbeat advances, and the lifecycle log lines are present; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.
- .vault/plan/2026-05-31-search-postprocess-plan.md S06: Document both flags as opt-in post-rerank steps across the project README, the package README, and the shipped discovery rule; `README.md`.
- .vault/plan/2026-05-31-server-mcp-route-plan.md S03: Confirm against a live daemon that a bare request returns no redirect status and no redirect location, and that a streaming client lists the expected tools without a redirect hop; `src/vaultspec_rag/tests/integration/`.
- .vault/plan/2026-05-31-service-token-identity-plan.md S06: Confirm against a live service that the status file carries the token, that the health endpoint returns the same value, and that the service stops cleanly; `src/vaultspec_rag/tests/integration/`.
- .vault/plan/2026-06-01-service-operability-plan.md S14: Document watcher config keys, env vars, flags, and subcommands in the top-level readme; `README.md`.
- .vault/plan/2026-06-01-service-operability-plan.md S15: Document the same watcher config and control surface in the package readme; `src/vaultspec_rag/README.md`.
- .vault/plan/2026-06-02-watcher-targeted-reindex-plan.md S05: Run ruff and the full pytest suite and confirm zero violations and green before PR; `pyproject.toml`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S01: Confirm the default output answers the human review questions; `src/vaultspec_rag/cli/_service_status.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S04: Keep `--json` stable and full-fidelity for agent/script use; `src/vaultspec_rag/cli/_service_status.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S06: Run manual CLI review and wait for human acceptance before closing the phase; `src/vaultspec_rag/cli/_service_status.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S08: Keep backend `/health` as a readiness endpoint for automation and adapters; `src/vaultspec_rag/cli/_service_status.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S23: Run manual CLI review and wait for human acceptance before closing the phase; `src/vaultspec_rag/cli/_service_jobs.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S32: Run manual CLI review and wait for human acceptance before closing the phase; `src/vaultspec_rag/cli/_service_logs.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S33: Inventory current logger creation and direct logging calls across the codebase; `src/vaultspec_rag/logging_config.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S34: Identify call sites that bypass or misuse the centralized logging interface; `src/vaultspec_rag/logging_config.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S38: Avoid changing the human CLI log renderer owned by W06.P03 except by agreed; `src/vaultspec_rag/logging_config.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S40: Produce an audit note for any broad call-site migration that should be staged; `src/vaultspec_rag/logging_config.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S41: Identify mature CLI tools with search, ranked result, reporting, or operational; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S42: Use primary or authoritative sources where possible, such as official; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S43: Compare how those tools handle; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S44: Treat `ragx` as a possible stable handoff format for long or structured result; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S45: Produce design recommendations for `vaultspec-rag search` that keep default; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S46: Do not implement the search output redesign until the human reviewer accepts the; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S56: Run manual CLI review and wait for human acceptance before closing the phase; `src/vaultspec_rag/cli/_search.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S62: Record remaining table-using CLI commands as follow-up inventory if they are; `src/vaultspec_rag/cli/_render.py`.
- .vault/plan/2026-06-11-cli-service-operability-hardening-epic-plan.md S63: Run manual CLI review and wait for human acceptance before closing the phase; `src/vaultspec_rag/cli/_render.py`.
- .vault/plan/2026-07-24-worktree-index-reuse-plan.md S19: commit the feature with a why-focused message and push to origin main; `git`.
- .vault/plan/2026-07-25-index-resume-drift-race-plan.md S11: Count faults only in the circuit breaker and record drift outcomes in their own counter reported alongside job state; `src/vaultspec_rag/indexer/_run_policy.py`.
- .vault/plan/2026-07-25-index-resume-drift-race-plan.md S14: Verify on a live service against a genuinely moving tree that a racing path is superseded, the run completes, and the degraded state clears; `src/vaultspec_rag/tests/integration/`.
- .vault/plan/2026-07-27-body-schema-provenance-plan.md S01: Add immutable body-schema contracts and scaffold stamping; `src/vaultspec_core/builtins and src/vaultspec_core/vaultcore`.
- .vault/plan/2026-07-27-body-schema-provenance-plan.md S02: Validate documents against attested schema provenance; `src/vaultspec_core/vaultcore/checks/body_sections.py and parser models`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S01: Retain a bounded window of progress samples per job so a rate can be derived from change over time rather than from a single point; `src/vaultspec_rag/jobs.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S02: Derive a windowed completion rate and remaining-time estimate on the liveness projection, returning null for queued, paused, terminal, uncountable and under-sampled work; `src/vaultspec_rag/server/_routes_jobs.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S03: Prove the estimator declines to guess: assert null for each non-countable state and that a steady rate yields the expected remaining seconds; `src/vaultspec_rag/tests/`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S04: Add textual to the core dependency list and refresh the lockfile; `pyproject.toml`, `uv.lock`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S05: Create the application module that owns the screen, composing the table, the log region and the footer from one layout; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S06: Refresh off the event loop on an interval through a thread worker over the existing bounded jobs query, keeping the fetch identical to the one-shot path; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S07: Build the multi-line row from the job payload: state, operation, full project path, progress, elapsed and remaining time, keyed so a row survives reordering and removal; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S08: Reuse the existing job label helpers rather than restating their vocabulary, and promote the full project root out of the detail-only render path; `src/vaultspec_rag/cli/_service_jobs.py`, `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S09: Animate a liveness indicator that distinguishes a refreshing view from a frozen one, and stamp the last successful refresh; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S10: Drive layout and column visibility from reported terminal width, collapsing to tabs when narrow and placing the log region beside the table when wide; `src/vaultspec_rag/cli/_jobs_tui.py`, `src/vaultspec_rag/cli/_jobs_tui.tcss`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S11: Bind pause, resume, stop, retry and delete to the selected row through the existing typed transports, carrying the expected-revision guard; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S12: Enable each action from the selected job's published capability flags, disabling rather than hiding what the service would reject; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S13: Render a requested control as requested until the service acknowledges it, so a desired state is never shown as an observed one; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S14: Scope the log region to the selected job through the existing bounded per-job filter, refreshing it with the selection; `src/vaultspec_rag/cli/_jobs_tui.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S15: Route the live jobs path to the application and delete the clear-and-reprint loop, its refresh banner and its watch-status text; `src/vaultspec_rag/cli/_service_jobs.py`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S16: Prove the interface on rendered output driven by real key presses: one assertion per action binding, plus the capability gate, the narrow and wide layouts, and the estimate column; `src/vaultspec_rag/tests/`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S17: Update the operator documentation for the replaced live view and the new controls; `docs/`, `README.md`.
- .vault/plan/2026-07-27-jobs-tui-plan.md S18: Run lint, format, type-check and the touched test modules, then commit by explicit pathspec; `repository gates`.
- .vault/plan/2026-07-27-maintainability-remediation-plan.md S16: Sweep the package for aliases that rename an existing binding, and repoint their callers at the original; `src/vaultspec_rag/cli/_app.py, src/vaultspec_rag/serviceclient/_discovery.py`.
- .vault/plan/2026-07-27-maintainability-remediation-plan.md S17: Search by meaning for declarations that restate logic owned elsewhere, and collapse each onto its owner; `src/vaultspec_rag/`.
- .vault/plan/2026-07-27-maintainability-remediation-plan.md S18: Confirm no non-facade module exports a name it does not define, and that the guard proves it; `src/vaultspec_rag/tests/test_no_reexports.py`.
- .vault/plan/2026-07-27-maintainability-remediation-plan.md S19: Guard that an extraction cannot orphan a decorator onto the definition below it; `src/vaultspec_rag/tests/`.
- .vault/plan/2026-07-27-maintainability-remediation-plan.md S20: Bring every test module under the production module ceiling and gate them at it; `src/vaultspec_rag/tests/, pyproject.toml`.
- .vault/plan/2026-07-27-maintainability-remediation-plan.md S21: Make the test helpers that now cross module boundaries public, after establishing why narrowing the shared harness import destabilises distributed workers; `src/vaultspec_rag/tests/_jobs_tui_harness.py, src/vaultspec_rag/tests/test_cli_jobs_tui*.py`.
- .vault/plan/2026-07-28-index-observability-plan.md S07: Run lint, format, type-check, and the targeted test set, then land the change; `src/vaultspec_rag`.
- .vault/plan/2026-07-31-issue-triage-plan.md S01: One finding shaped the sequencing and is worth restating: a PR that reads as merged is not evidence its commits are on the default branch. The stranded CI work merged into a branch that had itself landed thirty-three seconds earlier, so it shows green and delivers nothing. `P01.S01` is that recovery.
- .vault/plan/2026-07-31-issue-triage-plan.md S02: Pin the interpreter patch level so local and CI resolve one interpreter rather than a family; `.python-version`.
- .vault/plan/2026-07-31-issue-triage-plan.md S03: Derive the CI interpreter from the pin, replacing the four repeated version literals; `.github/workflows/ci.yml`.
- .vault/plan/2026-07-31-issue-triage-plan.md S04: Widen the interpreter conformance check from minor to patch granularity; `.github/workflows/ci.yml`.
- .vault/plan/2026-07-31-issue-triage-plan.md S05: State the one-per-line closing-trailer convention where the next PR author will read it; `.github/`.
- .vault/plan/2026-07-31-issue-triage-plan.md S06: Route the three raw-payload formatter call sites through the canonical measurement reader; `src/vaultspec_rag/cli/_service_jobs_presentation.py`.
- .vault/plan/2026-07-31-issue-triage-plan.md S07: Refuse a non-finite duration or size at the formatter instead of rendering it as a small measurement; `src/vaultspec_rag/cli/_cli_format.py`.
- .vault/plan/2026-07-31-issue-triage-plan.md S08: Decide whether the wheel ships the test suite, and record the intent beside the existing package-data note; `pyproject.toml`.
- .vault/plan/2026-07-31-issue-triage-plan.md S09: Confirm no live code writes the acceptance index artifacts, then remove the orphaned copies; `.git/`.
- .vault/plan/2026-07-31-issue-triage-plan.md S10: Warn when a result set collapses to a single distinct path across a broad query; `src/vaultspec_rag/search/`.
- .vault/plan/2026-07-31-issue-triage-plan.md S11: Obtain approval on the non-destructive index publication decision record, or record its rejection; `.vault/adr/`.
- .vault/plan/2026-07-31-issue-triage-plan.md S12: Wire the generation reclaim decision to a production caller once the decision record is approved; `src/vaultspec_rag/storage_reclamation.py`.
- .vault/plan/2026-07-31-issue-triage-plan.md S13: Author the decision record for the resumed-index drift race, naming the layer that owns detection and remedy; `.vault/adr/`.
- .vault/plan/2026-07-31-issue-triage-plan.md S14: Answer the five design calls blocking the remaining test-substitution sites; `.vault/adr/`.
- .vault/plan/2026-08-26-mcp-read-only-mode-plan.md S01: Derive the served surface from the read-only annotation each tool already declares, so no second list can drift from it; `src/vaultspec_rag/mcp/_tools.py`.
- .vault/plan/2026-08-26-mcp-read-only-mode-plan.md S02: Parse the read-only flag alongside the arguments the entry point already handles, and remove the mutating tools before the server serves; `src/vaultspec_rag/server/_main.py`.
- .vault/plan/2026-08-26-mcp-read-only-mode-plan.md S03: Assert the read-only listing serves exactly the read set and that no mutating tool survives the flag, so a tool added later cannot appear silently; `src/vaultspec_rag/tests/test_server.py`.
- .vault/plan/2026-08-26-mcp-read-only-mode-plan.md S04: Assert the default launch still serves every tool, so the flag cannot narrow the operator and CI surface; `src/vaultspec_rag/tests/test_server.py`.

Operator correction: a newly created duplicate release-trigger ledger used the filename-derived feature instead of the actual plan tag. Its original bytes are retained under the owning archive at .vault/\_archive/exec/2026-04-01-cicl-pipeline/2026-04-01-cicl-pipeline-ledger.md; the same narrow September 6 push evidence is correctly appended to the existing cicl ledger. No original historical ledger was retired.

### current-logging-inventory | low | Read-only current source attribution

On 2026-10-01, parsed all 323 production Python files with AST, excluding the tests subtree. Recorded 112 getLogger calls, 73 log_event calls, 389 direct diagnostic-level calls (20 exception,114 warning,60 info,143 debug,52 error), three configure_logging calls, one addHandler, and one StreamHandler construction. The exact path/line/call inventory is retained in ignored review artifacts. This inventories statically named calls; dynamic aliases and third-party logger internals are outside the assertion.

Handler installation and stream-handler construction are confined to logging_config.py; no production basicConfig or FileHandler calls were found. The CLI application and daemon main invoke the shared configure_logging entry point. Direct logger methods are inputs to this configured backend, rather than proof of a bypass. The structured log_event helper emits through target_logger.log. Examined daemon startup error messages describe actual failures. No evidence-supported broad call-site migration is proposed by this narrow inventory; it does not certify every event severity or runtime log capture. The human renderer remains untouched.

### current-cli-primary-comparison | low | Fresh design grounding, not recovered June research

Read authoritative project documentation on 2026-10-01 for two mature tools. The [ripgrep guide](https://github.com/BurntSushi/ripgrep/blob/master/GUIDE.md) demonstrates matching lines with source line numbers, recursive output grouped by file, terminal color, context flags, and explicit maximum-column configuration. Line-oriented source locators support mechanically reusable hits. Its explicit long-line controls should not be translated into silent default truncation here; preserve complete locators and expose detail controls deliberately.

The [GitHub CLI formatting manual](https://cli.github.com/manual/gh_help_formatting) separates selected JSON fields, jq filtering, and Go templates. Its helpers expose terminal-only color, hyperlinks, relative times, and explicit truncation; its table helpers are optional presentation mechanisms rather than a requirement for this service. The [code-search manual](https://cli.github.com/manual/gh_search_code) exposes result limits and JSON path/repository/SHA/text-match/URL fields, with a warning that its legacy search engine can differ from the website. This makes provenance and selection limits explicit.

| Dimension                | Comparison and scoped recommendation                                                                                                     |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Default and pipes        | Use readable lines with complete locations; keep decorative terminal behavior separable.                                                 |
| Rank versus coordinate   | Ripgrep line numbers are real source coordinates; ranked retrieval must label rank independently rather than inventing a line.           |
| Detail and machine modes | Preserve full JSON metadata; expose scores and additional context explicitly.                                                            |
| Width and truncation     | Keep source locators complete; disclose any opt-in shortening or result limit.                                                           |
| Stable handoff           | Consider ragx only as an additional structured handoff; these sources do not establish its schema or justify replacing the default view. |

This fresh comparison supplies current research work for the original Wave06 criteria. It does not manufacture a June source list or original shell transcript, and proposes no new compatibility ruling or implementation change. The retained June30 execution summary separately witnesses accepted direction and operator review.

### latest-structural-checkpoint | high | Structural conformance passes; integrated verification remains open

The latest owning whole-vault check exits zero with zero errors, zero warnings, and two informational work-in-flight findings. All closed Steps have actual execution attribution. Watcher-targeted-reindex S05, jobs-tui S18, and index-observability S07 record a genuine current configured CPU dimension, with broader gate and delivery limits explicitly retained. The independent coordinator owns fresh runtime and full-gate proof; no premature passing result is asserted.

Issue-triage S09 is genuinely reopened after a failed enumeration of nine acceptance-search-index directories in the resolved common Git directory. Root subsequently preserved all nine intact outside Git, with forty-file ZIP verification; current exact enumeration is zero. A read-only producer search finds no matching source producer, but does not alone establish safe deletion ownership. The qualified failed enumeration is appended; root owns safe inspection/removal and post-full-test no-recreation evidence. Performance S04 remains open for demonstrated required CI failures. These informational findings describe active repair, not exemptions.

Current progress S07 is mapped to the coordinator-supplied strict three-module52PASS run after stream-lifetime repair, whose actual painted-terminal and plain-pipe assertions exercise both count surfaces. Read-only remote evidence confirms the donor-reuse feature commit on main and fresh PR328 carrying all seven previously stranded CI commits onto main. These results are scoped, without invented historical command timing.

Preservation check compares all100 original ledgers at baseline3b0724c: all5342 original Changes and Notes rows remain exact and in order. Owning annotation/Markdown sanitizers remove generated comments and whitespace only; owning modified-stamp repair re-attests those supported repairs. Affected generated feature indexes are regenerated through their owner.

### partial-drift-verification | high | Mechanical source attribution does not complete live acceptance

Index-resume-drift-race S14 now has a genuine historical modified-test row at51b6c15988aebf1aaaba59debe29387b72781999. The source exercises a resumed local indexer with actual concurrent corpus writes and asserts a whole-run outcome plus drift metadata. It uses CPU BoW/local storage, permits zero superseded paths, and does not exercise HTTP service health or assert that degraded status clears after the same churn run. Independent health unit coverage cannot fill this integrated criterion. No original live-service PASS or complete S14 acceptance is asserted. The mechanical mapping is present; the substantive historical verification gap remains explicit.

An earlier full CPU run failed one holder-PID assertion (5808 passed,8 platform skips,zero warnings). After canonical fixture repair, root-owned just test-python passes5810 tests with8 platform skips andzero warnings in221.50 seconds. This CPU snapshot result is recorded without claiming GPU or aggregate success. Strict GPU verification currently exposes SQLite connection ResourceWarnings under canonical lifecycle repair; subsequent applicable reruns and final aggregate review remain pending. Current post-passing-CPU common-Git enumeration remains zero, but orphan-cleanup S09 stays open until final broader no-recreation evidence. It cannot close on an earlier overall-green assertion.

### current-search-documentation | low | Fresh README repair has scoped evidence

The coordinator updates both README files with the actual near-score locale-collapse behavior, both dedup controls, and prefer production/tests/documentation examples, grounded in the current postprocessor and CLI help. Current search help, mdformat check, and configured pymarkdown scan all exit zero. Actual modified-file rows and these narrow results are appended to S06. Historical May README completion proof remains absent. The discovery-rule existing prefer example is unchanged; the original both-flags rule scope remains partial rather than represented as complete. No generated policy modification is made.

### plan-parser-structure | high | Owning Step mutation exposed historical container and row syntax defects

The real attempt to reopen index-resume-drift-race S14 failed with PLAN070/PLAN010 because three Wave headings were level three instead of the parser-required level two. A bounded owning inventory and plan check of all 29 L3/L4 plans found ten wrong-level Wave headings across drift, machine-discovery-recovery and worktree-index-reuse, plus ten malformed scope diagnostics across reuse and the operability epic. Owning body edits repair only container heading levels; owning Step edits restore reuse action/scope syntax and all original requirements. The epic Step serializer dry-run would relocate roughly 900 lines of retained prose, so it was rejected. A blob-guarded owning body edit repairs only S10/S11 and their literal continuation prose; S10's previously missing scope is described as the existing CLI server-health compatibility surface rather than an invented historical file. Stable identifiers, checked states and historical execution rows remain, except drift S14 is explicitly reopened against its fresh failed required live run.

Eight bounded plan checks also report PLAN022 for stable identifiers out of document order. The owning check explicitly allows intentional insert-between order and recommends verifying writer intent, not renumbering. A real owning insert dry-run allocates S18 before S02 without changing existing IDs. The actual inversion census is retained in the ignored review artifact. These warnings are reported separately from vault check all; no order, threshold or exclusion is changed to conceal them. Their disposition remains with the coordinator.

### live-drift-counterexample | high | Fresh required live acceptance fails

The retained real served retry in remediation-served-drift-live.log/jsonl reports one failed call and one teardown error in 50.36 seconds. Coordinator inspection of the live failure identifies applied-point accounting expected 13 versus found 12; teardown additionally observes a still-running spawned launcher. The original S14 criterion requires live moving-tree supersession, completed execution and cleared degradation. Its owning Step status is reopened and its original ledger gains a qualified failed-observation row and note. Prior historical operation mappings and scoped observations are retained. This is actual contrary verification evidence, not reopening merely because historical evidence was missing. Repair and final integrated CPU/GPU/aggregate verification remain pending.

### Finding: second-live-drift-run | high | Successful retry lacks required public drift evidence

The retained 2026-10-01 report `.pytest-tmp/remediation-served-drift-repaired.log` at source digest `f02581e0a00bc2351080e1454c6c9fab184fc795cf202905f797069ba4dde700` records one functional failure in 45.75 seconds and zero warnings. The retry succeeded after the applied-point repair and the launcher warning was absent. Public job drift was `None`, so the positive superseded-path assertion still failed. Owning execution logs append this actual failure to drift S14 and performance S04, preserving all prior rows and notes. Both Steps remain open; successful retry alone does not satisfy live acceptance or integrated completion.

### Finding: full-plan-parser-census | high | Legacy parser diagnostics extend beyond general vault checks

Owning inventory and parser checks cover all 136 active plan records. After the initial L3/L4 corrections, the broader census exposed 319 ASCII-separator violations, 11 scope-clause errors, 24 absent tier fields and five missing-Phase errors caused by the legacy L2 default. Prescribed separator repairs preserve prose meaning; scope repairs preserve actions and IDs. Five prose-only records have no canonical Steps and are accurately classified L1, without inventing execution or completion evidence. Nineteen existing Phase-based plans receive their actual L2 tier through the documented owning autofix, followed by a blob-guarded owning body restoration so serializer reordering cannot change retained prose or row order. The census also reports 19 PLAN022 insertion-order and three PLAN023 supported lowercase Phase-suffix advisories. These are distinct from hard structural errors; no renumbering, threshold change or exclusion hides them. General vault conformance and plan-parser diagnostics are separate dimensions.

Final owning parser census after these repairs: 136 plans, zero errors and 22 advisory warnings (19 PLAN022 and three PLAN023). General owning vault checks report zero errors, zero warnings and three work-in-flight informational findings for drift S14, issue-triage S09 and performance S04. Markdown formatting passes for all 106 changed vault Markdown files. Read-only comparison to the current committed baseline confirms all 4,651 original mechanical rows and 691 original notes remain in order across 100 ledgers; appended evidence does not replace any prior entry. Preservation and census artifacts are retained under `.pytest-tmp/vault-structural-repairs-*` and `.pytest-tmp/vault-plan-all-structure-after-repairs.json`.

## Recommendations

Use retained source records and exact Git operations for historical attribution. Add fresh verification only where the actual recorded command and assertions establish the original acceptance criterion. Preserve irreducible history gaps as findings rather than manufacture passing outcomes. Maintain distinct parent bindings for the same-date `service-graph` ledgers and account for the owning CLI's default-path limitation.

Hosted relationship checks were not used: this pass is grounded in local structural diagnostics, literal execution records, and Git history. Repository-wide code, environment, service, and GPU gates are owned by the coordinating session and are not duplicated here.
