---
tags:
  - '#exec'
  - '#preprocess-sandbox-removal'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - "[[2026-07-14-preprocess-sandbox-removal-plan]]"
---

# `preprocess-sandbox-removal` `P02` summary

All seven Steps closed in one commit. The control surface is two-state: default (on, direct execution) or off (kill switch). The unsandboxed escape hatch is gone from config, both CLI verbs, the daemon env forwarding, and the status/reporting surfaces. S13 resolved as a no-op after grounding (jobs reporting was already sandbox-free).

- Modified: `src/vaultspec_rag/config.py`
- Modified: `src/vaultspec_rag/cli/_index.py`
- Modified: `src/vaultspec_rag/cli/_service_lifecycle.py`
- Modified: `src/vaultspec_rag/cli/_preprocess.py`
- Modified: `src/vaultspec_rag/cli/_process.py`
- Modified: `src/vaultspec_rag/server/_routes.py`

## Description

Collapsed PreprocessMode to default/off, deleted the PREPROCESS_UNSANDBOXED env knob and --preprocess-unsandboxed flags (BREAKING), repointed preprocess status at direct execution, and kept --no-preprocess / VAULTSPEC_RAG_PREPROCESS=off as the only kill switches.
