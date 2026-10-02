---
tags:
  - '#exec'
  - '#install-command'
date: '2026-04-12'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:09b54e23d43256569ee097d597bb4635664c8739309c60c9df6efcd29f0d9ab5'
related:
  - "[[2026-04-12-vaultspec-rag-install-plan]]"
---

# `install-command` ledger

## Changes

- `S02` `M` `pyproject.toml`
- `S03` `A` `src/vaultspec_rag/builtins/__init__.py`
- `S04` `A` `src/vaultspec_rag/commands.py`
- `S05` `M` `src/vaultspec_rag/cli.py`
- `S06` `A` `src/vaultspec_rag/tests/integration/test_install.py`
- `S01` `M` `pyproject.toml`

## Notes

- `S02` Historical change attribution from Git commit 2aa136447b2ca7fdee3290f0a4d0634d48c9ede2. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S03` Historical change attribution from Git commit 2aa136447b2ca7fdee3290f0a4d0634d48c9ede2. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S04` Historical change attribution from Git commit 2aa136447b2ca7fdee3290f0a4d0634d48c9ede2. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S05` Historical change attribution from Git commit 2aa136447b2ca7fdee3290f0a4d0634d48c9ede2. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S06` Historical change attribution from Git commit 2aa136447b2ca7fdee3290f0a4d0634d48c9ede2. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S01` Historical local operation 3eadcffb removes the temporary companion Git pin after core0.1.10 publication. External vaultspec-core commit9d913bb8f01db3a3865eb79bdb48b0a5f911ac13 implements persisted managed-entry ownership and orphan pruning, with real-filesystem TestMcpSyncPrune tests authored in `tests/test_mcps.py;` merge166ba697 lands PR69. Sources inspected read-only in sibling core checkout. Test authorship and actual landed source are proven; no historical test execution or fresh installer/runtime PASS is inferred.
