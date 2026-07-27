---
tags:
  - '#exec'
  - '#non-destructive-index-publication'
date: '2026-07-25'
modified: '2026-07-27'
step_id: 'S11'
related:
  - "[[2026-07-25-non-destructive-index-publication-plan]]"
---

# Move the pointer to the new generation only after its breadth is recorded, so a reader never resolves a collection that has not reconciled

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/indexer/_run_checkpoint.py`

## Description

Plan evidence: `2026-07-25-non-destructive-index-publication-plan` marks `P03.S11` closed for Move the pointer to the new generation only after its breadth is recorded, so a reader never resolves a collection that has not reconciled.

## Outcome

Evidence gap: `2026-07-25-non-destructive-index-publication-plan` marks `P03.S11` closed, while this record's retained body and complete git log --follow history do not state an implementation result. No outcome beyond that source-attributed plan state is asserted.

## Notes
Template evidence: intro_commit=6dbad746cb765874a5846b0d2ae892ef9c0ff008; template_commit=6dbad746cb765874a5846b0d2ae892ef9c0ff008:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
