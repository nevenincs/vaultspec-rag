---
tags:
  - '#exec'
  - '#search-postprocess'
date: '2026-05-31'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:ceda41016aa360465c13ec57e738be28ae97ca6acb6fe288846b1c5f6a6c6427'
related:
  - "[[2026-05-31-search-postprocess-plan]]"
---

# `search-postprocess` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/search.py`
- `S02` `M` `src/vaultspec_rag/search.py`
- `S03` `M` `src/vaultspec_rag/api.py`
- `S04` `M` `src/vaultspec_rag/cli.py`
- `S05` `M` `src/vaultspec_rag/tests/test_search_unit.py`
- `S06` `M` `README.md`
- `S06` `M` `src/vaultspec_rag/README.md`
- `S06` `verify:` `.venv/Scripts/vaultspec-rag.exe search --help` -> `pass`
- `S06` `verify:` `uv run --no-sync mdformat --check README.md src/vaultspec_rag/README.md` -> `pass`
- `S06` `verify:` `uv run --no-sync pymarkdown --config .pymarkdown.json scan README.md src/vaultspec_rag/README.md` -> `pass`

## Notes

- `S01` Historical change attribution from Git commit 60e9a69078ea98203abe4c8d4a4116402a8a9612. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S02` Historical change attribution from Git commit 60e9a69078ea98203abe4c8d4a4116402a8a9612. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S03` Historical change attribution from Git commit 60e9a69078ea98203abe4c8d4a4116402a8a9612. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S04` Historical change attribution from Git commit 60e9a69078ea98203abe4c8d4a4116402a8a9612. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S05` Historical change attribution from Git commit 60e9a69078ea98203abe4c8d4a4116402a8a9612. No fresh runtime or unretained historical passing result is asserted. The cited operation matches a substantive step action. Multi-action steps and their original execution gates are not certified complete by this attribution.
- `S06` Actual current root-owned documentation repair2026-10-01 covers default near-score locale variants, both dedup flags, and prefer production/tests/documentation with concrete examples, grounded in real postprocessor semantics and CLI help. Artifacts search-doc-options-help.log, search-doc-options-format.log, search-doc-options-markdown.log each exit0. Original historical README completion proof remains absent; this is fresh repair, not a fabricated May claim. Existing discovery-rule prefer example is unchanged; original both-flags policy scope remains partial and no generated policy edit or new ruling is implied.
