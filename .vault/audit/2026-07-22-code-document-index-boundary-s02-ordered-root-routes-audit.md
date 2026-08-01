---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:e3d3382fd16bb4bec18056075e169516a329fb8d49dfe77d24931ebc30c29017'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
  - "[[2026-07-21-code-document-index-boundary-adr]]"
---

# `code-document-index-boundary` audit: `S02 ordered root routes`

## Scope

Audit `W01.P01.S02` against the accepted routing boundary. Review the raw and typed
contracts for deterministic caller order, immutable values, fail-closed preservation of
unknown target tokens, and independence from preprocessing execution.

## Findings

Status: **PASS**. No critical, high, medium, or low findings remain.

`ContentRouteConfig` retains raw targets so a later compiler can return a structured error
for unknown values rather than erasing a rule. `RootContentPolicyConfig` and
`RootContentPolicy` preserve precedence through immutable tuples, and `ContentRoute` binds
only a generic project-relative pattern to a closed `ContentKind`.

No type contains an extractor command, preprocessing rule, repository-directory heuristic,
or parser-capability decision. Empty and NUL-bearing patterns are rejected at construction.
Focused Ruff, Ty, and a real raw-to-typed order-preservation probe pass.

## Recommendations

Proceed to `W01.P01.S03`. Keep transform configuration separate and require its target and
extractor version without changing the route tuple's declared order.
