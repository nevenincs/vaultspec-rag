---
tags:
  - '#plan'
  - '#operator-feedback-hardening'
date: '2026-07-24'
modified: '2026-07-24'
tier: L2
related:
  - '[[2026-07-24-operator-feedback-hardening-adr]]'
  - '[[2026-07-24-operator-feedback-hardening-audit]]'
---

# `operator-feedback-hardening` plan

### Phase `P01` - Render channel

Make operator feedback reach a terminal at all: resolve interactivity once from the real stream, and report continuously from the first statement of the command.

- [x] `P01.S01` - Resolve console interactivity once, from the real stdout stream; `src/vaultspec_rag/cli/_core.py`.
- [x] `P01.S02` - Add a startup status reporter whose output is stream-placed by mode; `src/vaultspec_rag/cli/_progress.py`.
- [x] `P01.S03` - Report every start pre-flight stage and the daemon cold-start phases; `src/vaultspec_rag/cli/_service_start.py`.

### Phase `P02` - Verdicts

Stop the service reporting a wrong outcome about itself: gate the start on serving, bound job-history degradation to the generation that earned it, and make a refusal state its cause.

- [x] `P02.S04` - Complete the start wait when the daemon can serve, not on the ready word; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `P02.S05` - Bound job-history degradation to the current service generation; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `P02.S06` - Log the startup refusal cause before the daemon process exit; `src/vaultspec_rag/server/_lifespan.py`.

### Phase `P03` - Legibility and control

Make what is reported readable and actionable, and keep the operator able to interrupt it.

- [x] `P03.S07` - Render every degradation with its cause and a remedying command; `src/vaultspec_rag/cli/_status_labels.py`.
- [x] `P03.S08` - Measure the vector store volume in the index disk pre-flight; `src/vaultspec_rag/index_profiles.py`.
- [x] `P03.S09` - Keep the main thread interruptible across blocking operator polls; `src/vaultspec_rag/cli/_process.py`.
- [x] `P03.S10` - Route every operator-facing size through one byte vocabulary; `src/vaultspec_rag/_units.py`.

## Description

## Steps

## Parallelization

## Verification
