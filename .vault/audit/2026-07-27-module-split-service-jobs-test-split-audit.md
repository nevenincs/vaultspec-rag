---
tags:
  - '#audit'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:df412efd756765d0f5406ddc89d6b65d4b1985db74dad34d462e8e8fa8f5d58b'
related:
  - "[[2026-06-01-module-split-plan]]"
---

# `module-split` audit: `service jobs test split`

## Scope

Reviewed P09.S10's replacement of the tracked service-jobs integration suite
with directly collected CLI, MCP, route, resilience, progress, and concrete
helper modules. Compared test identities, inspected fixture and helper
ownership, checked for facades and duplicate collection, and verified the
route, MCP, and resilience domain inventory.

## Findings

No findings. All 59 pre-split test identities are preserved exactly once. The
live split adds `test_jobs_running_output_flags_jobs_without_recent_progress`
without replacing or duplicating an existing scenario. Route authorization,
collection, control, and mutation coverage; MCP result, deadline, ordering,
limit, and source filtering coverage; and resilience HTTP/health/CLI parity
coverage remain directly collected in concrete owners.

## Recommendations

No remediation required.

Verification: all eleven replacement modules collect 74 tests with no
duplicate node IDs. `_service_jobs_support` and
`_service_jobs_route_helpers` own their named fixtures; consuming modules use
explicit direct imports, including fixture aliases solely to expose those
fixtures to pytest. There are no `pytest_plugins` declarations, wildcard
imports, exported helper surfaces, test facades, or retained
`test_service_jobs.py` imports. The CPU-safe focused suite passes 68 tests;
the six MCP tests marked `subprocess_gpu` were collected but not executed to
preserve GPU discipline. Collection and execution report only third-party
Typer and Starlette deprecation warnings.
