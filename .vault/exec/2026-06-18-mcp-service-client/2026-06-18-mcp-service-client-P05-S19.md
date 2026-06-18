---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S19'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Update the server tests that bind the removed HTTP mount and in-process model-load expectations

## Scope

- `src/vaultspec_rag/tests/test_server.py`

## Description

- Audit the server test module and the wider test tree for assertions that bind the removed surface: the daemon MCP mount path, the redirect ASGI wrapper, the streamable-HTTP app mount, the dropped stateless mount, the in-process stdio model load, the changed service-down error string, and the deleted daemon-call symbols.
- Confirm the earlier phases already rewrote each affected server test to the new reality: the guards assert the redirect wrapper, the mount path, and the streamable-HTTP app are absent from the entry point; the stdio test asserts no model load; the resource test matches the new "is not running" service-down error; and no test references the deleted daemon-call seam.
- Scan the whole test tree for the deleted daemon-call symbols and find none remaining.

## Outcome

This step is a verified no-op for source changes. The server test module passes in full, and the cross-tree scan for the deleted daemon-call symbols returns empty, so no stale assertion survives to fix. The one lingering mention of the streamable-HTTP app in the packaging-metadata test is a correct, current statement — the daemon still serves REST over that app; it simply no longer mounts the MCP — and the server-test references to the removed wrapper and mount are the regression guards themselves, asserting their absence.

## Notes

No edits were required, so no weakening of any assertion was possible. The verification rests on a clean server-test run and an empty deleted-symbol scan rather than on a diff.
