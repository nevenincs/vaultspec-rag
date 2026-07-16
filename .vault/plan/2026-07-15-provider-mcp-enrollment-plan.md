---
tags:
  - '#plan'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-16'
tier: L2
related:
  - '[[2026-07-15-provider-mcp-enrollment-adr]]'
  - '[[2026-07-15-provider-mcp-enrollment-research]]'
---

# `provider-mcp-enrollment` plan

### Phase `P01` - adopt Core's typed provider lifecycle

Route RAG's canonical MCP enrollment, preview, migration, and removal through Core's project-scoped provider authority.

- [x] `P01.S01` - Extend the canonical RAG definition with Core's tool distribution token; `src/vaultspec_rag/builtins/mcps/vaultspec-rag.builtin.json`.
- [x] `P01.S02` - Replace JSON-only mode observation and migration with Core's provider-aware status and force-managed sync; `src/vaultspec_rag/commands/_mode.py and src/vaultspec_rag/tests/test_install_mode.py`.
- [x] `P01.S03` - Route install preview and reconciliation through Core's project-scoped MCP sync; `src/vaultspec_rag/commands/_install.py and src/vaultspec_rag/tests/test_install_mode.py`.
- [x] `P01.S04` - Route uninstall preview and cleanup through Core's project-scoped MCP uninstall; `src/vaultspec_rag/commands/_uninstall.py`.
- [x] `P01.S05` - Preserve Core per-provider outcomes in structured reports and CLI rendering; `src/vaultspec_rag/commands/_models.py, src/vaultspec_rag/cli/_render.py, and src/vaultspec_rag/tests/test_cli.py`.

### Phase `P02` - make MCP intent and dependency placement symmetric

Make --mcp and --no-mcp reconcile the canonical source and optional dependency at the resolved tool, dependency, or dev surface.

- [x] `P02.S06` - Implement placement-aware MCP extra reconciliation and durable ownership provenance; `src/vaultspec_rag/commands/_mcp_extra.py`.
- [x] `P02.S07` - Make --mcp and --no-mcp reconcile only the canonical MCP source while retaining the rule and discovery skill; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/tests/test_install_mcp_extra.py, and src/vaultspec_rag/tests/test_install_mode.py`.
- [x] `P02.S08` - Reverse only owned MCP extra placement during unenrollment and uninstall; `src/vaultspec_rag/commands/_uninstall.py and src/vaultspec_rag/tests/test_install_mcp_extra.py`.

### Phase `P03` - prove host parity and release readiness

Verify provider-native behavior, package metadata, installed artifacts, and the dependent release with real workspaces and host CLIs.

- [x] `P03.S09` - Add real-behavior mode and enrollment tests for both provider-native targets; `src/vaultspec_rag/tests/test_install_mode.py, src/vaultspec_rag/tests/test_cli.py, src/vaultspec_rag/commands/_models.py, src/vaultspec_rag/commands/_install.py, and src/vaultspec_rag/commands/_uninstall.py`.
- [x] `P03.S10` - Add real-behavior dependency-placement tests for existing runtime and dev declarations; `src/vaultspec_rag/tests/test_install_mcp_extra.py`.
- [x] `P03.S11` - Add end-to-end install dry-run drift upgrade uninstall and host CLI acceptance coverage; `src/vaultspec_rag/tests/integration/test_install.py`.
- [x] `P03.S12` - Raise the Core minimum and refresh the lock after the fixed Core release is published; `pyproject.toml, uv.lock, src/vaultspec_rag/commands/_mode.py, src/vaultspec_rag/commands/_install.py, and src/vaultspec_rag/commands/_uninstall.py`.
- [x] `P03.S13` - Verify wheel metadata console entry point canonical builtin Core floor and installed-package acceptance; `src/vaultspec_rag/tests/test_packaging_metadata.py, tests/smoke_check.py, src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/cli/_install.py, src/vaultspec_rag/tests/test_install_mcp_extra.py, src/vaultspec_rag/tests/test_cli.py, and src/vaultspec_rag/tests/test_server_doctor.py`.
- [x] `P03.S14` - Run formal code review and record release-readiness findings; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md`.
- [x] `P03.S15` - Implement accurate non-mutating MCP source-overlay previews and real-file API/CLI regressions; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/tests/integration/test_install.py, and src/vaultspec_rag/tests/test_cli.py`.
- [x] `P03.S16` - Fail closed on top-level and per-provider MCP lifecycle errors with complete reports and CLI regressions; `src/vaultspec_rag/commands/_models.py, src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/commands/_uninstall.py, src/vaultspec_rag/cli/_install.py, src/vaultspec_rag/cli/_render.py, and tests`.
- [x] `P03.S17` - Remove dormant uv-add MCP code and stale prose and make the Core smoke floor future-compatible; `src/vaultspec_rag/commands/_uv_sync.py, src/vaultspec_rag/tests/test_install_mcp_extra.py, src/vaultspec_rag/cli/_install.py, and tests/smoke_check.py`.
- [x] `P03.S18` - Re-audit remediated MCP enrollment and run final release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S19` - Persist requested RAG mode in MCP preview projections and align tool-mode recovery guidance; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/server/_main.py, and real mode-transition tests`.
- [x] `P03.S20` - Re-audit final MCP remediation and repeat release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S21` - Migrate mode transitions when any managed provider remains and preserve partial-provider preview parity; `src/vaultspec_rag/commands/_mode.py, src/vaultspec_rag/commands/_install.py, and partial-provider integration tests`.
- [x] `P03.S22` - Perform final independent partial-provider audit and release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S23` - Restrict mode transitions to affirmative deployed ownership and restore fresh-install preview parity; `src/vaultspec_rag/commands/_mode.py, src/vaultspec_rag/tests/integration/test_install.py, and collision acceptance tests`.
- [x] `P03.S24` - Perform final independent deployment-evidence audit and release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S25` - Enforce MCP skip as a symmetric native-lifecycle boundary; `src/vaultspec_rag/commands/_install.py and skipped mode-transition integration tests`.
- [x] `P03.S26` - Perform final independent skip-boundary audit and release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S27` - Make implicit MCP skips status-free and migrate owned dependency-extra placement; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/commands/_mode.py, src/vaultspec_rag/commands/_mcp_extra.py, and real placement regressions`.
- [x] `P03.S28` - Perform final independent implicit-skip and placement audit with release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S29` - Enforce complete MCP intent skips and transactional placement-mode commits; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/builtins/__init__.py, and real transaction regressions`.
- [x] `P03.S30` - Perform final independent transaction-boundary audit and release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.
- [x] `P03.S31` - Restore malformed-project error reporting and prove successful mode declarations; `src/vaultspec_rag/commands/_install.py, mode and torch contract tests, and isolated real CLI gates`.
- [x] `P03.S32` - Perform final independent malformed-project and transaction audit with release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and complete segmented repository gates`.
- [x] `P03.S33` - Make native MCP intent writes transactional and generalize malformed-project diagnostics; `src/vaultspec_rag/commands/_install.py and real install transaction tests`.
- [x] `P03.S34` - Perform fresh transaction review and complete exact segmented release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the full selected test inventory`.
- [x] `P03.S35` - Preserve every builtin destination across failed forced seed transitions; `src/vaultspec_rag/commands/_install.py and ordered real seed rollback tests`.
- [x] `P03.S36` - Perform final fresh data-loss review and complete all release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact selected test inventory`.
- [x] `P03.S37` - Preserve builtin node topology across failed install rollback; `src/vaultspec_rag/commands/_install.py and real symlink/junction rollback tests`.
- [x] `P03.S38` - Perform final topology-aware release review and complete every gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1820-test inventory`.
- [x] `P03.S39` - Make rollback file replacement collision-safe and metadata-preserving; `src/vaultspec_rag/commands/_install.py and real rollback collision tests`.
- [x] `P03.S40` - Perform final collision-safe release review and complete every gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1820-test inventory`.
- [x] `P03.S41` - Repair service attribution and deterministic release-test isolation; `src/vaultspec_rag/serviceclient/_transport.py, service-job behavior tests, and isolated real service fixtures`.
- [x] `P03.S42` - Perform fresh service-safe release review and complete every gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1820-test inventory`.
- [x] `P03.S43` - Repair fresh provider selection and transactional MCP lifecycle boundaries; `src/vaultspec_rag/commands/_install.py, src/vaultspec_rag/commands/_uninstall.py, preview topology and context handling, and real lifecycle regressions`.
- [x] `P03.S44` - Perform fresh transaction-safe release review and complete every gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1823-test inventory`.
- [x] `P03.S45` - Make singleton teardown wait for the actual lock holder; `real singleton and Qdrant integration fixtures with foreign-holder process regressions`.
- [x] `P03.S46` - Perform final holder-safe release review and complete every gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1824-test inventory`.
- [x] `P03.S47` - Make required MCP nodes topology-safe across preview and apply; `preview projection, provider and workspace intent writes, native targets, ownership, and real relative-link regressions`.
- [x] `P03.S48` - Perform final topology-safe release review and complete every gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1824-test inventory`.
- [x] `P03.S49` - Reject full-lifecycle target overlap and adopt the corrective Core floor; `src/vaultspec_rag/commands/_mcp_topology.py, install and uninstall lifecycle tests, pyproject.toml, and uv.lock`.
- [x] `P03.S50` - Repeat the complete post-remediation release review and every gate from zero; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1830-test inventory`.
- [x] `P03.S51` - Accumulate requested project diagnostics and align filesystem failure tests with Core 0.1.45; `src/vaultspec_rag/commands/_install.py and real install regressions`.
- [x] `P03.S52` - Repeat the complete post-correction release review and every gate from zero; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and the exact 1830-test inventory`.
- [x] `P03.S53` - Repeat every release-review gate from zero and credit the POSIX-only FIFO item on Linux CI; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; Windows test items: 2,269 total, 1,832 selected, 437 excluded; POSIX test items: 2,270 total, 1,833 selected, 437 excluded`.
- [x] `P03.S54` - Align real job-completion integration waits with the bounded service administration contract; `src/vaultspec_rag/tests/integration/test_jobs_registry.py and S53 release-gate diagnostics`.
- [x] `P03.S55` - Repeat every platform-aware release gate from zero, verify S54 deadline behavior, and stop on the first red gate; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; no carried credit; Windows 2,269 total, 1,832 selected, 437 excluded; POSIX 2,270 total, 1,833 selected, 437 excluded with actual FIFO execution; full selected tests; static, type, complexity, and diff gates; wheel, sdist, and public Core 0.1.45 smoke; fresh isolated installed-package Claude and Codex configs, idempotence, and selective uninstall`.
- [x] `P03.S56` - Bound real GPU model fixture acquisition against persistent Hugging Face metadata failures while preserving warm-cache and cold-download behavior; `src/vaultspec_rag/embeddings.py, src/vaultspec_rag/search/_searcher.py, src/vaultspec_rag/tests/conftest.py, src/vaultspec_rag/tests/_model_setup.py, src/vaultspec_rag/tests/test_model_setup.py, src/vaultspec_rag/tests/integration/test_intent_ranking.py, and S55 release-gate diagnostics`.
- [x] `P03.S57` - Repeat every platform-aware release gate from zero, audit the complete S56 bounded model contract independently, and stop on the first failure; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; no carried credit; Windows 2,271 total, 1,834 selected, 437 excluded; POSIX 2,272 total, 1,835 selected, 437 excluded with actual FIFO execution; S56 full 1,111-document corpus, 600-second whole-worker boundary, sharded cache completeness, cold online repair diagnostics, and warm no-network behavior; all selected tests; static, package, public Core 0.1.45, fresh Claude and Codex, idempotence, and selective uninstall gates`.
- [x] `P03.S58` - Assign stable explicit pytest parameter IDs so every collected item has one unique displayed node ID; `src/vaultspec_rag/tests/test_config.py, src/vaultspec_rag/tests/test_torch_config.py, Windows and POSIX collection ledgers, and S58 formal review`.
- [x] `P03.S59` - Repeat every platform-aware release gate from zero at the corrected unique-item ledger, preserve every S56 and S57 gate, and stop on the first failure; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; no carried credit; Windows 2,271 total and unique, 1,834 campaign, 437 excluded; POSIX 2,259 total and unique, 1,835 campaign, 424 excluded; named zero-overlap M/P/J/F proof; complete S56 full-corpus, 600-second, cache, repair, offline, cleanup, and ranking contract; all runtime, static, package, public Core 0.1.45, fresh Claude and Codex, idempotence, selective unenrollment, and uninstall gates`.
- [x] `P03.S60` - Repair the disposable locked Windows scikit-learn installation, verify wheel payload integrity against RECORD, and rerun the failed S56 selectors; `.venv scikit-learn 1.9.0 installation, uv cache and public wheel evidence, installed msvcp140.dll and vcomp140.dll hashes, direct sklearn import, exact failed intent selector, six-item S56 model group, and S60 formal review`.
- [ ] `P03.S61` - Repeat every platform-aware release gate from zero after the verified environment repair and stop on the first failure; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md; no carried credit; Windows 2,271 total and unique, 1,834 campaign, 437 excluded; POSIX 2,259 total and unique, 1,835 campaign, 424 excluded; named zero-overlap M/P/J/F proof; direct scikit-learn import and RECORD payload preflight; complete S56 full-corpus, 600-second, cache, repair, offline, cleanup, and ranking contract; all runtime, static, package, public Core 0.1.45, fresh Claude and Codex, idempotence, selective unenrollment, and uninstall gates`.

## Description

Deliver project-scoped MCP parity for Claude Code and Codex without adding a RAG-owned
provider renderer. The work adopts Core's typed lifecycle, makes the optional MCP
dependency follow RAG's resolved install mode, turns `--no-mcp` into a true unenrolled
state, proves ownership-safe migration and removal, and gates publication on the fixed
Core release.

## Steps

## Parallelization

P01 waits for Core's public API and extra-aware renderer. Within P01, the canonical
definition and report model can proceed before the install, mode, and uninstall wiring.
P02 depends on mode resolution from P01 but its placement engine can be developed beside
provider report rendering. P03 follows the production behavior; packaging metadata and
smoke coverage wait for the published Core version, while local-source acceptance may
run against Core's feature branch without committing an unreleased dependency.

## Verification

- Focused unit and integration suites pass without mocks, patches, skips, or mirrored
  business logic.
- Fresh tool, dependency, and dev installs render the specified launch and dependency
  placement in Claude-only, Codex-only, and dual-provider projects.
- Real `claude mcp get vaultspec-rag` and `codex mcp get vaultspec-rag --json` recognize
  the project entries.
- Provider-local missing or drifted state is reported by Core and repaired without
  rewriting a correct sibling target or an unowned collision.
- Dry-run changes no bytes, invokes no dependency mutation, and reports provider-target
  deltas; a second identical install or upgrade is byte-stable.
- `--no-mcp` and uninstall remove only RAG-owned source, provider entries, and recorded
  dependency extras while preserving Core and user-owned configuration.
- Ruff, type checking, the full pytest matrix, Vaultspec checks, wheel build, smoke test,
  and formal code review pass.
- The released wheel declares the published fixed Core floor, contains the canonical
  builtin, exposes the console entry point, and passes installed-package host acceptance.
