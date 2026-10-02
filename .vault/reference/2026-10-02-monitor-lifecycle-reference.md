---
tags:
  - '#reference'
  - '#monitor-lifecycle'
date: '2026-10-02'
modified: '2026-10-02'
body_schema: 'body-v2'
body_hash: 'sha256:b54a793375c408700d5d66794c67a8a88f8d0739ce141b87d54a9578ffa8eb4e'
related: []
---

# `monitor-lifecycle` reference: `Managed monitor lifecycle seams`

## Summary

Source checkpoint: `1cb00875` on `feature/monitor`. The current backend rejects an occupied requested TCP port through its existing bind probe; it has no incrementing backend allocator: `src/vaultspec_rag/cli/_service_start.py:615`, `src/vaultspec_rag/cli/_process.py:215`. Monitor allocation must therefore reuse Vite's binding/retry behavior rather than copy an alleged backend scanner.

The daemon acquires the singleton lease before subordinate startup. Its lifespan rolls back started components on every pre-yield failure and deletes both discovery views under owner authority: `src/vaultspec_rag/server/_lifespan.py:264`, `src/vaultspec_rag/server/_lifecycle.py:151`. Complete snapshots, rather than client-side merges, must carry monitor assignment so heartbeat repair preserves it.

The existing frontend bridge is a Vite plugin shared by dev and preview, resolves local service discovery and invokes canonical Python lifecycle owners: `src/monitor/server/local-service.ts:235`, `src/monitor/server/local-service.ts:308`, `vite.config.ts:12`. A managed entry can reuse this server configuration with a runtime port override. Its Python interpreter must be the launching daemon's environment rather than an unrelated installed tool.

Windows operator stop forcibly terminates the detached daemon, bypassing its lifespan cleanup. The CLI confirms death before clearing discovery: `src/vaultspec_rag/cli/_service_stop.py:284`. Monitor cleanup needs independently recorded PID/incarnation evidence plus parent-death detection; PID alone must not authorize termination. Shared process probes already supply incarnation checks and bounded signals: `src/vaultspec_rag/_process_probe.py:64`.

The fixed manifest ports and shared harness govern source development. Managed daemon-derived ports are a scoped runtime exception. CI builds, bundled assets and packaging are owned by another session and excluded here.

Verified implementation detail: on Windows, Vite's wildcard bind can coexist with a loopback listener that was created without exclusive binding. The initial real occupied-port test exposed this. The canonical backend bind probe was moved to `src/vaultspec_rag/_ports.py:11`; `next_available_port` uses it before Vite's native retries. Tests reserve both IPv4 and IPv6 availability to establish the expected first free monitor port. Managed startup, publication, canonical shutdown, parent-pipe death and orphan identity checks are exercised through actual Node/Python subprocesses without model loading.

## Compiled runtime handoff

The user's subsequent clarification requires compiled resources. The concurrent delivery design proposes a self-contained `vaultspec-rag-monitor` Bun executable, with embedded Vite output and the shared bridge, but explicitly records that no binary has been built: `2026-10-02-monitor-delivery-adr`, Constraints; `2026-10-02-monitor-delivery-plan`, S01-S02. Compilation, trust pins, acquisition and archive installation stay with that producer. The lifecycle supervisor consumes the resulting installed executable and no longer launches a source Vite entry. Earlier real Node process evidence establishes the prototype lifecycle only; positive compiled-executable integration remains pending the artifact.
