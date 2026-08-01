---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-21'
body_hash: 'sha256:068c5e6928fd46dfa8c8f71f12736ae08a62f4997ab167f0130aa041885132f9'
step_id: 'S06'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# Drop the sandbox-policy fields from the preprocess context construction and any backend mentions

## Scope

- `src/vaultspec_rag/indexer/_preprocess_config.py`

## Description

- Remove the `server_mode`/`unsandboxed` fields from `PreprocessContext`.
- Reframe the loader docstrings: the `off` kill switch is the only gate; a root's preprocess config is repo-authored code.

## Outcome

`PreprocessContext(config, cache_root, max_emitted_bytes, project_root)`.

## Notes

None.
