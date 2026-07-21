---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S11'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Add end-to-end install dry-run drift upgrade uninstall and host CLI acceptance coverage

## Scope

- `src/vaultspec_rag/tests/integration/test_install.py`

## Description

- Enroll both project-native providers in real temporary workspaces before installing.
- Assert canonical launch parity in Claude JSON and Codex TOML targets.
- Drift both provider targets and prove dry-run reports repairs without changing bytes.
- Preserve Core and user sibling entries plus Core ownership fingerprints during selective
  RAG uninstall.
- Initialize and explicitly trust an isolated temporary Codex project before querying the
  real host CLI.
- Query the real Claude Code and Codex CLIs for the installed RAG project entry.

## Outcome

Thirty-seven integration tests pass against the Core feature source. Fresh install,
upgrade, drift reporting, dry-run byte invariance, selective uninstall, and symmetric
round-trip behavior all converge for Claude Code and Codex. Both real host CLIs recognize
the canonical `uvx --from vaultspec-rag[mcp]` project entry; the Codex acceptance uses an
isolated `CODEX_HOME` with the temporary git project explicitly trusted.

## Notes

The first Codex host query correctly rejected the project-local configuration because a
temporary project is untrusted by default. An isolated trust declaration proved that the
generated TOML was valid and keeps the acceptance independent of personal host settings.
Ruff, formatting, Ty, BasedPyright, and the full complexity gate pass. The released Core
minimum remains intentionally deferred to `S12`.
