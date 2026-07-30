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

Static Sol-only acceptance review of `0df85c2c`, `04660476`, `9fc85828`,
`f7fd4bd5`, and `4e9ef7ef` against the clarified W03 plan. The review inspected
the production route, projection, transport, CLI, and renderer changes plus
their checked-in CPU proof. It made no architectural inference from a delegated
review and ran no service, RAG, CUDA, GPU, test, mutation, lint, or type gate.

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

## Recommendations

For `requested-state-validation`, keep S24 open. Validate the canonical quiesce
mapping and exact requested state before any success exit, preserve the full
service body in a structured invalid-or-unachieved failure, and add real
loopback CLI guards for mismatched and malformed `ok: true` responses in both
human and JSON modes. Prove each negative guard red then green under the
project's no-mock test discipline.

After S24 remediation, complete the remaining approved P07 Steps: expose the
already-authoritative service-state block through the read-only MCP delegation
in S26, render it in the jobs TUI in S27, and prove shared vocabulary plus
Torch-free service paths in S28. These Steps depend on the P06 route vocabulary,
so starting them before P06 acceptance would have forced adapter-side inference
or duplicated an unstable contract. P06 is now accepted; W04 remains out of
scope and must not start.
