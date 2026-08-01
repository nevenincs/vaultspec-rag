---
tags:
  - '#research'
  - '#maintainability-remediation'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:083145a375a6570d323808ea59287fd4cd97886f945af2ae8f5fde94346a5645'
related:
  - "[[2026-07-27-module-split-production-length-gate-research]]"
  - "[[2026-07-27-module-split-production-package-seams-reference]]"
  - "[[2026-07-27-maintainability-remediation-radon-module-ownership-reference]]"
---

# `maintainability-remediation` research: `radon maintainability floor`

## Findings

### Retained preamble

The report identifies ten modules at Radon's floor value of 0.00: three
production modules that mix several ownership domains and seven integration
modules that combine independent end-to-end scenarios. The existing
facade-based package-split decision does not satisfy the current canonical-code
rule, so the remediation needs concrete-owner imports and responsibility seams,
not a filter, threshold change, or re-export wrapper.

### The health report's MI population and values are real

`tools/health_report.py:209-224` reads every Python file and computes Radon's
multi-line maintainability index through `radon.metrics.mi_visit`; it sorts the
scores and reports the lowest entries. The current `--fast --top 10` result has
the reported ten modules, all at 0.00. Radon's CLI itself is not a usable
verification path here: `tools/health_report.py:26-29` records the project TOML
interpolation failure and intentionally uses the API instead.

### Existing extraction policy must be revised, not repeated

The accepted `2026-06-01-module-split-adr` chose package-root re-exports so
callers would remain unchanged. The later research at
`2026-07-27-module-split-production-length-gate-research` establishes that this
contradicts the current canonical-code rule: a forwarding export preserves two
paths to one behaviour. The remediation must therefore move a concern to one
concrete owner and migrate every production and test import in the same change.

### The ten floor-score modules split into two kinds of seam

`cli/_service_jobs.py` contains display classification, summary rendering,
collection filtering, HTTP command adaptation, and command registration.
`indexer/_run_ledger.py` combines immutable ledger models, generation lifecycle,
unit recording, state queries, and SQLite schema/transaction work.
`job_manager.py` combines public result/context models, scheduling, attempt
execution, control transitions, persistence, restoration, and snapshots. The
integration modules mix several independently runnable service scenarios with
their scenario-specific process, request, polling, and assertion helpers.

Keeping the modules whole preserves discoverability at the cost of the floor
metric; splitting by a fixed line count risks moving tightly coupled behaviour
or duplicating helpers. The evidence favours ownership-based files with direct
imports, while retaining each test as a real process/service exercise.

### Scope excludes metric suppression and test doubles

Filtering the report, changing its ranking population, or exempting the listed
test files would hide the same complex code and conflicts with the request.
Likewise, replacing integration orchestration with fake service implementations
would violate the real-behaviour test requirement. The follow-on ADR must settle
the ownership map, migration sequencing, and the exact maintainability target;
this research does not prescribe an unverified numeric threshold.

## Sources

- `tools/health_report.py:26-29`
- `tools/health_report.py:209-224`
- `src/vaultspec_rag/cli/_service_jobs.py:1-1608`
- `src/vaultspec_rag/indexer/_run_ledger.py:1-1916`
- `src/vaultspec_rag/job_manager.py:1-2955`
- `src/vaultspec_rag/tests/integration/test_index_job_control.py:1-1441`
- `src/vaultspec_rag/tests/integration/test_install.py:1-3398`
- `src/vaultspec_rag/tests/integration/test_jobs_registry.py:1-1021`
- `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py:1-1060`
- `src/vaultspec_rag/tests/integration/test_service_jobs.py:1-2872`
- `src/vaultspec_rag/tests/integration/test_service_lifecycle.py:1-2589`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py:1-1540`
- `2026-06-01-module-split-adr`
- `2026-07-27-module-split-production-length-gate-research`
