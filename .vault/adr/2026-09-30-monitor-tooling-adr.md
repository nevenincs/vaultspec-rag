---
tags:
  - '#adr'
  - '#monitor-tooling'
date: '2026-09-30'
modified: '2026-11-23'
body_schema: 'body-v2'
body_hash: 'sha256:ebb2df3b1097389cdb77d15f9d8f3e2d8f2da495e73b55f30448c3efd1e961dc'
related:
  - "[[2026-09-30-monitor-tooling-reference]]"
  - '[[2026-09-21-automatic-merge-gate-adr]]'
---

# `monitor-tooling` adr: `Monitor frontend home` | (**status:** `accepted`)

## Problem Statement

The RAG monitor needs a frontend tooling home before dashboard implementation.

## Considerations

The user requested React 19.3, Vite, TypeScript, vanilla CSS and the existing
frontend stack.

## Considered options

- Keep a root frontend manifest, with Vite rooted at `src/monitor`. Chosen
  because it preserves the requested application home.
- Place the manifest only in `src/monitor`. Rejected because the frontend
  toolchain is invoked from the repository root.

## Constraints

The original 2026-09-30 request authorized the frontend stack and the
`src/monitor` home. The later two-wave feature request authorizes the browser
application after TUI review; the user's explicit
local/no-credential/no-admin-gates direction is recorded in
`2026-09-30-monitor-browser-adr`. Service behavior remains with existing owners.

React and react-dom are pinned to 19.3.0, Vite to 8.3.1 and plugin-react to
6.1.1. Use npm and a committed lockfile, ESLint with typescript-eslint and
React Hooks rules and strict TypeScript. The initial vanilla-CSS preference is
refined by the user's explicit Carbon request: official Carbon component SCSS
and token-based custom SCSS are authorized under monitor-browser. Node follows
the installed 26.10.0 runtime.

The frontend manifest is the only source of the monitor's host and ports: the
source build on 5420 and the preview on 5421. Both Vite modes use strict ports
and bind to the declared host. Keep state and generated artifacts outside Git.

The existing merge gate owns frontend static checks alongside Python
validation. No required GitHub check or branch protection setting changes.

`2026-07-27-jobs-tui-adr` and
`2026-07-29-server-watch-observability-adr` still govern the existing terminal
interface. Reserving a frontend home does not replace it or authorize a second
implementation of service behavior. The local automatic browser transport and
bounded independent polling are settled in `2026-09-30-monitor-browser-adr`;
the service-domain contracts remain unchanged. The user's historical
2026-10-01 wildcard/Tailscale correction is reversed by the authorized
2026-10-04 security fix in `2026-10-04-monitor-access-adr`. Both strict-port
services use the declared 127.0.0.1 host; the shared guard rejects remote
peers and authorities even if a development launch overrides the listener.
Local automatic credentials remain supported. Direct Tailnet and Tailscale
Serve access are unsupported.

The npm lockfile and Vite build remain canonical. For release delivery,
monitor-delivery adds Bun solely for native server compilation and embedded
asset packaging; the compiled command does not require npm, Node or Vite at
launch.

## Amendment, 2026-11-23

On the maintainer's explicit instruction of 2026-11-23, the shared frontend
lifecycle tool this record originally adopted, with its workflow, recipes and
byte-parity guard, is removed from the repository, and every commitment this
record made to it is withdrawn. The frontend home, the pinned stack and the
manifest-declared ports above stand.

## Implementation

Add a root package manifest and tooling configuration. The initial entry used
`src/monitor/index.html` as an empty build entry. The later authorized Carbon
implementation adds the presentation and local adapter under that home,
without changing daemon endpoints. Verify TypeScript, lint and build.

## Rationale

A single declaration gives Vite and the standalone monitor the same host and
ports. The root manifest keeps the requested application home.

## Consequences

Frontend dependencies remain separate from Python packaging. The user's
2026-10-02 request authorizes a daemon-owned monitor for managed server
start/stop under `2026-10-02-monitor-lifecycle-adr`. Its actual port starts at
the backend port plus one and advances until free; the fixed manifest
allocation governs standalone development. The initial browser entry was
blank; the user's subsequent feature request now authorizes the Carbon
application after the passing TUI review. The monitor's loopback-only
declaration must not be exposed through an unauthenticated remote proxy.
