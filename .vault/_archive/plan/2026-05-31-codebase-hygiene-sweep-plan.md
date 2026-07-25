---
tags:
  - '#plan'
  - '#codebase-hygiene-sweep'
date: '2026-05-31'
modified: '2026-06-30'
related:
  - '[[2026-05-31-codebase-hygiene-sweep-adr]]'
  - '[[2026-05-31-codebase-hygiene-sweep-research]]'
---

# `codebase-hygiene-sweep` plan: `mechanical strip + no-swallow sweep`

Implements gh #127 (dev metadata strip) + gh #130 (silent except
elimination) as one PR. Mechanical, no behaviour change.

## Tasks

### Phase 1 — dev metadata strip

- For each occurrence in `cli.py`, `mcp_server.py`,
  `tests/test_cli.py`, `tests/test_mcp_server.py`,
  `tests/integration/test_codebase_integration.py`:
  - Rephrase the comment/docstring to describe the invariant
    or remove it if redundant.
- Confirm the verification grep returns zero matches.

### Phase 2 — silent except sweep

- For each `.py` file under `src/vaultspec_rag/`:
  - Audit every `except` / `contextlib.suppress`.
  - Confirm a `logger` is available; add module-level
    `logger = logging.getLogger(__name__)` where missing.
  - Add `logger.debug("brief context: %s", exc, exc_info=True)`
    (or `logger.warning(...)` if user-facing surface degraded).
  - Narrow exception types where the broad-catch was lazy
    rather than intentional.

### Phase 3 — verification

- `uv run --no-sync ruff check src/`.
- `uv run --no-sync ruff format src/`.
- `uv run --no-sync ty check src/vaultspec_rag/`.
- `uv run --no-sync pytest src/vaultspec_rag/tests -m unit -q`.
- Verification grep returns zero matches.

### Phase 4 — commit + push + PR + merge

- One commit covering all sweeps.
- PR title: `chore(hygiene): strip dev metadata + log every except clause (#127, #130)`.
- Squash-merge once CI green. Then trigger release-please on
  main.

## Verification

- Negative grep zero.
- 591+ unit tests pass.
- ruff + ty clean.
- No behaviour change.

## Out of scope

- New ruff rules enforcing the no-swallow invariant — separate
  follow-up.
- Replacing `print` calls (none expected in src/).
- Test coverage gain (this PR adds no functional code).
