---
tags:
  - '#exec'
  - '#platform-backend-selection'
date: '2026-09-01'
modified: '2026-09-01'
body_schema: 'body-v1'
body_hash: 'sha256:c7290d81f1f30130e4f599d8facdf1bdbe346f98abd7e2dd1c7ffd63d9010566'
related:
  - "[[2026-09-01-platform-backend-selection-plan]]"
---
# `platform-backend-selection` `W03.P07` summary

Added a dedicated real-Mac MPS acceptance tier and blocking CI gate.

## Description

The opt-in MPS integration test runs cache-only with CPU fallback disabled, loads dense, sparse, and reranker models together, verifies every model's parameters reside on MPS, and performs representative forwards. Marker and workflow guards keep it out of ordinary and CUDA borrower lanes. The blocking macOS runner job covers main pushes before publication, releases, and manual runs.

## Verification

Marker tests, collect-only selection, workflow validation, actionlint, and parameter-placement mutation guards passed. A bounded earlier probe on the provisioned Mac confirmed the model stack fits and runs on MPS; the final heavy guard was deferred while the host reported battery power.
