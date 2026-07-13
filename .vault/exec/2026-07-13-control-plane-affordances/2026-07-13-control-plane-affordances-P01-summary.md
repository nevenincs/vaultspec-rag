---
tags:
  - '#exec'
  - '#control-plane-affordances'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - "[[2026-07-13-control-plane-affordances-plan]]"
---

# `control-plane-affordances` `P01` summary

All four Steps complete (S01 route, S02 transport and MCP client, S03 CLI,
S04 integration tests), one commit per Step plus a review-fix commit.

- Modified: `src/vaultspec_rag/server/_routes.py`
- Modified: `src/vaultspec_rag/serviceclient/_transport.py`
- Modified: `src/vaultspec_rag/mcp/_admin_client.py`
- Modified: `src/vaultspec_rag/cli/_service_storage.py`
- Modified: `src/vaultspec_rag/tests/integration/test_storage_survey_service.py`

## Description

`GET /storage/survey` now accepts `?root=`: the route resolves the queried
root through the one `root_collection_prefix` derivation, narrows the
namespace list to the matching prefix, and returns the authoritative prefix
as a top-level `queried_root` object - present even for a root the manifest
has never seen, which is what lets the dashboard delete its hand-rolled
blake2b recomputation. The serviceclient transport, the MCP `survey_storage`
client, and the CLI `server storage survey --root` all pass the parameter
through to the one route; the CLI-direct fallback resolves through the same
derivation in-process. Review fixes: relative `--root` resolves against the
operator's cwd before dispatch, the CLI-direct `--json` envelope gained
`returned`, and the help line names the lookup.

Verification: seven of eight integration tests pass live (route envelope,
empty-root 400, unindexed-root prefix, adapter pass-through); the
indexed-root test is blocked by a pre-existing daemon-reindex regression
(qdrant gridstore path error) that equally fails main's untouched lifecycle
isolation test. Ruff, ruff format, and basedpyright clean; post-review
audit passed with no critical or high findings.
