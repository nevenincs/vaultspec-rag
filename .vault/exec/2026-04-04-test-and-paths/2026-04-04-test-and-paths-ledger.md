---
tags:
  - '#exec'
  - '#test-and-paths'
date: '2026-04-04'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:3760cb5b571de8f7cb9358e3e54df880d8b36f3bcdff6df587b092d7712809d5'
related:
  - "[[2026-04-04-test-and-paths-plan]]"
---

# `test-and-paths` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/config.py`
- `S04` `M` `src/vaultspec_rag/config.py`
- `S02` `M` `src/vaultspec_rag/cli.py`
- `S03` `M` `src/vaultspec_rag/store.py`
- `S03` `M` `src/vaultspec_rag/indexer.py`
- `S05` `A` `src/vaultspec_rag/synthetic.py`
- `S05` `A` `src/vaultspec_rag/tests/corpus.py`
- `S06` `M` `src/vaultspec_rag/tests/conftest.py`
- `S06` `M` `src/vaultspec_rag/tests/integration/conftest.py`
- `S08` `M` `.gitignore`
- `S07` `verify:` `Retained test-and-paths-exec grep sweeps zero stale references in src` -> `pass`

## Notes

- `S01` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Centralized env/settings implementation in historical config monolith. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S04` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Centralized env/settings implementation in historical config monolith. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S02` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Added path CLI overrides in monolith. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S03` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Config-based store/indexer paths. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S05` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Canonical generator created synthetic.py; tests/corpus.py historical re-export; do not claim only corpus.py owns generator. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S06` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Fixture migrations; static corpus deletion visible full commit but not new A/M scope. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S08` Historical operation attributed from Git commit e9a90a624da92fdf2f09ddd65e022645b90ed2a9. Ignore mutation proven; dual-channel validation retained prose only. Historical source paths may predate package extraction; no human acceptance, full test execution, or unretained pass is inferred.
- `S07` Narrow historical observation from 2026-04-04-test-and-paths-exec Tests and Description: zero stale references in src and bare production os.environ calls eliminated. Full original sweep argv and exhaustive environment/path taxonomy are not retained; no fresh audit or complete compound acceptance is inferred.
