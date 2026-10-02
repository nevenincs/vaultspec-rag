---
tags:
  - '#exec'
  - '#jobs-tui'
date: '2026-07-27'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:4fb5b06b00dfc759eb10c8735bc6ad42615c1dc3503d21bf264ed00054f353f1'
related:
  - "[[2026-07-27-jobs-tui-plan]]"
---

# `jobs-tui` ledger

## Changes

- `S01` `M` `src/vaultspec_rag/jobs.py`
- `S02` `M` `src/vaultspec_rag/server/_routes_jobs.py`
- `S03` `A` `src/vaultspec_rag/tests/test_jobs_progress_rate.py`
- `S04` `M` `pyproject.toml`
- `S05` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S06` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S07` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S08` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S09` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S10` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S11` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S12` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S13` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S14` `A` `src/vaultspec_rag/cli/_jobs_tui.py`
- `S15` `M` `src/vaultspec_rag/cli/_service_jobs.py`
- `S16` `A` `src/vaultspec_rag/tests/test_cli_jobs_tui.py`
- `S17` `M` `docs/cli.md`
- `S18` `verify:` `Current canonical CPU lane just test-python` -> `pass`

## Notes

- `S01` Historical attribution: aef9446499fd32941d3d130133603fe9e6cbf50d estimate job completion from progress rate. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S02` Historical attribution: aef9446499fd32941d3d130133603fe9e6cbf50d estimate job completion from progress rate. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S03` Historical attribution: aef9446499fd32941d3d130133603fe9e6cbf50d estimate job completion from progress rate. Historical change attribution only, not complete Step acceptance or original gates PASS. Added real estimator tests; does not establish historical execution or every enumerated state passing.
- `S04` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S05` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S06` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S07` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S08` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S09` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S10` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S11` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S12` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S13` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S14` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S15` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S16` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS. Rendered/key-press tests added; retained jobs audit says passing tests missed real live defects. No full acceptance inferred.
- `S17` Historical attribution: 8e6de290ac41622cdf6098eea6e34b1479a37f28 replace the jobs watch loop with an interface. Historical change attribution only, not complete Step acceptance or original gates PASS.
- `S18` Genuine current root-owned configured CPU target completed5810passed8platform-specificskipszero warnings221.50s; exact artifact remediation-full-cpu-holder-fixed.log. This records an executed applicable test dimension only, not a historical gate run, all-marker pytest selection, lint/static results, GPU pass, commit delivery, or whole compound Step acceptance. Full GPU strict-Werror reveals connection lifecycle warnings under repair and final aggregate remains pending. Mechanical execution attribution does not erase these broader evidence limits.
