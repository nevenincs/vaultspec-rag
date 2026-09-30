---
tags:
  - '#adr'
  - '#monitor-tooling'
date: '2026-09-30'
modified: '2026-09-30'
body_schema: 'body-v2'
body_hash: 'sha256:3374fadb198555994f6b69d28271199c96d12473208134e324f31771bde15af1'
related:
  - "[[2026-09-30-monitor-tooling-reference]]"
  - '[[2026-09-21-automatic-merge-gate-adr]]'
---

# `monitor-tooling` adr: `Monitor frontend home and shared devserver contract` | (**status:** `accepted`)

## Problem Statement

The RAG monitor needs a frontend tooling home before dashboard implementation.
Concurrent frontend projects require stable ports and shared lifecycle control.
Evidence is recorded in `2026-09-30-monitor-tooling-reference`.

## Considerations

The user requested React 19.3, Vite, TypeScript, vanilla CSS, the existing
frontend stack and devserver conformance. The private devservers repository
already owns port allocation conventions, lifecycle supervision and proxy aliases.

## Considered options

- Adopt the canonical harness and root frontend manifest, with Vite rooted at
  `src/monitor`. Chosen because it meets enrollment discovery and preserves
  the requested application home.
- Place the manifest only in `src/monitor`. Rejected because canonical
  discovery does not reach that depth.
- Build another lifecycle controller or repeat ports in configs. Rejected
  because it would diverge from the requested workstation standard.

## Constraints

Authorization: the user's 2026-09-30 request authorizes the harness, shared
frontend stack, strict non-overlapping allocation and `src/monitor` home.
It does not authorize dashboard, API adapter or service-domain implementation.

React and react-dom are pinned to 19.3.0, Vite to 8.3.1 and plugin-react to
6.1.1. Use npm and a committed lockfile, ESLint with typescript-eslint and
React Hooks rules, strict TypeScript, and vanilla CSS when application work
begins. Node follows the enrolled portfolio frontend's installed 26.10.0
runtime; the shared harness does not pin Node itself.

The frontend manifest is the only source of service ports. Allocate
5420-5439 with dev on 5420 and preview on 5421. Both Vite modes use strict
ports and bind to the declared host. Name the proxy route
`vaultspec-rag-monitor`. Keep state and generated artifacts outside Git.

The canonical lifecycle script, recipe and workflow remain identical to the
private devservers source. This session adopts its separate frontend lifecycle
workflow as expressly requested frontend CI parity; the existing merge gate
owns frontend static checks alongside Python validation. No required GitHub check or branch
protection setting changes.

This is a narrow frontend-lifecycle exception to the sole pull-request workflow
ownership in `2026-09-21-automatic-merge-gate-adr`: the canonical supplemental
workflow reports its own lifecycle check, while the existing required aggregate
owns frontend static checks and Python validation. The shared workflow retains
its owner's name; a byte guard enforces its exact template.

The user separately authorized fixing the canonical trust condition on a
devservers feature branch. The adopted correction is commit
`b15e302441c426ba3604ec8ce2178bcfe8b394af`; it restricts pull requests to ready
owner/collaborator work or an explicit human-applied full-run label.
Canonical main-copy parity remains pending that upstream branch landing.

On 2026-09-30 the user explicitly authorized treating the shared Python script
as externally maintained code: check it with its owner's Ruff rules and verify
its adopted byte digest. RAG's strict lint and type profiles continue to check
RAG-owned Python. The shared copy is excluded from those incompatible profiles;
its owner lint and formatting checks join both CI lint aggregates, and the
byte guard joins the existing accelerator-free test collection.

`2026-07-27-jobs-tui-adr` and
`2026-07-29-server-watch-observability-adr` still govern the existing terminal
interface. Reserving a frontend home does not replace it or authorize a second
implementation of service behavior. Browser authentication, transport and
event delivery remain undecided for future implementation.

## Implementation

Add a root package manifest, tooling configuration and lifecycle recipes.
Use `src/monitor/index.html` as an empty build and health-check entry; add no
React component, data client, dashboard styles or service endpoint.
Copy the shared harness through its sync tool and verify parity, start,
reattach, stop, registry allocation, TypeScript, lint and build.

## Rationale

A single declaration gives Vite, the supervisor and the registry the same
ports. The root manifest accommodates canonical discovery without changing
the requested application home. The shared harness supplies existing proxy
control and process ownership rather than another implementation.

## Consequences

Frontend dependencies remain separate from Python packaging and the resident
RAG service. The browser stays blank until application work is authorized.
The registry can inspect this branch with `--worktree monitor`; ordinary
main-only registry and tailnet generation pick it up after landing.
Tailnet HTTPS uses the established port offset. Its feature-worktree mapping
must be applied explicitly while the main checkout lacks the declaration.

A stack upgrade must follow the shared standard rather than change one
consumer independently.
