---
tags:
  - '#exec'
  - '#preprocess-sandbox'
date: '2026-07-13'
modified: '2026-07-13'
body_hash: 'sha256:56ccee2ba69aaae6565111372634d1c2932a8b30084dfab3621a89cd6eb955df'
step_id: 'S01'
related:
  - "[[2026-07-13-preprocess-sandbox-plan]]"
---

# Delete the trust store module and every reference to it

## Scope

- `src/vaultspec_rag/indexer/_preprocess_trust.py`

## Description

- Delete the per-root trust-on-first-use store module in full.
- Remove every reference to it across production sources: the loader gate import in `_preprocess_config.py` and the four imported symbols in `cli/_preprocess.py` (folded into S02 and S04).
- Confirm no remaining `_preprocess_trust`, `hash_rule_set`, `record_trust`, `read_trust`, `remove_trust`, `is_trusted`, `TrustRecord`, or `trust_store_path` reference survives in production code via grep.

## Outcome

The trust store module is gone and no production source imports it. The only surviving references are the intentional regression guards in `test_cli_preprocess.py` (asserting the retired knob's absence) and the P04-owned integration test, which still imports the deleted symbols and is left untouched per the phase contract.

## Notes

The integration test `test_preprocess_integration.py` still imports `hash_rule_set` and `record_trust` from the deleted module and reads the removed `PREPROCESS_TRUST_ALL` env member; these breakages are enumerated for P04 to repair.
