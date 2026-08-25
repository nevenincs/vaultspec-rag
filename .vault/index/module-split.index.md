---
generated: true
tags:
  - '#index'
  - '#module-split'
date: '2026-08-14'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:ce2aaf727163fee8f64c29e77130dc2b4164a4735295a08fc0596786112fb5fe'
related:
  - '[[2026-06-01-module-split-P07-S07]]'
  - '[[2026-06-01-module-split-P08-S08]]'
  - '[[2026-06-01-module-split-P09-S09]]'
  - '[[2026-06-01-module-split-P09-S10]]'
  - '[[2026-06-01-module-split-P10-S11]]'
  - '[[2026-06-01-module-split-P12-S13]]'
  - '[[2026-06-01-module-split-P13-S14]]'
  - '[[2026-06-01-module-split-P14-S15]]'
  - '[[2026-06-01-module-split-P15-S16]]'
  - '[[2026-06-01-module-split-adr]]'
  - '[[2026-06-01-module-split-audit]]'
  - '[[2026-06-01-module-split-plan]]'
  - '[[2026-06-01-module-split-research]]'
  - '[[2026-07-27-module-split-install-test-split-audit]]'
  - '[[2026-07-27-module-split-job-unit-test-split-audit]]'
  - '[[2026-07-27-module-split-process-probe-split-audit]]'
  - '[[2026-07-27-module-split-production-length-gate-research]]'
  - '[[2026-07-27-module-split-production-package-seams-reference]]'
  - '[[2026-07-27-module-split-run-ledger-review-audit]]'
  - '[[2026-07-27-module-split-service-jobs-test-split-audit]]'
  - '[[2026-07-27-module-split-service-lifecycle-test-split-audit]]'
---

# `module-split` feature index

Auto-generated index of all documents tagged with `#module-split`.

## Documents

### adr

- `2026-06-01-module-split-adr` - `module-split` adr: direct-owner decomposition of overlength modules | (**status:** `accepted`)

### audit

- `2026-06-01-module-split-audit` - `module-split` audit: python module reaudit + monolith-to-package split blueprint
- `2026-07-27-module-split-install-test-split-audit` - `module-split` audit: `install test split`
- `2026-07-27-module-split-job-unit-test-split-audit` - `module-split` audit: `job unit test split`
- `2026-07-27-module-split-process-probe-split-audit` - `module-split` audit: `process probe split`
- `2026-07-27-module-split-run-ledger-review-audit` - `module-split` audit: `run ledger review`
- `2026-07-27-module-split-service-jobs-test-split-audit` - `module-split` audit: `service jobs test split`
- `2026-07-27-module-split-service-lifecycle-test-split-audit` - `module-split` audit: `service lifecycle test split`

### exec

- `2026-06-01-module-split-P07-S07` - Split canonical process-probe guard domains into directly collected test modules and concrete shared helpers
- `2026-06-01-module-split-P08-S08` - Split installation integration behavior domains into directly collected modules
- `2026-06-01-module-split-P09-S09` - Split job-manager unit behavior domains into directly collected modules
- `2026-06-01-module-split-P09-S10` - Split service jobs integration behavior domains into directly collected modules
- `2026-06-01-module-split-P10-S11` - Split service lifecycle integration behavior domains into directly collected modules
- `2026-06-01-module-split-P12-S13` - Decompose storage-operation responsibilities and migrate all direct importers
- `2026-06-01-module-split-P13-S14` - Decompose store responsibilities and migrate all direct importers
- `2026-06-01-module-split-P14-S15` - Decompose watcher responsibilities and migrate all direct importers
- `2026-06-01-module-split-P15-S16` - Decompose run-ledger responsibilities and migrate all direct importers after the active edit lands

### plan

- `2026-06-01-module-split-plan` - `module-split` `decompose overlength modules into direct owners` plan

### reference

- `2026-07-27-module-split-production-package-seams-reference` - `module-split` reference: `production package seams`

### research

- `2026-06-01-module-split-research` - module-split research: package + `__init__` re-export pattern
- `2026-07-27-module-split-production-length-gate-research` - `module-split` research: `production length gate`
