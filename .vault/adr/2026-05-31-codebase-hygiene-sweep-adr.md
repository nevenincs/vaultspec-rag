---
tags:
  - '#adr'
  - '#codebase-hygiene-sweep'
date: '2026-05-31'
related:
  - '[[2026-05-31-codebase-hygiene-sweep-research]]'
---

# `codebase-hygiene-sweep` adr: `mechanical sweep gating and log mandate` | (**status:** `accepted`)

## Problem Statement

Two follow-up issues (#127 + #130) demand mechanical cleanups
across the entire source tree:

- Process metadata (`Wave N`, `#1NN`, `PR #N`, `(per Task #N)`)
  leaks into source-code comments where it ages and confuses
  fresh readers.
- Some `except` clauses suppress exceptions without any record,
  making post-mortem debugging impossible.

Both are no-behaviour-change sweeps but each touches dozens of
sites; shipping as one PR avoids stacking two
all-files-modified diffs.

## Considerations

- Strict dev-metadata strip (no exceptions) removes test class
  docstrings like `"""gh #128: ..."""`. The replacement
  docstring must describe what the test verifies (the
  invariant), not the issue that triggered it.
- For #130, `contextlib.suppress(SpecificExc)` with a comment
  AND a follow-up `logger.debug` is acceptable. Broad
  `except Exception` is acceptable in load-bearing paths
  (heartbeat, shutdown hooks) BUT must emit `logger.debug(..., exc_info=True)` so the suppressed exception lands in debug
  logs.
- `logger` must exist module-level; add
  `logger = logging.getLogger(__name__)` where missing.

## Constraints

- No behaviour change (no new feature; no API surface change).
- No new dependencies.
- No new tests beyond regression assertions confirming
  log-emission on key paths.
- 591+ unit tests must continue to pass.
- ruff + ty stay green; mdformat clean.

## Implementation

### Phase 1 — dev metadata strip (#127)

Per-file edits in `src/vaultspec_rag/`:

- `cli.py`, `mcp_server.py`, `tests/test_cli.py`,
  `tests/test_mcp_server.py`,
  `tests/integration/test_codebase_integration.py`.

Replace each matched comment/docstring with the underlying
invariant or remove it entirely if redundant.

### Phase 2 — silent except elimination (#130)

Audit every `except` / `contextlib.suppress` in
`src/vaultspec_rag/**/*.py`. Per offender:

1. Confirm `logger` is available; add module-level
   `logger = logging.getLogger(__name__)` if missing.
1. Add `logger.debug("brief context: %s", exc, exc_info=True)`
   (or `logger.warning(...)` if the user-facing surface is
   degraded).
1. Keep the suppression narrow (specific exception type) when
   possible; document the broad-catch reason in a comment.

### Phase 3 — verification

- `uv run --no-sync ruff check src/` clean.
- `uv run --no-sync ruff format src/` clean.
- `uv run --no-sync ty check src/` clean on touched files.
- `uv run --no-sync pytest src/vaultspec_rag/tests -m unit -q`
  shows 591+ passing.
- Negative grep:
  `grep -rn -E '(Wave \d|#1[01][0-9]|ADR memory|Wave 1F|Wave 2|per Task #|PR #1[01][0-9])' src/vaultspec_rag/ --include='*.py'`
  returns nothing.

## Rationale

Mechanical sweeps survive review better when combined: one diff
narrative ("comments cleaned, every except now logs"), one CI
cycle, one merge.

The `logger.debug(..., exc_info=True)` pattern keeps debug
output rich without polluting normal stdout / `--json` envelopes
(debug logs go to file/handler per the project's logging config).

## Consequences

- ~33 comment/docstring edits + N+ logger-debug additions.
- Behaviour byte-identical at normal log level.
- Future PRs can rely on `ruff BLE001` to keep the no-swallow
  invariant enforced.
- Tests do not regress (assertion: 591+ unit pass).
