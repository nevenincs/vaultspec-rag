---
tags:
  - '#research'
  - '#issue-triage'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:4a3b483ee905d7fd8b6ec5a60b89fe4065ba292c6036ed3fa26d5215bbd8924c'
related: []
---

# `issue-triage` research: `open issue triage and stranded work survey`

The open issue list had drifted from what the tree actually contains: 22 issues open, of which 10 were already fixed on `main`. Two mechanisms produced the drift, and they are unrelated to each other. This document records the survey verbatim so the plan built from it can be checked against the evidence rather than re-derived.

Everything below the lead is the triage as delivered, reproduced unaltered apart from heading depth. Verified at `0bac1117` unless a locator says otherwise.

## Findings

### The stranded work is one thing, not many

Of 16 worktrees, **14 are fully contained in `main`** (`ahead_of_main=0`) - PR 325 swept every agent branch in. The rescue327 "446 dirty files" was a stale stat cache; it re-reads clean. The only uncommitted content anywhere is a 2-line `pyproject.toml` knob (`reportAny`/`reportExplicitAny = "error"`) in `agent-afa55496008c4fbe3` - the instrument the Any-narrowing campaign used to find leaks, not something to land while leaks remain.

**The real stranded work is PR 327.** It merged at `06:22:23Z` into `fix/complexity-and-strict-type-gates` - **33 seconds after** that branch had itself landed on `main` via PR 326 at `06:21:50Z`. So PR 327 reads as "merged" in the UI while none of its 7 commits are in `main`:

```
.github/workflows/fleet-health.yml     +150  (new - alert on work no runner claims)
.github/workflows/ci.yml               +239  (job timeouts, merge gate split from
                                              comprehensive tier, unit tier on
                                              Windows+macOS, GPU/macOS opt-in per dispatch)
bootstrap-branch / claude / publish / release-please   +7
                                       = 394 insertions, 6 workflow files
```

This needs a fresh PR onto `main` - a re-land, not a rescue. It is CI-only, no source conflict with PR 325.

### Why five fixes sat open

PR 325's trailer read `Closes #307, #309, #310, #311, #312, #314`. GitHub binds the keyword to the *first* number only, so 307 auto-closed and five merged fixes stayed open. Each verified against `main` by named commit before closing: 309 `a98bef02`, 310 `fe8bfd89`, 311 `737b6999`, 312 `ba4415c5`, 314 (unified encode driver, `src/vaultspec_rag/embeddings.py:988-1032`).

### Triage - 11 open

**Blocking / severity first**

| Issue   | State                                                                                                                                                                        | Next action                                                                                                                                   |
| ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| **274** | Architecture. The non-destructive index publication ADR is **proposed, unapproved**; 16/17 steps landed, `S14` open honestly (decision implemented, zero production callers) | Needs approval before anything moves. Then S14 wiring: registry lease accessor, collection-granular delete, pointer resolved at decision time |
| **268** | Item 1 **landed** (`code_file_breadth_shortfall` + tri-state integrity + auto-repair in `fabd2c67`); items 2-3 open                                                          | Item 2 (result-diversity signal) is scoped and independently shippable - cheapest real win here. Item 3 is 274 section 1                      |
| **262** | Diagnosed, undesigned. Remedy cannot live where the collision is detected (I/O inside a SQLite transaction)                                                                  | Wants an ADR: which layer owns detection/remedy, retry-in-run vs defer-to-next-generation                                                     |

**Mechanical, unblocked - good parallel work**

| Issue   | Next action                                                                                                                                                                                                                               |
| ------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **313** | Route 3 sites through `measurement`. Note `_format_mb` to `_format_mib` rename; and `nan` renders as `'0s'`/`'less than 1 second'` rather than raising - quieter than the crash and worth fixing in the same pass                         |
| **283** | One-line packaging call: exclude `tests` or state the intent beside the `builtins/` note. CI does not depend on the shipped copy                                                                                                          |
| **289** | 2.0 GB to 319 MB already (a `gc`), but 22 `acceptance-search-index-*` dirs remain under `.git/` and **no producer exists anywhere in the tree**. Likely orphans from a removed harness - verify, then remove                              |
| **290** | Half fixed (interpreter verification + `UV_PYTHON` declared). Remaining: patch-pin `.python-version`, derive CI from it (`"3.13"` still literal at `.github/workflows/ci.yml:52,:320,:349,:385`). **Natural rider on the PR 327 re-land** |

**Deferred by design**

| Issue         | Why it stays open                                                                                                                                                                                                                            |
| ------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **306**       | Decision-needed, not a defect. Median is the decided statistic; changing it amends the ADR and wants production telemetry first                                                                                                              |
| **275**       | 71 to 48 sites. Author's own correction: **0 confirmed mechanical** remain. Blocked on 5 named design calls (cold module state, service token, constructor-arg assertions, `sys.platform`, GPU thresholds)                                   |
| **281 / 308** | PR 325 shipped the machine-wide admission gate and marked both `Refs`, not `Closes` - deliberately. 308's observability direction (couple liveness to the encode path) is untouched and is the part that made the incident take hours to see |

Two suggested but not done, since they are new work rather than triage: file an issue for the PR 327 re-land so it is not lost behind a green "merged" badge, and drop `Closes` trailers one-per-line going forward.

### What was not investigated

The managed venv broke mid-survey (`annotated_doc` absent while resolved in `uv.lock`, site-packages mtime `2026-07-31 09:45:27`), so the last verification batch could not run. Another team owns that. Every finding above that a test would have confirmed was instead confirmed statically, by reading the merged source and naming the commit that introduced it; the two test batches that did run before the break are reported with their counts.

The snapshot-consistency question behind issue 272 - whether a Qdrant snapshot taken during an in-flight upsert is internally consistent - remains unestablished. It is a property of the store, not of this repository, and is narrower than the issue it was raised under.

## Sources

- `src/vaultspec_rag/embeddings.py:988-1032` - unified encode driver, `oom_count` published on both paths
- `src/vaultspec_rag/indexer/_streaming.py:884` - drained total tracked per encode kind
- `src/vaultspec_rag/indexer/_donor_candidates.py:40,313` - collapsed onto the canonical `index_meta_path` resolver
- `src/vaultspec_rag/tests/test_published_value_narrowing.py:381,424-425` - guard walks whole trees
- `src/vaultspec_rag/tests/test_jobs_progress_rate.py:314` - injected-moment cadence assertion
- `src/vaultspec_rag/cli/_jobs_tui.py:1084-1100` - beats owned by the screen that paints them
- `src/vaultspec_rag/cli/_cli_format.py:86-94,126-142` - formatters with no finite guard
- `src/vaultspec_rag/cli/_service_jobs_presentation.py:73,75,77,441,1006` - the three unprotected call sites
- `src/vaultspec_rag/_index_breadth.py:441` - `code_file_breadth_shortfall`
- `src/vaultspec_rag/_index_integrity.py:58-62,327` - tri-state verdict and the shrunken log line
- `src/vaultspec_rag/storage_restore.py:156` - `restore_archive`
- `src/vaultspec_rag/tests/integration/test_storage_restore_integration.py:100-160` - archive/delete/restore round trip
- `src/vaultspec_rag/server/_routes_jobs.py:401,425,636-641,826-832` - degradation verdict judges the evidence it publishes
- `.github/workflows/ci.yml:185-235` - interpreter matrix and the verification step
- `pyproject.toml:147-148` - wheel packages sweep
- commits `a98bef02`, `fe8bfd89`, `737b6999`, `ba4415c5`, `dfdcc509`, `78aa1ba0`, `9482f5c9`, `fabd2c67`, `a52b23b0`, `b7c588a6`
