---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:1f90ebece8f042110900a855932ebba75223f47d7123eaa98b2474a7120b8b4b'
step_id: 'S22'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# add an autouse suite-level isolation guard that points status and qdrant storage dirs at tmp for every test and fails fast if a test observes the machine-global dirs

## Scope

- `src/vaultspec_rag/tests/conftest.py`

## Description

Session-scoped autouse conftest fixture points `VAULTSPEC_RAG_STATUS_DIR`
and `VAULTSPEC_RAG_QDRANT_STORAGE_DIR` at a per-session temp tree for
every test (pre-set env wins; per-test overrides still apply), making the
managed-singleton isolation rule structural instead of per-test
discipline. It immediately fixed a live victim: a qdrant CLI test that
had been reaching the resident production service.

## Outcome

Committed as the structural-isolation commit; the suite-level guard test
asserts the machine-global dirs are never the session's resolved targets.

## Notes

Template evidence: intro_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9; template_commit=cdd61fe69100896ddf1b31f56e327d8fdfd778b9:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
