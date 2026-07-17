---
tags:
  - '#audit'
  - '#mcp-launch-hygiene'
date: '2026-07-17'
modified: '2026-07-17'
related: []
---

# `mcp-launch-hygiene` audit: `review of the issue-231 launch-hygiene fixes`

## Scope

Review of the fix for issue 231 (tool-spec token, placement-aware mcp
extra, seed-refresh pinning, docs remediation) against the ADR and core's
static-launch contract. Verdict: PASS, no critical or high findings.

## Findings

### remediation-text-releaks | medium | Failure warnings steered operators back to the bare uv add

The classifier and error branches hardcoded `uv add vaultspec-rag[mcp]` in
remediation text; after a group-placed add failed, following that advice
would re-leak the extra into runtime dependencies. RESOLVED: the exact
placement-aware command that ran is threaded into every warning, with a
test asserting the bare form never appears for group placements.

### pep503-name-matching | low | Placement detection missed normalized name spellings

`vaultspec_rag` / case variants in a dependency group false-missed (PEP
503 treats `-`/`_`/`.` and case as equivalent). RESOLVED: candidates are
normalized before matching; pinned by test.

### upgrade-wiring-untested | low | The upgrade-to-force seeding chain lacked an end-to-end test

The direct seeder test pinned the mechanism but not the
`install_run(upgrade=True)` wiring. RESOLVED: an end-to-end test writes a
stale exe-form seed and asserts the tokenized form after a real upgrade
run.

## Recommendations

Ship in the held release so tool-mode MCP works out of the box; core's
PR 224 lands independently.
