---
tags:
  - '#exec'
  - '#vault-pipeline-search'
date: '2026-06-24'
modified: '2026-06-24'
step_id: 'S27'
related:
  - "[[2026-06-24-vault-pipeline-search-plan]]"
---




# Relocate run_quality_probe and run_benchmark capability under the test tree

## Scope

- `src/vaultspec_rag/api.py`

## Description

- Confirmed `run_quality_probe` and `run_benchmark` in `api.py` are no longer reachable from
  any operator surface (the CLI verbs and MCP tools that called them were removed in S26).
- Retained the functions and the service `/quality` and `/benchmark` routes as the
  test-reachable capability, so the marked test suite keeps a path to the needle-precision and
  latency harnesses.

## Outcome

The dev-tooling capability is retained only behind the service/test layer; no operator entry
point exposes it. `ruff` and `ty` pass.

## Notes

A full physical relocation of `run_quality_probe`/`run_benchmark` into the test tree was NOT
done, because the service `/quality` and `/benchmark` routes still call them and moving them
would force production code to import from `tests/`. The cleaner end state - also removing
those two service routes and their transport helpers - is a deeper, separable change left as a
follow-up; the operator-surface removal D9 targets (CLI + MCP) is complete. This deviation
from the literal "move under the test tree" wording is recorded here per the no-silent-scope
rule.
