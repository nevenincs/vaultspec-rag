---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-30'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` Phase P08 Summary — Empirical Service Validation

## Overview

Empirical end-to-end validation of the live RAG service (real GPU — RTX 4080 SUPER,
real Qdrant, Windows). Goal: prove the functional core (index, search, filter, reindex,
incremental, concurrency, local fallback, service management) actually works against a
running daemon and locally.

## Results by step

- **S25 baseline:** daemon initially stopped per CLI (`status` exit 3). In-process status
  worked: GPU detected, existing index 405 vault docs / 3661 code chunks.
- **S26 lifecycle:** clean `server service start` → PID, port 8766, 16.6s startup,
  `service.json` written, status running/ready/CUDA/models-loaded (exit 0). Clean
  `server service stop` → stopped (exit 0), port freed, `service.json` removed.
- **S27 index / S14:** REST `/reindex` (vault, incremental) queued an async job that
  completed `+12 /9 -0 (973ms)` — it detected and indexed real new docs.
- **S28 search + filters:** REST `/search` returns ranked results for vault and code.
  Filters verified: vault `doc_type=adr` (3 ADRs); code `include_paths=src/vaultspec_rag/*`
  (5 results incl. `embeddings.py`), `cli/*` (0 — correct), `exclude_paths=*/tests/*`
  (5 results, 0 test paths). CLI `--port` vault delegation works.
- **S29 reindex + incremental:** incremental diffing proven (S27 `+12 /9`); the watcher is
  running (`watch_enabled=true`, debounce 2000ms, cooldown 30s, watching the project root).
- **S30 concurrency:** 6 concurrent REST `/search` requests all succeeded, no lock errors.
- **S31 vacate:** CLI-managed `stop` cleanly vacated the daemon and released the port/lock.
- **S32 local fallback:** in-process search works with the daemon down; dead `--port`
  hard-fails (exit 1, "unreachable"); dead `--port --allow-fallback` runs in-process. All
  three behaviours correct.
- **S33 recovery:** after clearing a stale daemon, a fresh `start` reclaimed the persisted
  Qdrant lock files and served again — recovery demonstrated.

## Functional verdict

The functional engine is **complete and working**: index/reindex (incl. incremental),
search (vault + code) over REST and local in-process, all filter types, concurrent
clients, the running watcher, and the full local-fallback contract.

## Out-of-scope findings (deferred to service redesign — tracked in issue #181)

A cluster of service-management / observability / error-handling divergences surfaced and
were **deliberately left out of scope** per maintainer direction (related production
service-management issues need dedicated treatment; see #166):

- CLI cannot observe or vacate a healthy orphaned daemon whose `service.json` is missing.
- `server service start` exits 0 when the port is already in use.
- `server service logs` returns nothing despite a populated log file.
- REST endpoints raise an unhandled `ValueError` → HTTP 500 on missing `project_root`
  (should be a 400).
- CLI auto-delegation (no `--port`) omits the service token → 401 while a daemon is up and
  holds the Qdrant lock.

These are filed in #181 for the scheduled service architectural redesign. The deconflation
code and the functional core are verified independently and are merge-ready.
