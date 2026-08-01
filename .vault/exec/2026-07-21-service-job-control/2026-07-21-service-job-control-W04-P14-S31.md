---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:cb8232961619fa453bf337db622edf4d6565b5cebb6cece3221b47bc0eb6a851'
step_id: 'S31'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify human and JSON CLI controls, ambiguous prefixes, idempotent requests, stable errors, retry, deletion, and force rejection against a real server using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_job_control.py`

## Description

- Seed canonical paused resources with deterministic exact identifiers.
- Exercise human show, pause, resume, stop, retry, and delete commands against
  a real loopback service.
- Verify unique-prefix resolution and stable ambiguous-prefix rejection.
- Exercise JSON exact-ID behavior, single-envelope success and failure,
  force rejection, replay idempotency, deletion, and missing history.

## Outcome

Two focused real-server scenarios pass. Human commands resolve only one
unique prefix before exact requests, JSON commands reject prefixes through
exact detail, already-satisfied controls exit successfully, and stable error
codes survive the CLI adapter. Ruff, Ruff format, and BasedPyright pass.
Independent review passed with no critical, high, or medium findings.

## Notes

The tests use production manager resources, routes, transport, Typer commands,
and Uvicorn loopback sockets. They contain no fake, mock, stub, patch,
monkeypatch, skip, or expected-failure shortcut.
