---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S62'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Replace patched auto-delegation isolation

## Scope

- `src/vaultspec_rag/tests/test_cli.py TestAutoDelegation`
- `real temporary STATUS_DIR and QDRANT_STORAGE_DIR state`
- `real OS machine lock and discovery pointer`
- `search and index shared resolution`
- `repeated live-55108 coexistence`
- `affected CLI`
- `discovery`
- `service-first`
- `static`
- `and formal review gates`

## Description

- Remove patched discovery, liveness, search, and index transport behavior from
  `TestAutoDelegation`.
- Run each case in a fresh interpreter with isolated status and machine-global storage.
- Use a real OS machine lock, real machine discovery pointer, and real status file.
- Hold two real loopback sockets bound but non-listening through the probe, then drive
  the real search command to the selected reserved port and inspect its JSON envelope.
- Verify the shared search and index resolver under both authority and fallback paths.
- Repeat the focused tests while the unrelated live service on port 55108 remains active.

## Outcome

- Preserved the two-test count while replacing both prohibited monkeypatch-based cases.
- Proved that a valid machine-global pointer outranks a conflicting status-file port.
- Proved that the status-file port is used only when no machine service resolves.
- Proved that search and index import the same authoritative resolver result.
- Proved real search delegation reaches the selected reserved, non-listening loopback
  port and returns `port_unreachable` without loading heavy model libraries.
- Passed 2 focused tests, 10 repeated focused executions, 19 adjacent discovery and
  service-first tests, and all 266 tests in `test_cli.py`.
- Passed Ruff, affected formatting, Ty, BasedPyright, complexity, and diff checks.
- Passed fresh independent review with no actionable findings after both selected
  endpoints were held reserved through the transport assertion.

## Notes

The subprocess relocates both `VAULTSPEC_RAG_STATUS_DIR` and
`VAULTSPEC_RAG_QDRANT_STORAGE_DIR`, so the host's live service on port 55108 remains
authoritative only outside the test boundary and is never read, called, or modified by
the probe. It keeps both selected port sockets bound until `finally`, preventing another
local process from claiming either discovery endpoint before the real transport check,
then closes both sockets. No index request is sent.

No production precedence, dependency, or lock file changed. This correction receives no
release-campaign credit and does not authorize a pull request, merge, approval,
publication, or release.
