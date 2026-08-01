---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a9daa1499fd3bd5d1653d872450a2a5c225cf292c961f2f0755642df30255f78'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` `W03.P05` summary

Completed the faithful invocation, cache identity, lifecycle, and operator
inspection contracts for generic preprocessing.

- Modified: `_preprocess_schema.py`, `_preprocess_config.py`
- Modified: `_resolved_policy.py`, `_preprocess_runner.py`
- Modified: `_preprocess_cache.py`, `_chunk_worker.py`
- Modified: `_codebase_indexer.py`, `_preprocess.py`
- Modified: `test_preprocess_cache.py`, `test_preprocess_runner.py`
- Modified: `test_preprocess_entry.py`, `test_cli_preprocess.py`

## Description

Introduced one versioned envelope shared by command and entry-point extractors;
bound emitted output to the host-owned source; bounded metadata; made cache
identity sensitive to source path, source hash, schema, options, version,
target, mode, and invocation; required explicit path-independent reuse; and
decoupled cache lifetime from collection cleanup. CLI list, check, run-one, and
status now expose and obey the same contract.

The phase boundary exercised 116 real-behavior checks across subprocess,
entry-point, batch, schema, configuration, cache, and CLI paths. The initial
run passed 114 checks; the two kill-switch diagnostics were corrected and then
passed. Focused lint and type checks passed.
