---
tags:
  - '#exec'
  - '#server-first-default'
date: '2026-06-13'
modified: '2026-06-13'
step_id: 'S23'
related:
  - "[[2026-06-13-server-first-default-plan]]"
---

# render the heterogeneous provisioning outcomes in the install report renderer including the torch sync-pending wording

## Scope

- `src/vaultspec_rag/cli/_render.py`

## Description

- Add a focused provisioning-outcome render path to the install report renderer
  in `src/vaultspec_rag/cli/_render.py`, called from `_render_install_report`
  after the existing torch lines and before the warnings.
- Render one bounded line per considered dependency through the shared sync
  vocabulary, with a flat step-label and action-phrase table so the renderer
  stays a single loop and the worst cyclomatic block does not regress.
- Surface the torch two-phase state honestly: a `created` / `updated` torch step
  carrying `sync_pending` reads as "configured, sync pending", kept distinct from
  a binary's terminal "downloaded" / "already present".
- Append each step's `detail` so a `skipped` step always carries its reason (e.g.
  the `--local-only` qdrant skip), keeping the view honest and actionable.

## Outcome

The renderer now emits a `Provisioning: <status>` summary line followed by an
indented, bounded per-dependency list. The render path reads the JSON-serialisable
`to_dict` view so the human and JSON reports describe exactly the same outcome,
and does not touch the unrelated jobs / status / logs / search rendering in the
file. The new helpers stay under the complexity baseline (gate green; the
pre-existing `_render_install_report` rank-C block did not regress). The honest
"configured, sync pending" wording is asserted by the integration renderer test
in S25.

## Notes

The complexity gate's baseline records `_render_install_report` as the worst
cyclomatic block at rank C, so the provisioning logic was kept out of that
function in small data-driven helpers rather than inlined, to avoid pushing the
block past C.
