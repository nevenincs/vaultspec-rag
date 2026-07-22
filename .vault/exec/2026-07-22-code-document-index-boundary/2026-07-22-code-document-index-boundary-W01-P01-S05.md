---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S05'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Compile ignore precedence, explicit ownership, source-profile admission, and parser selection into one deterministic classifier

## Scope

- `src/vaultspec_rag/indexer/_content_policy.py`
- `src/vaultspec_rag/indexer/_ignore_specs.py`
- `src/vaultspec_rag/indexer/_chunking.py`

## Description

- Separate conventional source admission from parser capability.
- Apply project ignore specifications before all ownership decisions.
- Compile root routes and transform targets into a one-owner decision.
- Admit conventional source only after explicit routing has been resolved.
- Select a structured or generic text parser only after admission.
- Validate lint, typing, and real classification behavior.

## Outcome

One classifier now produces deterministic ownership, admission reason, and parser capability.
Ambiguous formats do not enter the code domain through parser support alone, while
caller-authored routes can assign unconventional source or raw documents explicitly.

## Notes

No incidents or data loss. Concurrent shared-worktree commits temporarily displaced an
unstaged edit; the final implementation was reapplied against the current `main` state and
revalidated before commit.
