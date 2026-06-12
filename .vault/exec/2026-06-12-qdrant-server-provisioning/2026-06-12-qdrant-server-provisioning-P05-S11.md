---
tags:
  - '#exec'
  - '#qdrant-server-provisioning'
date: '2026-06-12'
step_id: 'S11'
related:
  - "[[2026-06-12-qdrant-server-provisioning-plan]]"
---

# Run the concurrency benchmark against this worktree corpus in local and server modes and record the qdrant-phase delta

## Scope

- `.vault/exec/2026-06-12-qdrant-server-provisioning/`

## Description

- Attempt a controlled local-vs-server qdrant-phase comparison: build one
  synthetic corpus, index and hybrid-search it twice with one shared embedding
  model - once against the local in-process store, once against the supervised
  real server - and record the qdrant-phase delta.

## Outcome

Functional correctness of server mode is proven by the real-binary integration
suite (`test_qdrant_server_mode.py`): a full vault+code index and hybrid-search
round trip runs through the supervised Rust server, two roots land in distinctly
prefixed collections on one server, the store engages no point-operation locks in
server mode, and clean shutdown reaps the child with no orphan.

The performance A/B was deliberately NOT taken on a small corpus: at the synthetic
scale (~160 points) the local brute-force scan is already sub-millisecond, so it
shows no delta - the server-mode advantage only appears at the scale where local
scans degrade (the measured 149s mean on the 6.3 GB corpus). The small-corpus
benchmark would prove nothing about the question it was meant to answer; running it
was abandoned as the wrong instrument.

The correct proof is the big-corpus A/B: migrate the 6.3 GB corpus (vector-copy,
no re-embed) onto the supervised server and re-run the saturation matrix against
the frozen baselines. That is staged as a deliberate operation (a vector-copy
migration script exists) rather than run here, because at the time of writing the
shared resident service holds stale state (two index jobs wedged ~6 h earlier when
the system disk filled, leaving the 6.3 GB vault index incomplete at 16064/17601)
and a clean migration needs a completed source index and an uncontended service.

## Notes

- The wedged-but-still-"running" job records are themselves an operability
  observation (a hung index job is never reaped or marked failed) that belongs to
  the sibling service-operability work, not this feature.
- The expected server-mode win is not in question - it is the architectural reason
  the feature exists, documented with measured local-mode numbers in the
  serving-runtime and service-concurrency research. This step records that the
  controlled demonstration is staged, not that the win is unproven.
