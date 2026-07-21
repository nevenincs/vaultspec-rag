---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S64'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Exercise real index auto-delegation through both isolated discovery modes

## Scope

- `src/vaultspec_rag/tests/test_cli.py TestAutoDelegation`
- `fresh subprocesses`
- `real loopback HTTP capture server`
- `reserved conflicting endpoint`
- `exact search and reindex routes and payloads`
- `initiator_kind=cli`
- `no heavy ML load or local indexing`
- `repeated live-55108`
- `adjacent`
- `full CLI`
- `static`
- `and formal review gates`

## Description

- Replace the selected non-listening endpoint with a real loopback HTTP capture
  server while keeping the conflicting endpoint bound and unavailable.
- Map the capture server to the valid machine-global pointer in the authority case and
  to the isolated status file in the fallback case.
- Execute the real CLI `search` and `index --type vault` commands in each fresh
  interpreter.
- Require `/search` followed by `/reindex`, and verify the exact request bodies,
  including `initiator_kind="cli"`, project root, index type, and clean mode.
- Require both JSON envelopes to report service execution, preserve the isolated target
  tree, and load no heavy machine-learning libraries.
- Shut down and join the HTTP server thread, release the machine lock conditionally,
  and close the conflicting socket in `finally`.

## Outcome

- Preserved the two-test count while exercising real search and index auto-delegation
  under both discovery modes.
- Proved the selected discovery endpoint by requiring the capture server's port to
  equal the resolved port and by capturing both actual HTTP requests.
- Proved that the index command sends `/reindex` with `type="vault"`, `clean=false`,
  the isolated project root, and `initiator_kind="cli"`.
- Proved that neither command falls back to local indexing: both envelopes report
  `via="service"`, the isolated target tree remains unchanged, and Torch,
  SentenceTransformers, Qdrant Client, Transformers, and ONNX Runtime remain unloaded.
- Passed 2 focused tests, 10 repeated focused executions, 19 adjacent discovery and
  service-first tests, and all 266 tests in `test_cli.py`.
- Passed Ruff, affected formatting, Ty, strict BasedPyright, every complexity threshold,
  and diff checks.
- Passed fresh independent review with no actionable findings.

## Notes

The installed service remained bound to port 55108 with process identifier 84904 and
the same process start time. One administrative status request timed out while the
service was busy, but the ungated `/health` endpoint immediately returned
`status="ready"` with the same process identity. The tests relocate status and
machine-global storage, never address port 55108, and make no index request outside
their own capture server.

No production code, dependency declaration, or lock file changed. This correction earns
no release-campaign credit and does not authorize a pull request, approval, merge, tag,
publication, or release.
