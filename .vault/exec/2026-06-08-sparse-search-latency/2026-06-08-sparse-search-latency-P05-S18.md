---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-09'
modified: '2026-06-30'
step_id: 'P05.S18'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` P05.S18 - mcp/ import-isolation guard test

scope: `src/vaultspec_rag/tests/test_mcp_import_isolation.py`

## Description

Added a static guard test asserting that no `.py` file under `src/vaultspec_rag/mcp/`
imports from `vaultspec_rag.server`, `vaultspec_rag.store`, `vaultspec_rag.service`, or
`vaultspec_rag.registry`. The test parametrises over every file in the package, parses each
with the `ast` module, and inspects `Import` / `ImportFrom` nodes — covering both absolute
(`import vaultspec_rag.server`, `from vaultspec_rag.server import X`) and relative
(`from ..server import X`) forms by resolving `node.level` against the file's package path.
No production module is imported at runtime, so the test needs no GPU or daemon.

## Outcome

Test passes — `mcp/` is confirmed import-isolated from the daemon internals. The invariant
from the deconflation ADR is now machine-enforced and will fail CI if a future change
reintroduces a forbidden import.

## Notes

The permitted `cli._service_status` import is not in the forbidden set; the test targets the
four backend modules named in the plan step.
