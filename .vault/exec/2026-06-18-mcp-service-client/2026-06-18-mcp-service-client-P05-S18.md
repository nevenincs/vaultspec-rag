---
tags:
  - '#exec'
  - '#mcp-service-client'
date: '2026-06-18'
modified: '2026-06-18'
step_id: 'S18'
related:
  - "[[2026-06-18-mcp-service-client-plan]]"
---

# Add the no-local-fallback test asserting each tool raises a clear service-not-running error against an isolated empty status dir

## Scope

- `src/vaultspec_rag/tests/test_mcp_no_local_fallback.py`

## Description

- Add a new test module that enumerates every MCP tool, admin tool, and the vault-document resource — the two searches, index status, code-file fetch, both reindexers, the admin and observability tools, benchmark, quality, and the document resource — as parametrized `(id, thunk)` pairs.
- Add an `isolated_status_dir` fixture copied from the service-lifecycle helper pattern: it points `VAULTSPEC_RAG_STATUS_DIR` at a fresh empty temp directory and calls `reset_config()` on enter and exit, with no `service.json` written, so service discovery must conclude the daemon is down. No monkeypatch is used; the environment variable is the project's designated isolation mechanism.
- Assert each tool, driven through `asyncio.run`, raises a `RuntimeError` whose message contains "is not running", exercising the real status-file read and the real client path up to the single no-local-fallback guard.
- Add a fresh-interpreter subprocess variant that drives the search tool to its service-down error against an empty status dir, then asserts `sys.modules` stays free of the heavy ML libraries — proving no local engine was built — since in-process `sys.modules` is session-polluted and the no-load assertion is only meaningful in a clean interpreter.

## Outcome

All eighteen per-tool cases plus the subprocess no-load variant pass. The forbidden-construct scan over the new file reports no `monkeypatch`, `MagicMock`, `@patch`, `unittest.mock`, `pytest.skip`, or `mock.` usage. The tests are non-tautological: they fail if any tool gains a local fallback or stops resolving the missing-service guard.

## Notes

The shipped service-down message is "vaultspec-rag service is not running", which the "is not running" match anchors on without binding to the exact wording. The thunk annotation uses `Coroutine` rather than `Awaitable` so the static type checker accepts it as the argument to `asyncio.run`.
