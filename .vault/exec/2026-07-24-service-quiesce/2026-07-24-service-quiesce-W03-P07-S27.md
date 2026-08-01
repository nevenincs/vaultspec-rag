---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
body_hash: 'sha256:0444e39bd0bc1fb96ec31b0c4ec8726727307be6c1f80ad63c8e343346986f49'
step_id: 'S27'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Render controller state, GPU release evidence and borrower safety in the jobs TUI header and status details

## Scope

- `src/vaultspec_rag/cli/_jobs_tui.py`

## Description

Render the controller-owned state, VRAM release evidence, and borrower-safety
observation from the jobs response. Treat absent, invalid, or incomplete
controller evidence as unavailable rather than inferring safety.

## Outcome

Accepted for S27 after merge commit `5dc05814` adopts the controller-derived
`QUIESCE_ENVELOPE_FIELDS` vocabulary and deletes the duplicated local field
sets. `54284415` and `9b1f0410` provide the rendering behavior, and `0576e4f4`
removes the rejected source-mutating probe. The reported CPU-only proof includes
the checked-in real no-lifespan route host: it pauses a real registry, fetches
jobs through authenticated transport, and renders the canonical block in
Textual. A real rejected jobs request renders `quiesce unavailable` and does
not render borrower safety as safe.

## Notes

The current successful `GET /jobs` route always serializes the complete
controller envelope, so it cannot produce a successful partial quiesce block.
The TUI's exact-field rejection for that hypothetical malformed success is
static, unexercised defense-in-depth. No response seam, test hook, proxy,
handcrafted contract, or production-source mutation is permitted to manufacture
it. Exact-set fail-closed behavior now consumes the controller-owned vocabulary;
no response seam, test hook, proxy, handcrafted contract, production-source
mutation, or source-inspection mutation test is used. The reported focused run
started no daemon lifespan, GPU, or Qdrant process.
