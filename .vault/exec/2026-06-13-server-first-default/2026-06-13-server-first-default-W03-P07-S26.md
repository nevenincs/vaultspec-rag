---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S26'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# add a get_readiness facade function that aggregates the bounded per-dependency readiness snapshot in the service domain

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Add a new service-domain readiness module `_readiness.py` housing the bounded, read-only reporter, mirroring how the provisioning front door keeps its logic out of the public facade.
- Define `compute_readiness` to aggregate one node per external dependency (torch, models, qdrant) in a stable order, reading the effective backend mode from config.
- Define `ReadinessReport` and `DependencyReadiness` dataclasses, each with a JSON-serialisable `to_dict`, and a bounded `ReadinessStatus` vocabulary (`ready` / `not_ready` / `unknown`).
- Expose the aggregate through a minimal `get_readiness` facade on the public `api.py`, returning the serialisable `to_dict` view and acquiring no project lease (readiness is process-wide and project-independent).

## Outcome

- `compute_readiness` returns a bounded three-dimension snapshot; `api.get_readiness` round-trips through `json.dumps` and reports `ready=True` on the dev host. The reporter loads no model and mutates nothing.

## Notes

- The plan named `src/vaultspec_rag/api.py` as the Step scope, but the readiness computation lives in a dedicated service-domain module `src/vaultspec_rag/_readiness.py` (the idiomatic location, mirroring `commands/_provision.py`); `api.py` carries only the thin `get_readiness` facade plus its `__all__` entry. The CLI verb and MCP adapter (W03.P08) consume this shared behaviour.
