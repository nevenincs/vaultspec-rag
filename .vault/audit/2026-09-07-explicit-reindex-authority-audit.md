---
tags:
  - '#audit'
  - '#explicit-reindex-authority'
date: '2026-09-07'
modified: '2026-09-07'
body_schema: 'body-v2'
body_hash: 'sha256:4e24ad6074fd94d293a9dbca298045c7a246530ae24f682b2f967afc4d887c0a'
related:
  - "[[2026-09-07-explicit-reindex-authority-plan]]"
---

# `explicit-reindex-authority` audit: final verification

## Scope

The audit traced the incident from the user service log through indexing mode
selection, storage identity, watcher retry state, integrity remediation,
health reporting, and startup failure handling. It then reviewed the completed
implementation against the accepted explicit-authority ADR.

## Findings

### published-backend-provenance | high | Published sidecars did not identify their storage backend

The first implementation bound resumable run ledgers to the backend but left
the code and document publication sidecars backend-agnostic. A server search
could therefore compare a remote collection with a local publication and
misclassify it as shrunken. Resolved by publishing the canonical backend
identity and making foreign or legacy claims unverifiable at every search
surface.

### watcher-terminal-recovery | high | A refused watcher could remain permanently inadmissible

`FULL_REINDEX_REQUIRED` correctly stopped retries, but no safe transition
reopened the same watcher's circuit after the operator performed the explicit
rebuild. Resolved by allowing a later exact-scope event owned by the same
watcher instance to clear that terminal refusal, while restart-lost scope
continues to fail closed and require an unscoped explicit rebuild.

### lifespan-diagnostic-typing | low | Startup failure context required an explicit mapping cast

Static checking found the startup diagnostic payload had widened to unknown
dictionary values. Resolved with a local typed cast; runtime behavior is
unchanged.

## Recommendations

All findings are resolved in this branch and protected by focused tests. Keep
backend identity in both resumability and publication evidence whenever a new
index domain is added. Keep terminal watcher recovery conditional on retained
exact scope; never infer exact paths after restart.
