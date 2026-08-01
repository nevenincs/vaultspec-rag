---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:78aa1ca4961e6ae719ce3ed7843ecc3bcbcd66cd497efe1a10462e8b41247fa7'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# `index-drift-hardening` `P04` summary

All three Steps closed (S12-S14). Files touched across the Phase:

- Modified: `src/vaultspec_rag/watcher.py`
- Created: `src/vaultspec_rag/tests/test_watcher_unit.py`
- Modified: `src/vaultspec_rag/tests/integration/test_preprocess_integration.py`
- Modified: `README.md`
- Modified: `docs/preprocessing-hooks.md`
- Modified: `docs/configuration.md`
- Modified: `docs/cli.md`

## Description

Closed the residual watcher gaps, proved the feature end to end, and aligned
the operator documentation (ADR D9-D10). The watcher now admits the three
index-shaping control files as ordinary code changes - a deliberate widening
of D9, recorded in the S12 notes, because an ignore edit with no subsequent
source change would otherwise never trigger the incremental entry the epoch
check lives in - re-resolves its preprocess config when the root config file
changes (single-slot holder the change filter closes over), and watches
non-vault markdown to match the chunker's language map. The integration suite
gained sentinel-based security proofs (the off kill switch outranks trust-all;
an untrusted root under the default mode executes nothing and the warning
names the trust verb; a trusted root executes and a command edit self-revokes)
and the consumer-reported drift scenario: only the edited ignore file is
forwarded down the scoped path and the membership-epoch escalation prunes the
newly-ignored file's chunks while retaining the rest. README, the
preprocessing guide's security posture, the configuration reference, and the
CLI reference now document the tri-state, the trust flow, and the drift
self-healing, with every mention of the removed enable knob gone.

Verification: six new watcher unit tests and ten integration tests (real GPU
and Qdrant) pass; ruff and basedpyright report zero findings on the touched
modules; markdown hooks are green on all four docs files; grep confirms no
stale enable-knob or declared-equals-trusted framing anywhere operator-facing.
