---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
step_id: 'S04'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# Cover the root-scoped lookup end to end: indexed root returns prefix plus populated namespaces, unindexed root returns prefix plus empty list, and the CLI and MCP adapters pass the parameter through

## Scope

- `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`

## Description

- Add root-scoped lookup coverage against the live service: an unindexed
  root returns `queried_root.prefix` equal to `root_collection_prefix` with
  an empty namespace list; an empty `?root=` is a 400; the admin client
  forwards `root` and receives the service-computed prefix.
- Add the indexed-root test: build a synthetic vault, reindex it through the
  daemon's `/reindex` route, wait for the job, then assert the lookup
  returns the prefix plus populated matching namespaces.

## Outcome

Seven of eight tests pass live (all four pre-existing plus the three new
lookup tests). The indexed-root test currently fails on this box for a
cause outside this feature: the daemon-driven vault reindex itself errors
inside the spawned qdrant ("failed to open mutable map index on gridstore:
os error 3" during prepare-collection), and the untouched
`test_multi_project_search_isolation` on main fails in the same
daemon-reindex path (reindex job errors, follow-up search 500s). The test
is committed as the honest coverage; it will pass once the pre-existing
daemon reindex regression is fixed.

## Notes

Pre-existing failure surfaced: daemon-spawned qdrant under an isolated
storage dir cannot create collections (gridstore path error), breaking
every reindex-through-daemon integration test on this machine - including
main's own lifecycle isolation test, independent of this feature. Needs a
separate investigation/issue; the integration suite marker set
(`subprocess_gpu`) does not run in CI, so CI is unaffected.
