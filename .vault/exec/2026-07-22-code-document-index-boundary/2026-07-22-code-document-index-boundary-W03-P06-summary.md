---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:5b67b0d762317125fb464b61728e090f777a40403b752da786d995e8139a93a1'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# `code-document-index-boundary` `W03.P06` summary

Completed bounded document execution, honest unsuccessful-file outcomes, independent retry ownership, and model-free service admission.

- Modified: `_chunk_worker.py`, `_preprocess_runner.py`, `_document_indexer.py`
- Modified: `_document_meta.py`, `_preprocess_glue.py`, `_streaming.py`
- Modified: `index_profiles.py`, `job_dispatch.py`, `job_models.py`, `jobs.py`
- Modified: `watcher.py`, `watcher_retry.py`, `_watcher.py`
- Modified: `test_document_execution.py`, `test_document_indexing.py`, `test_jobs_unit.py`

## Description

Document-target binary input now reaches only its extractor; raw decoding happens after code admission; and skip, fail, and passthrough retain their declared kind. Streaming source identity, encoded output accounting, aggregate chunk and weighted queue limits, cancellation-aware subprocess control, and incomplete failure metadata keep work bounded and retryable.

Document jobs use the shared service limiter, registry lease, writer authority, GPU gate, and memory policy while retaining separate collection, metadata, watcher retry, circuit, and generation state. The named document support profile is validated before durable HTTP mutation and GPU model loading. Read-only status reports the latest vault, code, and document job generations with degraded reasons.

The phase boundary passed focused lint, formatting, typing, and cognitive-complexity checks across eighteen files. Twelve real-behavior tests passed across extraction, cancellation, document storage, kill-switch retention, watcher handoff, retry generation, and jobs status.
