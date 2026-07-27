---
tags:
  - '#research'
  - '#module-split'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-06-01-module-split-research]]"
  - "[[2026-07-25-index-resume-drift-race-research]]"
---

# `module-split` research: `production length gate`

The question is whether the module-breakup ratchet measures production
complexity and which package seam can lower the next enforceable ceiling. The
current gate measures the entire package, so a test module makes its 3,400-line
ceiling fail while every production module is below 3,000 lines. The evidence
supports a production-only gate at 3,000 as the immediate, truthful threshold;
the separate decision is whether package roots remain compatibility facades or
all callers move to concrete submodules.

## Findings

### The gate currently measures the wrong population

`tools/module_length.py:57` recursively includes every Python file below
`src/vaultspec_rag`, including `tests/`; it uses a 3,400-line ceiling at
`tools/module_length.py:45`. On 2026-07-27 it reported 470 files and failed
solely because `src/vaultspec_rag/tests/test_process_probe_canonical.py` is
4,178 lines. The gate is invoked by `justfile:132` and is therefore distinct
from the Ruff Pylint-style function complexity settings in
`pyproject.toml:231`. `tools/health_report.py:183` repeats the same
whole-tree ranking and must agree with whichever scope the gate adopts.

### A 3,000-line production ceiling is green today

A direct production-only census, excluding paths whose component is `tests`,
finds 196 current modules: zero above 3,000, one above 2,500, six above 2,000,
ten above 1,500, 21 above 1,200, 28 above 1,000, and 58 above 500 lines. The
longest is `src/vaultspec_rag/job_manager.py` at 2,955 lines; it is followed by
`indexer/_codebase_indexer.py` at 2,477 and `server/_routes.py` at 2,340. The
203-module census in the requested change does not reproduce on this checkout,
so checked-in comments must use the observed 196-module result rather than a
stale count. A 3,000 ceiling is a valid immediate ratchet under
`2026-07-25-index-resume-drift-race-adr`; the 500-line target remains a
backlog indicator, not an enforceable claim that the tree already meets.

### The existing package-facade decision is incompatible with the canonical rule

The accepted `2026-06-01-module-split-adr` and its completed plan adopted
package-root `__init__.py` re-exports specifically so callers and tests would
not migrate. That direction conflicts with `.codex/rules/canonical-code.md`,
which forbids a forwarding shim, a delegating wrapper, and a re-export at the
former module seam. The current guard test exempts package `__init__.py` at
`src/vaultspec_rag/tests/test_no_reexports.py:14`, so it cannot prove the
stricter outcome. This is a refinement of the existing module-split decision,
not an unrelated second decision.

### The first candidate must migrate direct consumers, not hide them behind a facade

Converting `job_manager.py` to a package would preserve package import
resolution, but its public names must move to their concrete owner modules.
Current production consumers include `jobs.py:25`, `job_dispatch.py:11`,
`watcher.py:33`, and `server/_lifespan.py:46`; tests directly import
`JobManager` at `tests/test_jobs_unit.py:101`. A forwarding `job_manager.py`
cannot coexist with a same-named package and would violate the canonical rule
in any event. The alternative is to keep a package-root facade like the
completed June split; it avoids migration work but leaves duplicate import
paths and is rejected by the rule. Import-time state owners (for example the
server package documented at `src/vaultspec_rag/server/__init__.py:18`) need a
small explicit owner rather than a facade; ordinary collaborators can be
imported directly.

### Boundaries not investigated

This research establishes gate scope and the first candidate's import surface.
It does not prescribe every extraction boundary inside the six production
modules over 2,000 lines; each requires a focused responsibility audit before
a plan assigns code-moving steps.

## Sources

- `tools/module_length.py:45`
- `tools/module_length.py:57`
- `tools/health_report.py:183`
- `justfile:132`
- `pyproject.toml:231`
- `.codex/rules/canonical-code.md`
- `src/vaultspec_rag/tests/test_no_reexports.py:14`
- `src/vaultspec_rag/job_manager.py:233`
- `src/vaultspec_rag/jobs.py:25`
- `src/vaultspec_rag/job_dispatch.py:11`
- `src/vaultspec_rag/watcher.py:33`
- `src/vaultspec_rag/server/_lifespan.py:46`
- `src/vaultspec_rag/tests/test_jobs_unit.py:101`
- `src/vaultspec_rag/server/__init__.py:18`
- `2026-06-01-module-split-adr`
- `2026-07-25-index-resume-drift-race-adr`
