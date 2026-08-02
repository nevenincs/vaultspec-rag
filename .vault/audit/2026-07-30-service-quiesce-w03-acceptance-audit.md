---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:83b3ff523186226fdae26a612e973fc123da10a6784eb3631b1e33a1c8411707'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# `service-quiesce` audit: `w03 acceptance`

## Scope

Sol-only acceptance and reconciliation against the clarified W03 plan. The
review retained the earlier S19-S25 evidence and additionally inspected the
complete S28 sequence from `71b446db` through `3d524e3b`: immutable app
runtime construction, loopback binding, discovery publication, lifecycle,
authentication, request-side registry ownership, and watcher continuations.
It also inspected merge `5dc05814` and cleanup `de91373f`. The reported
post-merge CPU-only proof is ten focused quiesce CLI and adapter tests, compile,
Ruff, scoped basedpyright, and diff validation; it carried only a pytest-cache
access warning. The earlier S28 review ran 198 focused CPU-only tests plus
`ruff check src tools` and `ty check`. No daemon lifespan, RAG endpoint,
managed Qdrant, model, Torch, CUDA, or GPU test was started.

## Findings

### requested-state-validation | resolved | CLI has real behavior coverage and no source-inspection guard

`0e7cce89` makes `_quiesce` accept pause only with `quiesce.state` equal to
`quiesced` and resume only with `quiesce.state` equal to `running`, in addition
to `ok: true`. It otherwise preserves a complete service failure when present
and returns `invalid_service_response` for an invalid or unachieved success
body. The checked-in real loopback route tests exercise achieved transitions,
idempotent transitions, a real transition conflict, and unreachable discovery.

`de91373f` removes the in-memory source rewrite and AST inspection. An
`ok: true` wrong-state body is not producible by the current truthful route, so
the exact-state condition is static, unexercised defense-in-depth under the
amended W03 boundary rather than a manufactured skewed-response claim.

### adapter-and-tui-contracts | resolved | MCP and jobs TUI preserve the controller authority

`866f399c` removes MCP lifecycle interpretation and returns the authenticated
service-state mapping unchanged; its checked-in fresh-interpreter probe compares
the route and MCP documents exactly. S27's real no-lifespan route-host test
renders the complete jobs controller block after a real registry pause, and a
real rejected jobs request renders `quiesce unavailable` without a safe borrower
signal.

The current successful jobs route always serializes the complete controller
envelope. A successful partial block is therefore impossible without a response
seam, test hook, proxy, handcrafted contract, or production-source mutation.
Those mechanisms are prohibited. The exact-field TUI validator remains static,
unexercised defense-in-depth rather than a red/green runtime claim.

### collapse-ownership | resolved | TUI consumes the controller-owned field vocabulary

Merge `5dc05814` adopts `QUIESCE_ENVELOPE_FIELDS`, derived from
`QuiesceSnapshot`, and replaces the duplicated jobs-TUI and adapter-test field
sets with that controller-owned vocabulary. It also adopts the TUI observation
composition. The single adapter-test conflict retained exact-set fail-closed
comparison, MCP's S26 pass-through, and `0576e4f4`'s removal of the
source-mutating test.

### strict-type-stubs-baseline | low | repository strict typing is not green outside S28

The configured full basedpyright gate reports 98 `reportMissingTypeStubs`
errors for `vaultspec_core.*` imports. The failures are an existing Core-stub
baseline outside S28's runtime files, not a passing gate and not grounds to
claim full W03 acceptance.

## Recommendations

S24, S26, S27, and S28 are accepted for their individual W03 scopes. S28 is
accepted for the immutable runtime seam: token, registry, and port are
one app authority; the daemon binds and publishes the same validated port;
request-side registry reads and test hosts no longer rely on server-global
assignment. Its CPU-only proof is complete. Live GPU/Qdrant integration remains
delegated and unverified.

W03.P07 implementation is complete. W03 cannot yet be called fully accepted at
the configured strict-gate boundary while the 98 Core-stub errors remain
unresolved. The CPU-only evidence does not cover live GPU/Qdrant integration,
which remains delegated and unverified. W04 is out of scope and must not start.
