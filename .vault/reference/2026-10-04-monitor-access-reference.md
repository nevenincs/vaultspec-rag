---
tags:
  - '#reference'
  - '#monitor-access'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:9d23cbbbd4fc927f389370351a809dd1d66e38c49808bea2005d67aedd80b2a0'
related:
  - "[[2026-09-30-monitor-browser-adr]]"
  - "[[2026-09-30-monitor-tooling-adr]]"
  - "[[2026-10-02-monitor-delivery-adr]]"
---

# `monitor-access` reference: `Monitor credential-bearing request boundary`

## Summary

Inspected checkout 9785414e55596cbb983f99dfe2fc1eba4d7d8fbb on 2026-10-04 before the security fix. The user supplied a validated finding that any routed Tailnet peer can operate the monitor without an application credential. Independent source tracing confirms it.

The shared monitor admission guard accepts loopback or Tailnet source ranges, a declared/local/Tailnet Host, and an optional Origin matching Host; it never authenticates a remote caller: `src/monitor/server/local-service.ts:24`, `src/monitor/server/local-service.ts:55`. The route allowlist admits operational reads and lifecycle, job, enrollment, pause/resume and eviction controls: `src/monitor/server/local-service.ts:178`. Admitted lifecycle calls invoke the local owner command directly; other operations inject a local credential from service discovery or health recovery: `src/monitor/server/local-service.ts:430`, `src/monitor/server/local-service.ts:459`. Request headers cannot substitute for caller identity at this credential-bearing boundary.

Both Vite modes and the compiled server use this middleware. All use the manifest host, currently 0.0.0.0: `src/monitor/server/vite-plugin.ts:8`, `vite.config.ts:14`, `vite.config.ts:20`, `src/monitor/server/standalone.ts:84`, `package.json:19`. A single middleware guard and manifest correction cover all entry paths. Guarding before middleware dispatch also covers static assets and build metadata. Rejecting Tailnet authorities prevents the documented Tailscale Serve mapping from preserving its original hostname through a loopback proxy.

Existing tests prove credential-free loopback reads and canonical controls through real service routes, but the Tailnet authority test uses loopback with a forged Host rather than a real routed peer: `src/vaultspec_rag/tests/test_monitor_browser.py:123`, `src/vaultspec_rag/tests/test_monitor_browser.py:345`. Socket-address unit coverage must include Tailnet IPv4, IPv6 and mapped IPv4 plus forwarded-header spoofing. Real HTTP coverage must retain local reads/control behavior and refuse a non-admitted source. Listener coverage must exercise Vite dev, preview and the compiled command.

The earlier accepted browser, tooling and delivery decisions explicitly permit wildcard/Tailnet credential-free access. They require a scoped network-policy exception; service ownership, automatic local credentials, fixed development ports, managed allocation and parent-pipe shutdown can remain.

## WebSocket boundary

Review of the installed Vite 8.3.1 implementation confirmed that HMR and ping upgrades bypass Connect middleware: `node_modules/vite/dist/node/chunks/node.js:24420`. A real TCP client sourced from 127.0.0.2 with local Host and no Origin received 101 under a wildcard dev override; a malformed vite:invoke message then crashed the development monitor. Apply the same admission predicate in a prepended upgrade listener for dev and preview: `src/monitor/server/vite-plugin.ts:8`, `src/monitor/server/local-service.ts:479`. Real upgrade tests retain local HMR/ping while rejecting non-admitted peers and Tailnet authorities.

## Guard verification

Mutation proofs ran in an isolated checkout, restoring each mutation before the next: restoring Tailnet peer admission, limiting admission to API paths, restoring Tailnet Host admission, restoring wildcard Vite binding, compiling a wildcard native listener, compiling an admission bypass, and removing Vite upgrade admission each failed the intended refusal assertion (exit 1). Restoring the guard passed (exit 0). The mutation and affected assertion are recorded beside the regression tests. No mutation was applied to the shared working tree.
