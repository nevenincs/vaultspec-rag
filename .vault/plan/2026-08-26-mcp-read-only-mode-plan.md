---
tags:
  - '#plan'
  - '#mcp-read-only-mode'
date: '2026-08-26'
modified: '2026-08-26'
body_hash: 'sha256:fbc4d6b1073dc59f7a764a67a30d48b4b3c0084b8de798950caec976d38075cd'
tier: L1
related:
  - '[[2026-08-26-mcp-read-only-mode-adr]]'
  - '[[2026-08-26-mcp-read-only-mode-research]]'
---

# `mcp-read-only-mode` plan

## Description

## Steps

- [x] `S01` - Derive the served surface from the read-only annotation each tool already declares, so no second list can drift from it; `src/vaultspec_rag/mcp/_tools.py`.
- [x] `S02` - Parse the read-only flag alongside the arguments the entry point already handles, and remove the mutating tools before the server serves; `src/vaultspec_rag/server/_main.py`.
- [x] `S03` - Assert the read-only listing serves exactly the read set and that no mutating tool survives the flag, so a tool added later cannot appear silently; `src/vaultspec_rag/tests/test_server.py`.
- [x] `S04` - Assert the default launch still serves every tool, so the flag cannot narrow the operator and CI surface; `src/vaultspec_rag/tests/test_server.py`.

## Parallelization

## Verification
