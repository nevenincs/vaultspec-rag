---
tags:
  - '#plan'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
tier: L1
related:
  - '[[2026-07-23-cli-startup-feedback-adr]]'
  - '[[2026-07-23-cli-startup-feedback-research]]'
---

# `cli-startup-feedback` plan

Extend the shipped per-stage `phase_detail` increment into the structured,
count-bearing startup-progress contract the ADR decided, so `server start`
renders genuine live progress.

## Description

Executes `2026-07-23-cli-startup-feedback-adr`. The daemon already publishes a
coarse per-stage `phase_detail` string that the start spinner renders (commit
`034a0dd4`); this plan carries that to the decided contract: a structured
startup-progress descriptor (stage id, label, optional `done`/`total`) on the
discovery/status view, published at each cold-start stage boundary with a model
count where one exists, and a CLI wait that upgrades the spinner to a
determinate bar when a total is present while falling back to the named spinner
for an older daemon. Byte-granular download bars are gated behind an
investigation Step, per the ADR constraint. Service startup is the surface in
scope; index-build progress stays with the jobs-operability surface.

## Steps

- [x] `S01` - Carry a structured startup-progress descriptor (stage id, label, optional done/total) on the discovery snapshot and \_DiscoveryPublisher, additive and best-effort; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `S02` - Publish the structured descriptor at each cold-start stage boundary, filling done/total for the model-load count; `src/vaultspec_rag/server/_lifespan.py`.
- [x] `S03` - Render a determinate Rich bar in the start wait when total is present, falling back to the named spinner for a descriptor-less daemon; `src/vaultspec_rag/cli/_service_start.py`.
- [x] `S04` - Investigate whether the Hugging Face and pinned-binary downloaders expose incremental byte callbacks, and record whether download-percentage bars are feasible; `src/vaultspec_rag/tests/quality/ab_report.md`.
- [x] `S05` - Add unit tests for the descriptor round-trip and the CLI bar/spinner rendering, including the older-daemon fallback guard; `src/vaultspec_rag/tests/test_machine_discovery.py`.
- [ ] `S06` - Verify on a real GPU cold start that provisioning, per-model load count, and reranker stages render live, and record the execution; `src/vaultspec_rag/cli/_service_start.py`.

## Parallelization

`S04` (the download-callback investigation) is independent and can run in
parallel with `S01`-`S03`. `S01` precedes `S02` (the publisher must carry the
descriptor before the lifespan can fill it) and `S02`/`S01` precede `S03` (the
CLI renders what the daemon publishes). `S05` follows the code Steps; `S06` is
the end-to-end verification and runs last.

## Verification

- The discovery snapshot and `_DiscoveryPublisher` round-trip the structured
  progress descriptor, proven by a unit test that also confirms an absent
  descriptor leaves behaviour unchanged (no schema bump).
- The CLI start wait renders a determinate bar when `total` is present and the
  named spinner otherwise, proven by a unit test over `_startup_phase_label`
  and its bar path, including the older-daemon fallback (guard test).
- A real GPU cold start shows the provisioning, per-model load count, and
  reranker stages live, recorded in the S06 execution record.
- The plan is complete when every Step is closed (`- [x]`).
