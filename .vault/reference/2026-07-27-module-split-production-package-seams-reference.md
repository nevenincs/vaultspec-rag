---
tags:
  - '#reference'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-06-01-module-split-adr]]"
  - "[[2026-07-25-index-resume-drift-race-adr]]"
---

# `module-split` reference: `production package seams`

This reference captures the present source topology that an approved
module-breakup plan must preserve or migrate directly. It was grounded by the
current size gate, the current production import sites, and the existing
package-root designs.

## Summary

`tools/module_length.py:42` is the authoritative physical-LOC gate. It derives
its input from `PACKAGE_DIR` and `Path.rglob("*.py")` in
`collect_module_lengths` at `tools/module_length.py:57`; filtering should occur
there so the main gate and `--census` share one scope. Its current commentary,
ceiling, and rungs at `tools/module_length.py:3-53` describe 434 whole-tree
modules and a 3,400 ceiling, neither of which matches the current checkout.
`tools/health_report.py:183-199` independently enumerates the same package and
must use the same production predicate to avoid reporting a different gate
population.

`job_manager.py` is the longest production candidate (2,955 lines). Its
stable public surface is narrow (`MAX_RECORDS`, `JobAttemptContext`,
`JobExecutionResult`, `JobManager`, and `JobShutdownResult`) at
`src/vaultspec_rag/job_manager.py:53-59`, while the implementation begins with
result/context dataclasses at lines 84-233 and the `JobManager` class at line
233\. That creates a likely package shape of concrete model/context and manager
ownership submodules, provided a focused audit proves the class's internal
responsibility boundaries. Direct consumers currently import from the flat
module: `src/vaultspec_rag/jobs.py:25`, `job_dispatch.py:11`, `watcher.py:33`,
and `server/_lifespan.py:46`; they must be migrated in the same change if the
package root ceases to re-export names.

The existing `cli`, `indexer`, and `server` directories show the prior
facade-style pattern. In contrast, `server/__init__.py:18` describes
load-bearing package state, so its root must retain only necessary state
ownership and cannot become a generic forwarding surface. No package root may
retain an import solely to expose a symbol after callers have migrated; that
would duplicate the concrete import path and violate
`.codex/rules/canonical-code.md`.

The audit guard at `src/vaultspec_rag/tests/test_no_reexports.py:14` currently
permits `__init__.py` re-exports. An approved plan must change that policy only
alongside migration of the affected direct imports, using real behavior tests
for the moved owners rather than a facade-presence test.

There is a non-ancestor reference implementation on branch `chore/tooling-gates`.
Commit `c95a780f` extracts code-index consumer lifecycle, incremental
publication, and support-budget ownership from `_codebase_indexer.py` into
`_consumer_pipeline.py`, `_incremental_commit.py`, and `_support_budget.py`;
commit `afc81558` extracts HTTP token, search, reindex, and registry/watcher
concerns from `server/_routes.py` into `_auth.py`, `_routes_search.py`,
`_routes_reindex.py`, and `_routes_registry.py`, while retaining `ROUTES` as
the single table owner. These commits repoint import sites and tests directly,
with no forwarding module left behind. Commit `85e30273` contains the requested
production-only Pylint gate update but depends on a configuration surface not
present at current `HEAD`; it is a reference for intended scope, not a patch to
apply blindly.
