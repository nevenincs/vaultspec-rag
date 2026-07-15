---
tags:
  - '#plan'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
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
- [ ] `P03.S30` - Perform final independent transaction-boundary audit and release gates; `.vault/audit/2026-07-15-provider-mcp-enrollment-audit.md and full repository gates`.

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
