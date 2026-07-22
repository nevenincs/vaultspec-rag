---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S29'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Register the singular server job command group while preserving the server jobs collection command using vaultspec-low-executor

## Scope

- `src/vaultspec_rag/cli/_app.py`

## Description

- Create the singular `server job` Typer application.
- Nest it under the existing server group without changing the plural `jobs`
  command.
- Add zero-argument help behavior consistent with the other server groups.

## Outcome

`server job` is registered and ready for exact-resource control commands while
`server jobs` remains the collection view. Ruff, Ruff format, and BasedPyright
pass, and both help surfaces resolve successfully. Independent review passed
with no critical, high, or medium findings.

## Notes

An attempted package-module invocation was invalid because the CLI package has
no local `__main__`; the registered Typer surface was verified directly through
the production application object. No destructive Git operation occurred.
