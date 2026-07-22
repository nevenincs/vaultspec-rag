---
tags:
  - '#audit'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` audit: `W03 P05 Preprocess Fidelity Code Review`

## Scope

Audit `W03.P05` against the accepted preprocess invocation, source-binding, cache,
metadata, lifecycle, and CLI contracts in the governing ADR and plan. The review covered
`_preprocess_schema.py`, `_preprocess_config.py`, `_resolved_policy.py`,
`_preprocess_runner.py`, `_preprocess_cache.py`, `_preprocess_glue.py`,
`_chunk_worker.py`, `_preprocess_entry.py`, the preprocess CLI, and the Phase's unit and
integration checks. Focused Ruff and Ty checks passed, 61 schema/config/runner/cache/entry
tests passed, nine integration tests collected, and a source sweep found no downstream- or
client-specific identifiers or directory-name heuristics in the Phase surface.

## Findings

### preprocess-cli-outcomes | medium | Migration failures are not rendered exhaustively

`preprocess list` calls `load_preprocess_rules` without handling `PreprocessPolicyError`, so
a legacy configuration exits through an exception with no structured output. `preprocess
check` catches the base configuration exception but collapses the stable
`migration_required` and `admission_config_invalid` outcomes into the hard-coded
`invalid-config` kind. `preprocess status` reduces the same defect to
`config_valid=false` without the stable reason. A real `CliRunner` invocation against a
version-1 configuration reproduced exit code 1, an exposed `PreprocessPolicyError`, and
empty JSON output for `preprocess list --json`. This violates S106's requirement that
list, check, and status render schema migration and closed policy outcomes consistently.

### preprocess-test-integrity | medium | The claimed acceptance run relies on prohibited monkeypatching

The Phase summary counts CLI and batch tests among its 116 checks, but
`test_cli_preprocess.py` and `test_preprocess_batch.py` repeatedly use pytest's
`monkeypatch` fixture to mutate environment and module-visible state. The workspace test
policy expressly prohibits monkeypatches, fakes, mocks, stubs, patches, skips, and xfails
as passing-test shortcuts. Even where these instances only alter process state, the
acceptance evidence does not meet the repository's stated real-behavior test standard and
must be replaced with process-scoped or dependency-injected real behavior.

### preprocess-option-envelope | high | Valid TOML temporal values crash invocation and cache construction

`_preprocess_config.py` accepts arbitrary TOML dictionaries for `options`, while
`_resolved_policy.py` preserves and rematerializes `date`, `time`, and `datetime` values.
`PreprocessCacheIdentity.from_rule` then passes those objects to `json.dumps`, raising
`TypeError`, and `_invocation_envelope` passes them into the JSON-valued Pydantic schema,
raising `ValidationError`. A focused real-object reproduction observed both failures with
a TOML-valid date option. Because cache identity is computed before extraction error
handling, a syntactically valid schema-v2 rule can abort indexing instead of producing a
bounded per-file preprocess failure or a validation error at admission.

### preprocess-cache-cap | high | Cache hits bypass the current emitted-size policy

`PreprocessCacheIdentity.from_rule` omits `max_emitted_bytes` from the execution
fingerprint, and `read_cached_output` validates only the output schema. Each cache-hit path
in `_chunk_worker.py` returns the cached document before the current cap is applied; the
cap is passed only to a newly executed extractor. Lowering the configured limit, or
sharing a cache produced under a larger limit, therefore accepts output that current
policy would reject. The effective cap is semantics-bearing execution policy and must
either participate in identity or be enforced again on every cache read.

### preprocess-integration-coverage | high | S36 was closed without the required real extractor verification

The S36 plan requires real integration coverage for option propagation, configured
version invalidation, source-redirection refusal, metadata retention, and path-dependent
cache behavior. `test_preprocess_integration.py` contains none of those assertions, and
the Phase summary does not list that file as modified. Most configurations in the module
also omit the now-required schema version, target, and extractor version, so current
admission logic deterministically rejects them as migration-required before extraction.
Collect-only found nine legacy tests, but no test matching the S36 acceptance behaviors.
The Phase therefore lacks the end-to-end evidence required to close its central fidelity
contract, and the existing integration suite is not migrated to the schema it purports to
exercise.

## Recommendations

Reopen S32, S33, S36, and S106. Normalize temporal TOML values into a documented canonical
JSON representation or reject them during policy admission; never allow them to fail in a
worker. Bind the effective emitted-byte cap into cache semantics and enforce it on reads.
Give list, check, status, and run-one one exhaustive structured mapping for every stable
preprocess policy outcome. Replace the prohibited monkeypatched checks and add real
command and entry-point extractor integration that exercises every S36 behavior before
the Phase is marked complete again.
