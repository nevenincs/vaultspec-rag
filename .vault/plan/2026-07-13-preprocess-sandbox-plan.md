---
tags:
  - '#plan'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-27'
body_hash: 'sha256:2af87ef153a2a62bc149a1fb4e0c80b8acb9123ba12b28bd96a71875de5aa772'
tier: L2
related:
  - '[[2026-07-13-preprocess-sandbox-adr]]'
  - '[[2026-07-13-preprocess-sandbox-research]]'
---

# `preprocess-sandbox` plan

## Description

Implements the accepted `preprocess-sandbox` ADR (D1-D9). The RAG server's clients
are non-interactive, so consent cannot gate hook execution; containment replaces it.
P01 removes the trust-on-first-use surface entirely (the store, its verbs, and the
loader gate) so rules resolve for any root, leaving only the `off` kill switch and an
opt-in unsandboxed escape hatch. P02 introduces a `HookSandbox` abstraction at the
single runner launch seam - staged input, curated env, scratch cwd, and pluggable
OS-level backends (Windows AppContainer wrapped in a kill-on-close Job Object as the
primary boundary; bubblewrap/Landlock on Linux; seatbelt on macOS) - and is
fail-closed in server mode: no working backend means hooks are refused, never run
unconfined. P03 fixes the three server-path defects that would otherwise leave hooks
silently ineffective or their failures invisible (the watcher's trust-gated change
filter, the dropped `preprocess_failures` on `/jobs`, and the missing `/reindex`
pre-flight signal). P04 proves end-to-end that a contained hook cannot escape the
staged directory or open a socket and that a real worktree's hooks index through the
service with no interaction, and documents the model. Grounded in the research's
threat model and containment analysis.

## Steps

### Phase `P01` - Remove TOFU, resolve rules for every root

Delete the trust store and its gate so load_preprocess_rules resolves rules for any root (ADR D7); amend the control surface to the sandbox model (D8).

- [x] `P01.S01` - Delete the trust store module and every reference to it; `src/vaultspec_rag/indexer/_preprocess_trust.py`.
- [x] `P01.S02` - Remove the trust branch from load_preprocess_rules so rules resolve for any root, replacing the mode enforcement with the off kill switch and the unsandboxed escape hatch only; `src/vaultspec_rag/indexer/_preprocess_config.py`.
- [x] `P01.S03` - Retire trust_all, add VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED, and resolve the amended preprocess_mode (on-sandboxed default, off, unsandboxed); `src/vaultspec_rag/config.py`.
- [x] `P01.S04` - Drop the trust and untrust verbs, repoint preprocess status at sandbox-backend availability, keep --no-preprocess and add the unsandboxed flag; `src/vaultspec_rag/cli/_preprocess.py`.
- [x] `P01.S05` - Rework the preprocess-config unit tests off the trust store onto the resolve-for-any-root and kill-switch behavior; `src/vaultspec_rag/tests/test_preprocess_config.py`.

### Phase `P02` - HookSandbox seam and cross-platform backends

Introduce the HookSandbox abstraction at the runner launch with staged input, curated env, and pluggable backends including the Windows AppContainer boundary, fail-closed in server mode (ADR D1-D6).

- [x] `P02.S06` - Create the HookSandbox abstraction: backend protocol, staged-input plus curated-env plus scratch-cwd contract, capability probe, and the fail-closed server-mode policy; `src/vaultspec_rag/indexer/_hook_sandbox.py`.
- [x] `P02.S07` - Implement the Windows AppContainer backend with a kill-on-close Job Object, no network capability, and an ACL grant for the staged input dir; `src/vaultspec_rag/indexer/_hook_sandbox_windows.py`.
- [x] `P02.S08` - Implement the POSIX backends: bubblewrap with a Landlock-plus-seccomp fallback on Linux and a deny-default seatbelt profile on macOS; `src/vaultspec_rag/indexer/_hook_sandbox_posix.py`.
- [x] `P02.S09` - Route the runner subprocess launch through the resolved sandbox backend, preserving the timeout, output caps, and argv hygiene inside it; `src/vaultspec_rag/indexer/_preprocess_runner.py`.
- [x] `P02.S10` - Unit-test the sandbox contract and each backend: staged-only filesystem read, denied network, denied secret env, process-tree teardown, and the fail-closed refusal when no backend resolves; `src/vaultspec_rag/tests/test_hook_sandbox.py`.

### Phase `P03` - Server-path defect fixes and observability

Fix the watcher trust-gating, surface preprocess failures through /jobs, and add the /reindex pre-flight notice so hook outcomes are client-visible (ADR D9).

- [x] `P03.S11` - Make the watcher change filter recognize preprocessable files independent of the removed trust state; `src/vaultspec_rag/watcher.py`.
- [x] `P03.S12` - Thread preprocess_skipped and preprocess_failures into the job record and the /jobs response so extraction failures are client-visible; `src/vaultspec_rag/jobs.py`.
- [x] `P03.S13` - Add the /reindex pre-flight signal reporting whether a root ships a preprocess config and whether hooks will run under the resolved sandbox; `src/vaultspec_rag/server/_routes.py`.

### Phase `P04` - End-to-end proof and docs

Prove a contained hook cannot escape and that a real worktree's hooks index through the service non-interactively; update docs and the rule candidate.

- [x] `P04.S14` - Prove end-to-end against real backends that a contained hook cannot read outside the staged dir nor open a socket, and that a worktree shipping a hook indexes its corpus through the service with no interaction; `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`.
- [x] `P04.S15` - Document the sandbox model, the tri-state control, fail-closed behavior, and the removed trust surface across the README and preprocessing docs; `README.md`.

## Parallelization

P01 (trust removal) and P02 (sandbox) touch mostly disjoint files and can proceed
together, with one ordering constraint: P02's runner routing (S09) assumes rules
resolve for any root, so S02 must land before S09 is verified end-to-end. Within P02,
S06 (the abstraction) precedes the three backends (S07-S08) and the runner routing
(S09); S10 closes the phase. The Windows AppContainer backend (S07) is the highest-risk
step and should be proven with its own sandbox-escape test before P04's integration
proof depends on it. P03 depends on P01 (the watcher fix assumes the trust gate is
gone). P04 hard-depends on all prior phases: the integration proof exercises the real
sandbox and the real server path together, and the docs describe the final surface.

## Verification

- No trust surface remains: `grep` finds no `_preprocess_trust`, `preprocess trust`,
  `preprocess untrust`, or `trust_all` in src, tests, or docs; `load_preprocess_rules`
  resolves a root's rules with no trust record present.
- A hook run through the sandbox proves containment against real backends: a hostile
  test hook that attempts to read a file outside the staged dir and to open a network
  socket is denied both, and its output is a clean per-file skip; a process-tree bomb
  is torn down by the Job Object.
- Fail-closed holds: with no sandbox backend available, server mode refuses to run
  hooks (loud log, surfaced status) and never runs them unconfined; the
  `VAULTSPEC_RAG_PREPROCESS_UNSANDBOXED=1` escape hatch is the only way to override,
  and it is loudly logged.
- Non-interactive end-to-end: a worktree shipping a `.vaultragpreprocess.toml` indexes
  its corpus through the running service with no trust step, and a hook failure is
  visible in the `/jobs` response (`preprocess_failures` populated).
- The watcher recognizes a changed preprocessable file and routes it through the
  sandbox; `/reindex` reports whether hooks will run for a root.
- Full gate green locally: ruff, ruff format, basedpyright, the unit suite, and the
  integration suite (service stopped) with zero failures.
- Every Step closed with a Step Record; vaultspec-code-review passes with an audit.
