---
tags:
  - '#exec'
  - '#managed-log-contract'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:7f095d258868a2482843b6fbf8a7e7b96f0ddce082254e57b927709e3fc536e5'
related:
  - "[[2026-07-21-managed-log-contract-plan]]"
---

# `managed-log-contract` `W02.P05` summary

The CLI now renders explicit source groups from the live service or the production local reader after service shutdown.

- Modified: `src/vaultspec_rag/cli/_service_logs.py`
- Modified: `src/vaultspec_rag/tests/test_cli_server.py`

## Description

The activity parser, raw compatibility flag, and service-only command identity were removed. Live and post-crash CLI tests pass.
