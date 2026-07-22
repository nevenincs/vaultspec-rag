---
tags:
  - '#exec'
  - '#machine-discovery-recovery'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S21'
related:
  - "[[2026-07-21-machine-discovery-recovery-plan]]"
---

# Register the reconcile adapter without changing existing lifecycle command contracts

## Scope

- `src/vaultspec_rag/cli/__init__.py`

## Description

- Register the reconcile adapter alongside the existing lifecycle commands and export it
  from the command-line package surface.

## Outcome

The verb is reachable as a server subcommand with no change to any existing lifecycle
command's arguments, output, or exit codes.

## Notes

Registration was verified against the composed application rather than a locally installed
shim: the console script on this machine resolves to a separate installed copy, so a help
probe through it would have reported the command missing even though it registers
correctly.
