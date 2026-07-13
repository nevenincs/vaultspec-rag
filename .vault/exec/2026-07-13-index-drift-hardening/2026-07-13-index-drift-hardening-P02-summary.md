---
tags:
  - '#exec'
  - '#index-drift-hardening'
date: '2026-07-13'
modified: '2026-07-13'
related:
  - "[[2026-07-13-index-drift-hardening-plan]]"
---

# `index-drift-hardening` `P02` summary

All four Steps closed (S05-S08). Files touched across the Phase:

- Modified: `src/vaultspec_rag/config.py`
- Created: `src/vaultspec_rag/indexer/_preprocess_trust.py`
- Modified: `src/vaultspec_rag/indexer/_preprocess_config.py`
- Modified: `src/vaultspec_rag/tests/test_preprocess_config.py`

## Description

Replaced the blanket preprocess enable gate with the tri-state mode and the
per-root trust-on-first-use store (ADR D4-D6). The legacy enable knob was
removed outright - enum member, override-map entry, config field, and loader
gate - with no back-compat alias (owner decision at ADR approval). The mode
resolves live from two env vars in a dedicated property: the off kill switch
wins over trust-all, which wins over the configured value; unrecognised values
degrade to the safe trust-gated default. The stdlib-only trust store mirrors
the storage manifest: a status-dir sidecar keyed by root collection prefix,
holding the blake2b of the resolved rule set (pattern, command or entry point,
on-error, priority, resolved timeout, options, order), written atomically
under a process lock, degrading to untrusted on corruption. The loader
enforces the gate after resolution on the non-strict path only: off returns
zero rules, trust-all returns rules with a loud bypass warning, and the
default returns rules only on a trust-record hash match, else zero rules plus
one loud actionable warning naming the trust verb. The strict path (backing
the validate-only check verb) bypasses the gate; the loader and spawn worker
never prompt.

Verification: 29 unit tests cover loader enforcement per mode, hash stability
across benign edits and change on command edits, corrupt-store degradation,
record round-trips, and status-dir isolation; ruff and basedpyright report
zero findings on all four files. The orchestrator independently verified that
the only other executing verb (run-one) flows through the non-strict gate and
that strict stays confined to the validate-only check verb, and end-to-end
sentinel proofs for the off and untrusted tiers landed with the P04
integration suite.
