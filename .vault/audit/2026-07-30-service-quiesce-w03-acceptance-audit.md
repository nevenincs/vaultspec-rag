---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-quiesce with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `service-quiesce` audit: `w03 acceptance`

## Scope

Sol-only acceptance and reconciliation against the clarified W03 plan. The
review retained the earlier S19-S25 evidence and additionally inspected the
complete S28 sequence from `71b446db` through `3d524e3b`: immutable app
runtime construction, loopback binding, discovery publication, lifecycle,
authentication, request-side registry ownership, and watcher continuations.
It ran 198 focused CPU-only tests from the current checkout, plus `ruff check
src tools` and `ty check`. No service process, RAG endpoint, managed Qdrant,
model, Torch, CUDA, or GPU test was started.

## Findings

### requested-state-validation | high | correct CLI logic has an invalid source-inspection guard

`0e7cce89` makes `_quiesce` accept pause only with `quiesce.state` equal to
`quiesced` and resume only with `quiesce.state` equal to `running`, in addition
to `ok: true`. It otherwise preserves a complete service failure when present
and returns `invalid_service_response` for an invalid or unachieved success
body. The checked-in real loopback route tests exercise achieved transitions,
idempotent transitions, a real transition conflict, and unreachable discovery.

However, `7e6d4632` adds an in-memory source rewrite followed by AST inspection
of `_quiesce`. It does not write the production file, but it is still a
forbidden source-mutation analogue and is not real-behavior evidence. An
`ok: true` wrong-state body is not producible by the current truthful route.
Remove that inspection before accepting S24; retain the condition as static,
unexercised defense-in-depth under the amended W03 boundary rather than
manufacturing a skewed response.

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

### collapse-ownership | high | TUI must consume the controller-owned field vocabulary

The local collapse branch adds `QUIESCE_ENVELOPE_FIELDS`, derived from
`QuiesceSnapshot`, and replaces the duplicated jobs-TUI and adapter-test field
sets with that controller-owned vocabulary. It also changes the TUI observation
composition. Its common ancestor is the earlier S28 acceptance commit, so this
overlaps the local S26 and S27 work.

The required integration is a normal merge before S27 closes. The collapse
branch owns the field-vocabulary refactor and TUI composition: take the derived
controller constant, delete local copies, retain the exact-set fail-closed
comparison, preserve MCP's S26 pass-through, and preserve `0576e4f4`'s removal
of the source-mutating test. This is a canonical-owner reconciliation, not a
Terra implementation choice.

### strict-type-stubs-baseline | low | repository strict typing is not green outside S28

The configured full basedpyright gate reports 98 `reportMissingTypeStubs`
errors for `vaultspec_core.*` imports. The failures are an existing Core-stub
baseline outside S28's runtime files, not a passing gate and not grounds to
claim full W03 acceptance.

## Recommendations

S26 and S28 are accepted for their individual W03 scopes. S24 remains open
until its source-inspection mutation test is removed. S27 remains open until
the controller-derived field vocabulary and TUI composition are merged under
the stated ownership. S28 is accepted for the immutable runtime seam: token,
registry, and port are
one app authority; the daemon binds and publishes the same validated port;
request-side registry reads and test hosts no longer rely on server-global
assignment. Its CPU-only proof is complete. Live GPU/Qdrant integration remains
delegated and unverified.

W03.P07 is not complete: S24 and S27 remain open. Even after their correction,
W03 cannot be called fully accepted at the configured strict-gate boundary while
the 98 Core-stub errors remain unresolved. The CPU-only evidence does not cover
live GPU/Qdrant integration, which remains delegated and unverified. W04 is out
of scope and must not start.
