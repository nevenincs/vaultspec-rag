---
tags:
  - '#adr'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-30'
related:
  - "[[2026-06-27-rag-broker-affordances-research]]"
---

# `rag-broker-affordances` adr: `idempotent JSON start and a machine-global discovery pointer` | (**status:** `accepted`)

## Problem Statement

The cross-project service-management audit's dashboard handover recorded two optional
rag-side coordination asks that make rag's single-machine service cleaner for an
out-of-process broker to manage; both are unaddressed. (1) `server start` is not idempotent
for a broker - a healthy owned service already running causes the port/machine guards to
exit 1 before the idempotent "already running" path is reached, and there is no `--json`
mode, so a broker that speculatively starts rag sees an opaque gateway fault instead of
"already running, attach" (the audit's C1 exit-1->502 flattening at its source). (2)
Discovery is `service.json` under `VAULTSPEC_RAG_STATUS_DIR`, with no machine-global
pointer, so a consumer that does not share rag's STATUS_DIR cannot find the one running
service - even though the machine lock that proves the singleton is deliberately
STATUS_DIR-independent. This ADR decides both rag-side fixes: an idempotent `server start --json` that exits 0 with a structured `already_running` envelope, and a
STATUS_DIR-independent machine-global discovery pointer written beside the machine lock.

## Considerations

- Both are **additive and consumer-optional**: `--json` is opt-in (the human start output
  is untouched), and the machine-global pointer is an ADDITIONAL file (the STATUS_DIR
  `service.json` is unchanged), so no current consumer - and no dashboard change - is
  required for either to land. rag ships the capability; the broker opts in later.
- The idempotent fix is a **reorder plus a JSON contract**, not new lifecycle machinery:
  `_existing_service_running()` already computes the running pid/port; moving the idempotent
  check ahead of the guards and the human printing out to the caller is the whole change.
- The daemon **already writes a versioned discovery file** atomically on every heartbeat;
  the machine-global pointer is the same payload written a second time to a fixed
  STATUS_DIR-independent path beside the lock, cleaned on shutdown on the same hooks.
- The **machine lock remains the singleton authority**; the pointer is informational
  discovery, never a second source of truth for "may a service start" (that stays the OS
  advisory lock).

## Constraints

- **Parent stability.** Depends on `_service_lifecycle.py` (`service_start`,
  `_existing_service_running`), `_render._emit_json`, `_machine_lock.py` (`machine_lock_path`),
  the daemon `server/_lifecycle.py` heartbeat/shutdown hooks, and the shipped
  `SERVICE_DISCOVERY_SCHEMA`/`VERSION` (service-discovery-schema ADR) - all stable on `main`.
  No frontier risk: a reorder, a `--json` branch, and a second atomic file write.
- **Test isolation is mandatory.** Both touch managed-singleton paths, so every test sets
  `VAULTSPEC_RAG_STATUS_DIR` and `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` to temp paths before
  exercising start/discovery (the `managed-singleton-paths-isolate-storage-dir-in-tests`
  and `service-tests-isolate-status-dir` rules), and `reset_config()` around each.
- **No mocks** (project mandate): the start tests drive the real command with a real
  temp-isolated status file; the pointer tests assert the real file written beside a real
  temp lock.
- **Atomic, crash-safe writes.** The pointer write reuses the heartbeat's `.tmp` +
  `os.replace`, and is cleaned best-effort on shutdown like `service.json` - a stale
  pointer from a crash is truthful "stale" to a heartbeat-aware reader, never corruption.

## Implementation

Four decisions.

**D1 — Reorder `server start` so the idempotent check precedes the guards.** Move
`_existing_service_running()` ahead of the port and machine guards: a healthy owned service
is `already_running` (success) before the guards, which then only catch the genuine
"another process holds the port" / "another service owns the machine" cases. The human path
is unchanged; the friendly idempotent return stops being shadowed by the port-guard exit 1.

**D2 — `server start --json` emits one envelope per outcome.** Add a `--json` option;
`_existing_service_running()` is refactored to RETURN the running pid/port (the caller does
the human print or the JSON emit). In `--json` mode every exit path emits one `_emit_json`
document: `already_running` (ok, exit 0, pid+port), `started` (ok, exit 0,
pid+port+startup_s), and the failures (`port_in_use`, `machine_owned` with the holder pid,
`daemon_breakaway`, `start_timeout`) as `ok:false` error envelopes exiting non-zero. This
mirrors the storage verbs' and `server status` JSON discipline.

**D3 — A machine-global discovery pointer beside the lock.** Add
`machine_discovery_path()` to `_machine_lock.py` (the machine-global-path owner):
`machine_lock_path().parent / "service.json"`, STATUS_DIR-independent, distinct from the
STATUS_DIR file. The daemon's `_heartbeat_tick_sync` writes the SAME versioned discovery
payload to it (one writer shape, reusing `.tmp` + `os.replace`), and shutdown cleans it
alongside the STATUS_DIR file. A tolerant `read_machine_discovery()` parses it (a
missing/unreadable file is truthful absence), so a consumer finds the one service
regardless of its own STATUS_DIR.

**D4 — The lock stays the authority; the pointer is discovery only.** The pointer never
gates startup and never replaces the OS advisory lock; it carries the same heartbeat
staleness contract the STATUS_DIR file does, so a reader judges liveness the same way. A
divergence between the two files (e.g. a half-written tick) resolves on the next heartbeat;
neither is authoritative over the lock.

## Rationale

The decisions follow the audit's two coordination asks and rag's existing seams (research
F1-F5). The idempotent reorder (D1) is the minimal fix to the C1 flattening at its source -
the friendly path already exists, it is merely shadowed - and the `--json` contract (D2)
makes every outcome a parseable document a broker can branch on, matching the discipline
the storage and status verbs already use. The machine-global pointer (D3) closes the
singleton/discovery asymmetry: the lock is already STATUS_DIR-independent, so anchoring the
pointer beside it makes discovery as machine-global as the singleton it advertises, and
riding the existing atomic heartbeat write keeps it crash-safe with no new machinery.
Keeping the lock authoritative (D4) preserves the single-seat guarantee - the pointer is a
convenience for finding the service, never a second gate on starting one.

## Consequences

- **Gains.** A broker can speculatively `server start --json` and get `already_running`
  (exit 0) to attach, instead of an opaque 502 - the C1 fix at the source. A consumer that
  does not share rag's STATUS_DIR (the per-scope-isolation case) can find the one running
  service via the machine-global pointer. Both are additive: existing CLI/human use and the
  STATUS_DIR file are untouched.
- **Honest difficulties.** Two files now describe the same service (STATUS_DIR + the
  machine-global pointer); they are written from one tick so they agree, but a reader must
  treat the pointer as discovery (apply the heartbeat staleness contract), not authority.
  The `--json` start must cover every exit path or a broker hits an unparseable outcome -
  the test matrix must enumerate them. The reorder must not weaken the guards for the
  genuine cases (a foreign process on the port, another config owning the machine still
  fail).
- **Pathways opened.** A `server stop --json` sibling, the dashboard's adoption (pass
  `--json` to its start broker; add the machine-global pointer as a discovery candidate),
  and a future where the pointer is the canonical machine discovery and the STATUS_DIR file
  is the per-config detail.
- **Pitfalls to avoid.** Letting the pointer gate startup (the lock is the authority);
  emitting human text on a `--json` path; reordering so a foreign port holder is mistaken
  for our service; or forgetting to clean the pointer on shutdown (a stale pointer is
  tolerable but should be cleaned like `service.json`).

## Codification candidates

- **Rule slug:** `broker-facing-cli-outcomes-are-structured-and-idempotent`.
  **Rule:** A lifecycle CLI verb a broker drives must, in `--json` mode, emit exactly one
  structured envelope on every exit path (success and each failure) and treat an
  already-satisfied request as a success (exit 0 with an `already_*` status), never a
  non-zero fault a broker would misread as a gateway error.

(Holds one full execution cycle before promotion, per the codify discipline. Complements
`service-domain-owns-operability` and the dashboard-side
`brokered-destructive-verbs-validate-args-and-default-to-preview`.)
