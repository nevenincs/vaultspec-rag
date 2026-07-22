---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace code-document-index-boundary with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

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
