---
tags:
  - '#reference'
  - '#monitor-capability'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:c963b405349c724753b31cee702e45a13a3603e7105668f44db141269ae4da86'
related:
  - "[[2026-10-04-monitor-access-adr]]"
  - "[[2026-10-04-loopback-http-security-adr]]"
---

# `monitor-capability` reference: `Monitor caller authentication boundary`

Inspected checkout d126f083 on 2026-10-04 before the fix. The user supplied a validated high-severity finding: the loopback monitor authenticates no caller, so any local OS account can borrow the service owner's backend authority. Independent source tracing confirms it.

## Summary

Admission is network metadata only. `localRequest` accepts an exact loopback socket peer, a local Host and a matching Origin when present: `src/monitor/server/local-service.ts:38`. Loopback is shared by every account on the host, so these checks separate remote from local callers and cannot separate the owner from another local user. The middleware dispatches every admitted request: `src/monitor/server/local-service.ts:483`.

The bridge then acts for the caller. The allowlist admits reads of jobs, logs, queries, repositories and storage, plus lifecycle start/stop, pause/resume, repository enrollment, resident eviction and job controls: `src/monitor/server/local-service.ts:158`. Lifecycle routes spawn the canonical owner command as the monitor's user: `src/monitor/server/local-service.ts:313`, `src/monitor/server/local-service.ts:421`. Every other route reads the owner-only discovery credential and injects it upstream: `src/monitor/server/local-service.ts:55`, `src/monitor/server/local-service.ts:431`. Inventory reads fall back to a second owner subprocess: `src/monitor/server/local-service.ts:336`. The backend's own token gate therefore sees the owner on every forwarded call, including enrollment: `src/vaultspec_rag/server/_routes_operator.py:211`. Enrollment of an attacker-chosen directory chains into the service's default preprocessing and so into execution as the service owner.

The existing controls do not close this. Token redaction keeps the backend credential out of responses (`src/monitor/server/local-service.ts:190`) but the caller never needs it. Protected same-user discovery keeps another account from reading the credential file, and the monitor reads it on that account's behalf.

## Owner channels that already exist

A caller credential needs a channel only the owner can read. Two exist. The managed monitor's stdout is a pipe to the daemon, which parses the readiness line and never logs it: `src/monitor/server/standalone.ts:191`, `src/vaultspec_rag/monitor_process.py:220`. The daemon publishes monitor fields into service discovery (`src/vaultspec_rag/monitor_process.py:143`, `src/vaultspec_rag/server/_lifecycle.py:205`), which is written with private permissions and a protected Windows DACL: `src/vaultspec_rag/_atomic_write.py:236`. `server start` already rebuilds the monitor URL from that record on first start and on idempotent reuse: `src/vaultspec_rag/cli/_service_start.py:507`. A directly launched monitor and the Vite dev and preview servers write to the launching user's terminal: `src/monitor/server/vite-plugin.ts:4`.

## Browser constraints

The browser reaches the bridge through one fetch helper: `src/monitor/model.ts:95`. The application routes by URL fragment (`src/monitor/App.tsx:47`), so a fragment-carried secret must be consumed and removed before it is read as a page. A fragment is never sent to a server, logged by one, or placed in a Referer. Session storage is partitioned by scheme, host and port; cookies on a loopback host are shared across every port and would be sent to another account's listener. Owner-ACL Unix sockets cannot be reached by a browser. Peer-credential lookup for loopback TCP needs a different privileged mechanism on each platform and is unavailable to the Node entry used by Vite.

Repository enrollment is already an explicit operator action: a modal with a typed path and a submit control, sent as one POST: `src/monitor/Inventory.tsx:326`.

## Version skew

The daemon and the compiled monitor ship in one archive but can be selected independently through the executable override: `src/vaultspec_rag/monitor_process.py:36`. A credential handed from parent to child would be ignored by an older monitor, leaving it open while the daemon reports it protected. A credential minted by the child and reported on the readiness line fails the coupled start in both skew directions, because each side rejects the other's line shape.

## Existing coverage

Admission tests call the middleware and real listeners with no credential and expect success for loopback peers: `src/vaultspec_rag/tests/test_monitor_access.py:16`, `src/vaultspec_rag/tests/test_monitor_browser.py:36`, `src/vaultspec_rag/tests/test_monitor_process_integration.py:127`. The delivered-binary smoke and the installed-browser driver do the same: `tools/monitor/smoke.py:303`, `dev/monitor-browser.mjs:60`. Each needs the owner's access link, and new coverage must prove that a loopback caller without the capability, and one presenting only the backend token, reaches neither the credential read nor an owner subprocess.
