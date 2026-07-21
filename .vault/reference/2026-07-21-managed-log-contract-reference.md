---
tags:
  - '#reference'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-04-12-store-eviction-log-rotation-adr]]"
  - "[[2026-06-24-service-hardware-singleton-adr]]"
  - "[[2026-06-01-service-observability-adr]]"
---

# `managed-log-contract` reference: `current log ownership, Qdrant 1.18.2, and operator paths`

This reference pins the current Vaultspec RAG log writers, readers, and operator
adapters, plus Qdrant 1.18.2's operational logging behavior. It is the implementation
grounding for a uniformly bounded, source-aware replacement contract.

## Summary

### Current writers

- The resident service installs `DaemonRotatingFileHandler` in
  `src/vaultspec_rag/server/_main.py:127-143`. The handler receives
  `service_log_max_bytes` and `service_log_backup_count`, whose defaults are 10 MiB and
  five backups in `src/vaultspec_rag/config.py:503-504`. The active file plus backups
  therefore has a 60 MiB default bound.
- `DaemonRotatingFileHandler` in `src/vaultspec_rag/logging_config.py:223-413` owns the
  Windows-specific stdout and stderr rebinding needed after service-log rollover. Its
  copy-truncate fallback preserves bounded backups when another Windows handle blocks
  rename.
- `QdrantSupervisor` merges child stdout and stderr into a pipe at
  `src/vaultspec_rag/qdrant_runtime/_supervise.py:424-453`. Its drain thread opens
  `status_dir/qdrant.log` once per child with `O_APPEND`, writes and flushes every line,
  and closes only at end-of-file (`:477-508`). No size check, rollover, or retention
  setting reaches this path.
- Qdrant restarts and quarantine retries reopen the same path in append mode. The
  50-line `recent_output` deque bounds only failure diagnostics, not disk usage
  (`src/vaultspec_rag/qdrant_runtime/_supervise.py:50-54,510-513,575-665`).

### Qdrant 1.18.2 boundary

The managed binary is Qdrant 1.18.2, build
`44ad62f8cd69642be5afa6441612525e24a0d063`. Its pinned
`config/config.yaml:1-15` says operational logs go to stdout by default and warns that
the optional on-disk file may grow indefinitely. The upstream sink in
`src/tracing/on_disk.rs:79-89` also opens append-only without rotation. Qdrant audit-log
rotation is a separate authenticated-operation facility and cannot replace supervised
stdout and panic capture.

Vaultspec must therefore rotate the output it already owns at the pipe-drain boundary.
Enabling Qdrant's native on-disk logger would create another unbounded file.

### Current reader and adapters

- `read_service_log` resolves only `cfg.log_file`, normally `service.log`, and its
  numbered backups (`src/vaultspec_rag/logging_config.py:133-194`). It stops backup
  discovery at the first missing suffix, so a set containing `.1`, `.3`, and `.5`
  silently omits `.3` and `.5`.
- Both `GET /logs` and `GET /logs/json` call only `read_service_log`
  (`src/vaultspec_rag/server/_routes.py:162-187,908-920`).
- `server logs` calls the JSON route through the admin transport and has no source
  argument or local-file fallback (`src/vaultspec_rag/cli/_service_logs.py:495-579`,
  `src/vaultspec_rag/serviceclient/_transport.py:317-331`). A stopped service therefore
  makes retained logs unavailable through the CLI.
- The human activity parser accepts Python timestamps shaped as
  `YYYY-MM-DD HH:MM:SS`. Qdrant emits RFC 3339 timestamps shaped as
  `YYYY-MM-DDTHH:MM:SSZ`, so simply merging raw lines would discard Qdrant entries
  (`src/vaultspec_rag/cli/_service_logs.py:24-57,264-270`).

### Implementation translation

- Keep independent service and Qdrant files so each producer preserves raw diagnostic
  fidelity. Apply one generic per-source size and backup policy to both.
- Do not reuse the service handler's `dup2` behavior for Qdrant. The Qdrant drain owns a
  single file handle and needs close, rotate, securely reopen, and continue semantics.
- Replace the service-only reader with one source-aware service-domain reader. It must
  enumerate numeric backups without assuming contiguous suffixes and must bound both
  searched history and returned lines.
- Return grouped, source-tagged service and Qdrant results. Do not synthesize a global
  chronology from unlike timestamp formats and multiline records.
- Route live HTTP and offline CLI reads through the same reader contract. Keep adapters
  thin and remove the legacy service-only reader, payload, configuration, and parser
  paths rather than retaining aliases.

### Verification blueprint

Existing real-behavior service tests cover bounded rollover and post-rollover writes in
`src/vaultspec_rag/tests/integration/test_service_eviction.py:277-383`. Qdrant drain
tests cover raw capture and the in-memory ring only in
`src/vaultspec_rag/tests/test_qdrant_supervise_diagnostics.py:24-77`.

The replacement needs real-behavior coverage for Qdrant rollover, backup count,
pre-existing oversized files, restart continuity, gap-tolerant reads, source selection,
bounded filters, live HTTP access, local post-crash access, and current human or grouped
rendering. Tests must import production behavior and use no mocks, patches, stubs,
monkeypatches, skips, or xfails.
