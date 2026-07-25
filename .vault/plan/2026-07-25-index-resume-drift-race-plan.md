---
tags:
  - '#plan'
  - '#index-resume-drift-race'
date: '2026-07-25'
modified: '2026-07-25'
tier: L3
related:
  - '[[2026-07-25-index-resume-drift-race-adr]]'
  - '[[2026-07-25-index-drift-circuit-accounting-adr]]'
  - '[[2026-07-25-document-index-drift-parity-adr]]'
  - '[[2026-07-25-index-resume-drift-race-research]]'
  - '[[2026-07-21-large-index-resilience-adr]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #plan) and one feature tag.
     Replace index-resume-drift-race with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     tier is mandatory for new plans. Allowed: L1, L2, L3, L4.
     L1 = Steps only. L2 = Phases above Steps. L3 = Waves above
     Phases above Steps. L4 = Epic above Waves above Phases above
     Steps; PM association required. Pre-existing plans without this
     field default to L2.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'. The related field
     carries the AUTHORIZING documents (ADR, research, reference, prior
     plan) for every Step in this plan; Steps inherit this chain;
     per-row reference footers do not exist.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- HIERARCHY AND TIERS:
     Epic > Wave > Phase > Step. Step is the canonical leaf-row
     noun. Execution Record artifact: <Step Record>.
     Tier is declared in frontmatter as tier: L1/L2/L3/L4
     (mandatory for new plans; pre-existing plans without the
     field default to L2 and the writer adds the field on first
     edit). The tier selects containers:
       L1 = Steps only.
       L2 = Phases above Steps.
       L3 = Waves above Phases above Steps.
       L4 = Epic above Waves above Phases above Steps; MUST declare
            a project-management association in the Epic intent
            block prose.
     Selection is by complexity criteria, not container counting.
     Writer never invents containers to qualify a tier. -->

<!-- IDENTIFIERS AND ROW CONTRACT:
     S##, P##, W## are flat, per-document, append-only, immutable.
     Promotion adds containers without renumbering. Gaps are not
     reused.
     Display paths are computed from current grouping:
       Step path:    L1 S##   L2 P##.S##   L3/L4 W##.P##.S##
       Phase heading:        L2 P##       L3/L4 W##.P##
       Wave heading:                      L3/L4 W##
     Row format:
       - [ ] `<display-path>` - imperative-verb action; `path/to/file`.
     Two-state checkboxes only ([ ] open, [x] closed). No per-row
     reference footers; wiki-links and markdown links are forbidden
     in plan body. Authorizing documents go in the plan's `related:`
     frontmatter once.
     ASCII spaced hyphens everywhere; em-dash (U+2014) and en-dash
     (U+2013) are forbidden. Step rows within a Phase are
     contiguous. -->

<!-- NO COMPRESSION:
     N self-similar actions = N rows. Never collapse into "for each
     X, do Y" / "across all callers, do Z" / "in every module,
     replace W". The rule applies at every tier including L1. -->

<!-- VAULTSPEC-CORE VAULT PLAN CLI:
     The `vaultspec-core vault plan` CLI is the canonical surface for
     structural manipulation of this plan document. Writers and
     executors MUST use `vaultspec-core vault plan step add/insert/move/
     remove/check/uncheck/toggle/edit`,
     `vaultspec-core vault plan phase add/move/remove/edit`,
     `vaultspec-core vault plan wave add/move/remove/edit`,
     `vaultspec-core vault plan epic intent`, and
     `vaultspec-core vault plan tier promote/demote` for every
     identifier-affecting change rather than hand-editing the row
     grammar. Hand edits are tolerated by the parser but flagged by
     `vaultspec-core vault plan check`; canonical-identifier preservation is
     guaranteed only when the CLI performs the mutation. Run
     `vaultspec-core vault plan --help` for the full subcommand
     surface. -->

# `index-resume-drift-race` plan

## Wave `W01` - Seam the codebase indexer

Extract the responsibility clusters that one 3601-line class currently holds, behaviour-preserving, with the existing suite as the only oracle. Extraction runs ahead of the fix so the drift owner has somewhere to live that is not a seventh concern in the monolith.

<!-- One-line headline summary plan. -->

### Phase `W01.P01` - Establish the extraction baseline

Fix the behavioural oracle and prove the seams are not carrying duplicate implementations across.

- [ ] `W01.P01.S01` - Capture the behavioural baseline: run the full suite and record the passing count and the per-module test inventory that the extractions must preserve; `src/vaultspec_rag/tests/`.
- [ ] `W01.P01.S02` - Sweep the indexer for duplicate behaviour with vaultspec-rag semantic search before any extraction, recording each duplicate pair so extraction collapses it rather than carrying both across the seam; `src/vaultspec_rag/indexer/`.
- [ ] `W01.P01.S15` - Cover the drift-detection predicate with direct tests before it moves across a seam, since it currently has no test of its own and only its remedy is exercised; `src/vaultspec_rag/indexer/_run_checkpoint.py`.

### Phase `W01.P02` - Extract the collaborators

One extraction per responsibility cluster, each landing green before the next begins.

- [ ] `W01.P02.S03` - Extract discovery and admission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S04` - Extract chunk production and submission into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S05` - Extract generation and ledger lifecycle into its own collaborator, grounding first with vaultspec-rag semantic search and citing what it returned; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W01.P02.S06` - Extract drift ownership into its own collaborator that holds the drop-points-then-remove-units ordering as a property of the type; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

## Wave `W02` - Give drift a single owner and close the window

Turn the ledger collision into a distinguishable signal and let the drift owner supersede and re-record the racing path, so detection and remedy reason over the same evidence at the same instant.

### Phase `W02.P03` - Make the collision legible

Distinguish a racing path from a genuine invariant breach at the type level.

- [ ] `W02.P03.S07` - Give the indexed-path upsert collision its own exception type so a racing path is distinguishable from a genuine invariant breach; `src/vaultspec_rag/indexer/_run_ledger.py`.
- [ ] `W02.P03.S08` - Add the cheap pre-record drift re-check that keeps the common case off the signal path entirely; `src/vaultspec_rag/indexer/_run_checkpoint.py`.

### Phase `W02.P04` - Supersede and re-record

Remedy the drift through its owner, bounded, with deferral as the visible fallback.

- [ ] `W02.P04.S09` - Route the drift signal to the drift owner so it supersedes the racing path and the run re-records it instead of aborting; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `W02.P04.S10` - Bound the per-path retry and defer on exhaustion, emitting a warning that names the path and the exhausted budget; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

## Wave `W03` - Accounting, gate, and verification

Stop the breaker reacting to edit rate, restart the module-length ratchet the tooling already documents, and verify the whole change against a live service.

### Phase `W03.P05` - Circuit accounting and the ratchet

Count faults only, and turn the advisory length gate into a failing one.

- [ ] `W03.P05.S11` - Count faults only in the circuit breaker and record drift outcomes in their own counter reported alongside job state; `src/vaultspec_rag/indexer/_run_policy.py`.
- [ ] `W03.P05.S12` - Turn the module-length gate from advisory to failing at a threshold the post-seam tree actually meets, and record the full offender census in the same change so the remaining ratchet is visible rather than implied; `tools/module_length.py`.

### Phase `W03.P06` - Verify against a live service

Prove the guard still fires, the remedy works on a genuinely moving tree, and the degraded state clears.

- [ ] `W03.P06.S13` - Prove the upsert guard bidirectionally: permit the forbidden write, watch the test fail on its own assertion, restore, watch it pass, and record both directions; `src/vaultspec_rag/tests/`.
- [ ] `W03.P06.S14` - Verify on a live service against a genuinely moving tree that a racing path is superseded, the run completes, and the degraded state clears; `src/vaultspec_rag/tests/integration/`.

## Description

<!-- Briefly describe the proposed work. Reference `{adr}`s,
`{research}`, `{reference}`. Supporting documentation must be read prior to
writing the plan document. A plan may execute one ADR or a cluster; when
several feed it, state here which Wave or Phase each ADR governs. -->

## Steps

<!-- The plan's tier (declared in frontmatter as `tier: L1`, `L2`, `L3`, or
`L4`) determines the structure under this section:

- `L1`: a flat list of Step rows (no Phase, Wave, or Epic).
- `L2`: one or more `### Phase` blocks each containing Step rows.
- `L3`: one or more `## Wave` blocks each containing Phase blocks.
- `L4`: a `## Epic intent` block, followed by Wave blocks. -->

<!-- Replace this scaffold with the tier-appropriate structure for your plan.
Format examples for each block type are embedded below as commented
templates. -->

<!-- IMPORTANT: This document must be updated between execution runs to
     track progress. -->

<!-- PHASE BLOCK FORMAT (L2, L3, L4):
     ### Phase `P02` - rewrite the writer-agent contract

     One sentence stating what this Phase delivers.

     - [ ] `P02.S01` - imperative-verb action; `path/to/file`.
     - [ ] `P02.S02` - imperative-verb action; `path/to/file`.

     At L3/L4 the Phase heading uses the ancestor-aware path
     (### Phase `W01.P02` - ...). The intent sentence is mandatory. -->

<!-- WAVE BLOCK FORMAT (L3, L4):
     ## Wave `W01` - language-only convention rollout

     One paragraph stating what this Wave delivers, which downstream
     Wave depends on it, and which authorizing documents back it.

     ### Phase `W01.P01` - ...
     ### Phase `W01.P02` - ...

     The Wave intent paragraph is mandatory. -->

<!-- EPIC INTENT BLOCK FORMAT (L4 only):
     ## Epic intent

     One paragraph stating the strategic goal, the external project-
     management association (milestone name, project board identifier,
     roadmap entry), the timeline horizon, and the teams or agents
     involved.

     ## Wave `W01` - ...
     ## Wave `W02` - ...

     The ## Epic intent block is mandatory at L4 and absent at L1, L2,
     L3. The plan title (the level-one # heading at the top of the
     document) is the Epic title; no separate Epic heading is emitted. -->

## Parallelization

<!-- State which Steps, Phases, or Waves can be executed in parallel and
which carry hard ordering. At `L1` and `L2`, parallelism is decided
per-Step or per-Phase. At `L3` and `L4`, Waves are sequenced by
default (one Wave must land before the next can begin); Phases
within a single Wave may be parallelized when they share no hard
interdependency. -->

## Verification

<!-- State the mission success criteria for this plan. Each criterion
should be a verifiable check (test passes, surface conforms,
reviewer signs off) rather than a free-form assertion.

The plan is complete when every Step in the plan is closed
(`- [x]`). At `L4`, the Epic-completion check additionally requires
the declared project-management association to report the Epic
complete.

For tier-specific verification cadence, see the authorizing
documents linked in the `related:` frontmatter. -->
