---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S35'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# reframe the getting-started flow to install-then-setup with a server-backed RAG as the standard path and local-only as the minimal alternative

## Scope

- `docs/getting-started.md`

## Description

- Read both governing ADRs (`server-first-default` and `provisioning-setup`) to ground the reframe.
- Reframed the tutorial intro from "pointed it at a project" to "provisioned a server-backed RAG", noting the one-time server-binary fetch in the timing expectations.
- Replaced the bare GPU-config step with an "install and provision" step that leads with the server-first default, documents the default provisioning of torch, models, and the qdrant binary, the sync-vocabulary reporting, the two-phase torch step (`uv sync`), and the `--dry-run` preview.
- Added a "minimal alternative: local-only" subsection presenting `--local-only` as a deliberate first-class opt-out for CI, air-gapped, and small-project hosts.
- Updated the wrap-up and Step 4 prose to reflect a server-backed install and pointed service-mode readers at `server doctor`.

## Outcome

The getting-started flow now leads with the server-first standard path (install provisions a server-backed RAG) and presents `--local-only` as the minimal alternative. Every documented command and flag was verified against the live `--help` surface: `vaultspec-rag install` (default provisioning, `--local-only`, `--dry-run`, `--yes`), the two-phase torch step, and `server doctor`. `mdformat` is a no-op and `pymarkdown --config .pymarkdown.json scan` exits 0.

## Notes

- The live `install --help` confirms default provisioning of models + qdrant binary plus `--local-only` / `--skip-torch` / `--skip-models` / `--skip-qdrant` / `--no-provision`; no fictional flags were introduced.
