---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-22'
step_id: 'S21'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Amend the hook child cwd from a scratch dir to the project root so project-launcher commands (uv run) resolve, per the aeat validation failure

## Scope

- `src/vaultspec_rag/indexer/_preprocess_runner.py`

## Description

- Change the hook child cwd from a fresh scratch dir to the project root; drop the scratch mkdtemp/rmtree.
- Rewrite the cwd test to assert the project-root cwd; update the runner docstrings, ADR D8, and the docs' bounds paragraph.

## Outcome

The aeat validation run had all 531 hook invocations failing (`uv run` cannot resolve its project from a scratch cwd); with the project-root cwd, `preprocess run-one` on a previously-failing corpus PDF extracts 82 sections. Matches the pre-sandbox contract hooks were authored against.

## Notes

Found only by the live corpus benchmark - the unit suite could not catch it because the failure is a property of project-launcher commands, not of the runner's own logic.
