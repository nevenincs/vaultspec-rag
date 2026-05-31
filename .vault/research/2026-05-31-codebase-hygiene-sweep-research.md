---
tags:
  - '#research'
  - '#codebase-hygiene-sweep'
date: '2026-05-31'
related: []
---

# `codebase-hygiene-sweep` research: `dev metadata strip + silent except elimination`

## Trigger

Two follow-up issues filed during the end-of-Wave-2 honest audit:

- **gh #127**: dev metadata pollution. Wave 1/Wave 2 work
  embedded process references (`Wave 2 #112`, `(issue #110)`,
  `(#115)`, `Wave 1F`, `(see ADR memory)`, `(per Task #N)`) into
  source-code comments. These age fast and mean nothing to a
  fresh reader of the code.
- **gh #130**: silent exception swallows. User feedback mid-Wave 3
  mandated every `except` clause either re-raise, return a
  structured error, or emit `logger.debug` / `logger.warning` /
  `logger.exception` with enough context. `contextlib.suppress`
  is only acceptable when the suppression target is genuinely
  narrow AND has a comment AND has a `logger.debug` line.

Both are mechanical sweeps with no behaviour change. Shipping
together because they touch the same files and share verification
(unit tests pass, ruff clean, no functional regression).

## Method

Grep across `src/vaultspec_rag/**/*.py` with the regexes from the
two issues. Counts current as of branched-from-main commit
`ece6d67` (post-#128 merge).

## Findings

### Dev metadata occurrences (gh #127)

Pattern: `(Wave \d|#1[01][0-9]|ADR memory|Wave 1F|Wave 2|per Task #|PR #1[01][0-9])`. Result:

- `cli.py`: 14 occurrences.
- `mcp_server.py`: 1 occurrence.
- `tests/test_cli.py`: 12 occurrences.
- `tests/integration/test_codebase_integration.py`: 3 occurrences.
- `tests/test_mcp_server.py`: 3 occurrences.

Total: 33 occurrences across 5 files. Most test occurrences are
class docstrings of the form `"""gh #128: prove tqdm progress bars don't leak."""`. Strip uniformly: rephrase to the
underlying invariant rather than referencing the gh number.

### Silent except locations (gh #130)

Files with `except`/`contextlib.suppress` patterns ending in
`pass`/`return`/`continue`:

- `cli.py` — broad-except in `_try_mcp_*` HTTP wrappers, plus
  `_health_probe` and `_terminate_pid`.
- `mcp_server.py` — heartbeat-loop broad-excepts (load-bearing;
  must survive all exceptions), `_record_shutdown`,
  `_unlink_status_file_silently`.
- `indexer.py`, `search.py`, `store.py`, `embeddings.py`,
  `watcher.py`, `torch_config.py`, `memory_probe.py`,
  `logging_config.py`, `config.py` — full audit pass needed.
  Some may be legitimate (e.g. optional-import fallbacks).

### Cross-cutting concerns

- The `logger` name must already exist in each module before we
  add `.debug(...)` lines. Add to any that don't.
- `exc_info=True` recommended so the suppressed exception is
  preserved in debug output without polluting stdout/stderr.

## Recommendation

One PR — feature `#codebase-hygiene-sweep` — covering both
issues. The 33-mention dev-metadata strip is fully mechanical;
the silent-except audit requires per-clause judgment but produces
consistent `logger.debug` additions with no behaviour change.

Verification:

- `grep -rn -E '(Wave \d|#1[01][0-9]|ADR memory|Wave 1F|Wave 2|per Task #|PR #1[01][0-9])' src/vaultspec_rag/ --include='*.py'`
  returns zero matches.
- 591+ unit tests still pass.
- No new behaviour (purely log + comment changes).
