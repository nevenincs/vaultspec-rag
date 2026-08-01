---
tags:
  - '#exec'
  - '#mcp-project-root-contract'
date: '2026-07-25'
modified: '2026-07-25'
body_hash: 'sha256:5ee519df5bfb41574acc643f25b94d82f4cc37579e0a49b927517d1c873dab9c'
step_id: 'S03'
related:
  - "[[2026-07-25-mcp-project-root-contract-plan]]"
---

# Assert against a recording daemon that an omitting caller sends a concrete root and an explicit root still wins

## Scope

- `src/vaultspec_rag/tests/test_mcp_conformance_surface.py`

## Description

- Stand up a real loopback HTTP server that answers with a valid search envelope
  and records each decoded request body, published through a relocated status
  directory so the tools resolve it instead of the operator's service.
- Assert that an omitted root arrives as the resolved working directory on both
  the search route and the reindex route.
- Assert that an explicitly supplied root arrives unchanged and is not the
  working directory.

## Outcome

Thirteen tests pass in the file. The assertions are on the exact payload that
reached the wire, so they would fail on the empty string the route rejects -
which is the actual defect, and the thing an intercepted call could not have
shown.

The explicit-root case is the one that keeps the fix honest. A default that
silently overrode a caller's argument would pass every test written only around
the omitted case, and would be a worse bug than the one being fixed.

## Notes

The recording server is a real HTTP peer, not a stub of the client: the code
under test performs a genuine request and parses a genuine response. Both
machine-singleton directories are relocated to a temp path by the shared
fixture, so the test neither contends for the real machine lock nor writes into
the operator's managed directory.
