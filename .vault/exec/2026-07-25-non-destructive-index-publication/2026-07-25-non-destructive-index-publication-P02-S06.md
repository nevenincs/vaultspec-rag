---
tags:
  - '#exec'
  - '#non-destructive-index-publication'
date: '2026-07-25'
modified: '2026-07-27'
body_hash: 'sha256:80766a5330c43b77afb2f4033611a4115b4f73aed2e900975ddb155044b5d1c9'
step_id: 'S06'
related:
  - "[[2026-07-25-non-destructive-index-publication-plan]]"
---

# Resolve every read path's collection name through the pointer rather than deriving it from the root, leaving write paths on the derived name for now

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/_store_search.py`

## Description

Plan evidence: `2026-07-25-non-destructive-index-publication-plan` marks `P02.S06` closed for Resolve every read path's collection name through the pointer rather than deriving it from the root, leaving write paths on the derived name for now.

## Outcome

Evidence gap: `2026-07-25-non-destructive-index-publication-plan` marks `P02.S06` closed, while this record's retained body and complete git log --follow history do not state an implementation result. No outcome beyond that source-attributed plan state is asserted.

## Notes

Template evidence: intro_commit=6dbad746cb765874a5846b0d2ae892ef9c0ff008; template_commit=6dbad746cb765874a5846b0d2ae892ef9c0ff008:.vaultspec/templates/exec-step.md requires Description, Outcome, and Notes. This repair preserves the retained record text and adds no new implementation claim.
