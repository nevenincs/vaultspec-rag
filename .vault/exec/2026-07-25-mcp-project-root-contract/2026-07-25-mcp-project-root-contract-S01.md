---
tags:
  - '#exec'
  - '#mcp-project-root-contract'
date: '2026-07-25'
modified: '2026-07-25'
step_id: 'S01'
related:
  - "[[2026-07-25-mcp-project-root-contract-plan]]"
---

# Add a single dispatch-root seam on the MCP adapter and forward every delegation site through it

## Scope

- `src/vaultspec_rag/mcp/_tools.py`

## Description

- Add one helper returning the concrete root to send: the caller's value when
  present and non-blank, the resolved process working directory otherwise.
- Replace the empty-string fallback at every delegation site - the four search
  tools, the code-file retrieval, the reindex family, the clean family, and the
  service-state query.
- Leave the daemon route untouched.

## Outcome

The advertised optionality is reachable. An omitting caller now sends a concrete
root, so the schema's claim and the route's requirement agree without the route
relaxing anything.

Placing the fill at one seam rather than in each tool body is what makes the
claim true everywhere at once. Eight call sites each applying their own
fallback is how the surface drifted into advertising something it could not
honour in the first place.

## Notes

The seam adds only a standard-library path import, so the adapter stays a thin
service client with no torch and no locks.
