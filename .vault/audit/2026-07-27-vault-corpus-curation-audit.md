---
tags:
  - '#audit'
  - '#vault-corpus-curation'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:fe18ccc960303fb78a9e6775329fdf26c983441dd9667df7c038f9612a47f136'
related:
  - '[[2026-07-25-adr-plan-coverage-triage-audit]]'
  - '[[2026-07-26-adr-plan-coverage-triage-corpus-reconciliation-audit]]'
---

# `vault-corpus-curation` audit: `Warning remediation`

## Scope

Reconciled the complete vault corpus after the canonical check reported 972 warnings: feature integrity, execution mapping, required body sections, and plan grounding. The review also checked ADR status topology, selected decision-to-code implementations, and lifecycle-document boundaries. Semantic RAG service evidence was unavailable because the service was not running and the installed Torch build was CPU-only; direct whole-document reads and targeted source confirmation supplied the findings below.

## Findings

### Warning remediation | low | Canonical mechanics and feature indexes repaired

`vault check all --fix` refreshed the stale modified stamp on `2026-06-01-module-split-adr`. The owning feature-index verb regenerated the stale or missing indexes for `adr-plan-coverage-triage`, `index-lifecycle-consolidation`, `large-index-resilience`, and `mcp-project-root-contract`. Status encoding is clean: 121 ADRs have canonical H1 statuses and all six formal supersession relationships are reciprocal.

### Warning remediation | high | Historical documents lack required sections

The body-sections check reports 946 warnings. These are historical ADR, research, audit, plan, and execution records that lack required template sections or have empty mandatory content. The missing material cannot be safely synthesized from current code or copied from another document without risking invented evidence, a changed decision, or a forked fact.

### Warning remediation | medium | Execution mapping has ten canonical-identifier false positives and seven historical records

Ten records retain a composite display identifier even though their exact checked plan rows exist: the sparse-search-latency records for S16 and S18 through S24, and the operability-hardening records for S03 and S16. The checker requires canonical bare `S##` values, but the CLI exposes no owning relink mutator and protects `step_id` as machine-filled data. One sparse-search-latency record targets genuinely retired S09. Six cli-service-operability-hardening records document prose-era waves with no corresponding live Step rows. Hand-editing any of these records would violate the vault ownership contract.

### Warning remediation | medium | Five plans lack recorded research grounding

The schema check reports no related research record for `2026-06-13-server-first-default-plan`, `2026-07-22-code-stands-alone-boundary-plan`, `2026-07-24-operator-feedback-hardening-plan`, `2026-07-25-archive-restore-contract-plan`, and `2026-07-25-service-release-compatibility-plan`. This is not safe to repair by adding an unrelated link; each plan needs verified lifecycle evidence or an explicit historical exception.

### Warning remediation | high | Accepted ADRs contain unresolved topology and content conflicts

The inventory found an unmodelled MCP dependency change between `2026-06-10-install-mcp-dependency-fix-adr`, `2026-06-18-mcp-service-client-adr`, and `2026-06-30-mcp-optional-dependency-adr`; a CLI/MCP parity conflict among the service-observability, service-operability, and mcp-search-scope ADRs; a fragmented duplicate GPU-performance decision cluster; two shipped records still marked proposed; and a stdio-lifetime/watchdog-convergence successor ambiguity. These require an author-selected amendment, ratification, deprecation, or supersession path.

### Warning remediation | high | The CUDA ceiling decision contradicts live implementation

`2026-07-24-index-throughput-adr` states that the ceiling counts reserved memory, while `2026-07-23-document-chunk-bounding-adr` governs allocated high-water enforcement with reserved memory diagnostic only. `memory_probe.py` implements the latter. This is a decision-record contradiction, not a code defect, and requires ADR amendment approval.

### Warning remediation | medium | Search-index lifecycle records contain one safe-boundary candidate and one forked fact

`2026-07-21-search-index-availability-adr` restates evidence already homed in its related research and reference records; the decision scope can be retained while operational evidence is replaced with a stem pointer. The related research also carries settled implementation language that the accepted ADR owns. Separately, the code-review audit describes a six-request harness while the ADR, reference, and final audit specify five parties; that contradictory fact requires author judgment before either history is changed.

## Recommendations

- Keep the completed CLI-owned mechanical repairs and re-run the feature check after any later vault mutation.
- Add an owning execution-record relink and retirement verb, then convert the ten composite identifiers to their verified canonical Step IDs and formally classify the seven historical records.
- Establish an evidence-recovery review for the 946 missing required sections. Author only content recoverable from the record's cited source or explicitly mark legacy records under an approved policy; do not generate filler.
- For each of the five ungrounded plans, confirm the appropriate research artifact before adding a related edge. Where none exists, create a research record through the research workflow rather than retrofitting a decision.
- Obtain author decisions for the ADR topology conflicts, the two proposed-but-shipped records, the CUDA ceiling contradiction, and the five-versus-six search harness fact. Apply the selected amendments or supersession changes with the ADR owning verbs.
- After approval, perform the identified content-preserving search-index lifecycle cleanup using the vault body-edit verb, then re-read the related research, reference, ADR, and audits to verify that no fact lost its single home.
