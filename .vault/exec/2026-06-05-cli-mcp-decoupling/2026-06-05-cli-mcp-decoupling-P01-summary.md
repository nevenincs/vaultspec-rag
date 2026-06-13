---
tags:
  - '#exec'
  - '#cli-mcp-decoupling'
date: '2026-06-05'
modified: '2026-06-05'
related:
  - '[[2026-06-05-cli-mcp-decoupling-plan]]'
  - '[[2026-06-05-cli-mcp-decoupling-adr]]'
---

# `cli-mcp-decoupling` `P01` summary

Phase P01 decouples the benchmark and quality testing orchestration logic from the CLI command modules, standardizing them into the core backend facade in `src/vaultspec_rag/api.py`.

- Modified: `src/vaultspec_rag/api.py` (added `run_benchmark` and `run_quality_probe`)
- Modified: `src/vaultspec_rag/cli/_benchmark.py` (delegated to backend `run_benchmark`)
- Modified: `src/vaultspec_rag/cli/_quality.py` (delegated to backend `run_quality_probe`)
- Closed Step: `P01.S01` (`.vault/exec/2026-06-05-cli-mcp-decoupling/2026-06-05-cli-mcp-decoupling-P01-S01.md`)
- Closed Step: `P01.S02` (`.vault/exec/2026-06-05-cli-mcp-decoupling/2026-06-05-cli-mcp-decoupling-P01-S02.md`)
- Closed Step: `P01.S03` (`.vault/exec/2026-06-05-cli-mcp-decoupling/2026-06-05-cli-mcp-decoupling-P01-S03.md`)
- Closed Step: `P01.S04` (`.vault/exec/2026-06-05-cli-mcp-decoupling/2026-06-05-cli-mcp-decoupling-P01-S04.md`)

## Description

The benchmark logic has been successfully extracted into the backend API function `run_benchmark` which executes under a leased project slot. The CLI benchmark command now acts solely as a display/formatting client.

Similarly, the quality test logic was moved to the backend API function `run_quality_probe` which allocates a temporary workspace directory slot, indexes synthetic documents, runs needle-based search probes, calculates search precision, and handles clean slot eviction. The CLI quality command now delegates to this facade and reports the results.

## Tests

Verification commands:

- `uv run ruff check src/vaultspec_rag/` - all checks passed.
- `uv run pytest -m unit` - 606 passed.
