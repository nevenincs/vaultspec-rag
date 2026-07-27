---
tags:
  - '#exec'
  - '#service-release-compatibility'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S18'
related:
  - "[[2026-07-25-service-release-compatibility-plan]]"
---
# Stamp this install release into the discovered dead-service fixture

## Scope

- `src/vaultspec_rag/tests/test_search_service_first.py`

## Description

Stamp the fixture with the locally installed package release so its discovery path reaches the unreachability assertion rather than the release-compatibility refusal.

## Outcome

The fixture writes `SERVICE_VERSION_FIELD: local_package_version()`. The discovered-but-dead-service path now exercises the intended error contract.

## Verification

`uv run pytest -p no:cacheprovider src/vaultspec_rag/tests/test_search_service_first.py::TestServiceFirstRouting::test_discovered_dead_service_errors_without_fallback -q` completed with `1 passed`.

## Notes

The test disables cache-provider writes and did not alter shared runtime state.
