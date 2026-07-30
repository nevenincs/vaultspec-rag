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

### requested-state-validation | high | CLI accepts an unachieved successful lifecycle body

`_quiesce` in `src/vaultspec_rag/cli/_service_quiesce.py` exits zero for every
mapping whose `ok` value is true. It does not validate that pause carries
`quiesce.state` equal to `quiesced`, or that resume carries
`quiesce.state` equal to `running`. Commit `f7fd4bd5` therefore preserves
service-owned failures correctly but does not satisfy S24's clarified rule that
success requires both `ok: true` and the requested achieved canonical state. A
malformed or skewed service can still make the CLI report success for an unsafe
or opposite state.

No other acceptance-blocking defect was found in S19 through S23 or S25 by
static inspection. Those Steps are accepted from the named commits and their
checked-in proof, subject to the unrun validation boundary below.

### strict-type-stubs-baseline | low | repository strict typing is not green outside S28

The configured full basedpyright gate reports 98 `reportMissingTypeStubs`
errors for `vaultspec_core.*` imports. The failures are an existing Core-stub
baseline outside S28's runtime files, not a passing gate and not grounds to
claim full W03 acceptance.

## Recommendations

For `requested-state-validation`, keep S24 open. Validate the canonical quiesce
mapping and exact requested state before any success exit, preserve the full
service body in a structured invalid-or-unachieved failure, and add real
loopback CLI guards for mismatched and malformed `ok: true` responses in both
human and JSON modes. Prove each negative guard red then green under the
project's no-mock test discipline.

S28 is accepted for the immutable runtime seam: token, registry, and port are
one app authority; the daemon binds and publishes the same validated port;
request-side registry reads and test hosts no longer rely on server-global
assignment. Its CPU-only proof is complete. Live GPU/Qdrant integration remains
delegated and unverified.

W03.P07 remains in progress. Next, remediate the S24 high finding, then expose
the already-authoritative block in S26 and render it in S27. Re-run the W03
CPU acceptance suite after those three steps and resolve the Core-stub baseline
before calling the full strict gate green. W04 remains out of scope and must
not start.
