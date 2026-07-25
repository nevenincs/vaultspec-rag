---
tags:
  - '#plan'
  - '#cli-argv-expansion'
date: '2026-07-25'
modified: '2026-07-25'
tier: L1
related:
  - '[[2026-07-25-cli-argv-expansion-adr]]'
  - '[[2026-07-25-cli-argv-expansion-research]]'
---
# `cli-argv-expansion` plan

- [x] `S01` - Route every program invocation through one call that disables the command-line rewriting pass; `src/vaultspec_rag/cli/_app.py, src/vaultspec_rag/cli/__init__.py, src/vaultspec_rag/__main__.py`.
- [x] `S02` - Guard the argv path with subprocess tests and prove the delivered pattern filters real results; `src/vaultspec_rag/tests/test_cli_argv_expansion.py, src/vaultspec_rag/tests/test_cli.py`.

## Description

## Steps

## Parallelization

## Verification
