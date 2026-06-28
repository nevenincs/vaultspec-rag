---
tags:
  - '#plan'
  - '#rag-broker-affordances'
date: '2026-06-27'
modified: '2026-06-27'
tier: L2
related:
  - '[[2026-06-27-rag-broker-affordances-adr]]'
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
     Replace rag-broker-affordances with a kebab-case feature tag, e.g. #foo-bar.
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

# `rag-broker-affordances` plan

Make rag's single-machine service broker-friendly: an idempotent JSON `server start` and a STATUS_DIR-independent machine-global discovery pointer.

### Phase `P01` - idempotent server start with structured JSON outcomes

Reorder the idempotent check ahead of the guards and add a --json contract emitting one envelope per outcome (ADR D1, D2).

- [x] `P01.S01` - Refactor \_existing_service_running to return the running pid and port instead of printing, moving the human lines to the caller; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S02` - Reorder service_start so the idempotent already-running check precedes the port and machine guards; `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S03` - Add the --json option and emit one envelope per outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway, start_timeout); `src/vaultspec_rag/cli/_service_lifecycle.py`.
- [x] `P01.S04` - Unit-test the reorder and each --json outcome shape with an isolated temp status dir; `src/vaultspec_rag/tests/test_cli_server_start.py`.

### Phase `P02` - machine-global discovery pointer beside the lock

Add the machine-global pointer path and reader, write it on the daemon heartbeat, and clean it on shutdown (ADR D3, D4).

- [x] `P02.S05` - Add machine_discovery_path and a tolerant read_machine_discovery to the machine-lock module; `src/vaultspec_rag/_machine_lock.py`.
- [x] `P02.S06` - Write the discovery payload to the machine-global pointer on the daemon heartbeat tick and clean it on shutdown; `src/vaultspec_rag/server/_lifecycle.py`.
- [x] `P02.S07` - Unit-test the pointer path, the heartbeat write beside the lock, the shutdown cleanup, and the tolerant reader with an isolated temp storage dir; `src/vaultspec_rag/tests/test_machine_discovery.py`.

## Description

Deliver the two rag-side broker affordances the cross-project audit's handover recorded,
per the accepted ADR. Phase P01 makes `server start` broker-friendly in
`_service_lifecycle.py`: `_existing_service_running` is refactored to return the running
pid/port (the caller prints or JSON-emits), the idempotent check is reordered ahead of the
port and machine guards (so a healthy owned service is `already_running`/exit 0, not the
shadowed port-guard exit 1), and a `--json` option emits one `_emit_json` envelope per
outcome (already_running, started, port_in_use, machine_owned, daemon_breakaway,
start_timeout). Phase P02 adds a STATUS_DIR-independent discovery pointer: a
`machine_discovery_path()` + tolerant `read_machine_discovery()` in `_machine_lock.py`, the
daemon `_heartbeat_tick_sync` writing the versioned discovery payload to it beside the lock
(atomic `.tmp` + `os.replace`) and the shutdown hooks cleaning it. Both are additive
(human start output and the STATUS_DIR file are untouched) and consumer-optional; the
dashboard adopts them as follow-ups. Grounded in the `rag-broker-affordances` research and
ADR; closes the audit's C1 (exit-1 flattening, at the source) and C3 (STATUS_DIR-coupled
discovery) on the rag side.

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

P01 and P02 touch different files (`_service_lifecycle.py` vs `_machine_lock.py` +
`server/_lifecycle.py`) and are independent, but they share the managed-singleton test
isolation, so they are executed sequentially for a clean review. Within P01, S01 (the
return-refactor) precedes S02 (the reorder) and S03 (the --json branch), with S04 (tests)
last. Within P02, S05 (path + reader) precedes S06 (the daemon write), with S07 (tests)
last. The test steps (S04, S07) gate their phase's completion.

## Verification

The plan is complete when every Step is closed and these criteria hold:

- An already-running healthy owned service makes `server start` exit 0 with the
  `already_running` outcome (the reorder), never the port-guard exit 1 it produced before
  (unit test with an isolated temp status dir).
- `server start --json` emits exactly one `_emit_json` envelope on every exit path:
  `already_running`/`started` (ok, exit 0) and `port_in_use`/`machine_owned`/
  `daemon_breakaway`/`start_timeout` (ok:false, non-zero); the human (non-JSON) output is
  unchanged (unit tests).
- The genuine guard cases still fail: a foreign process holding the port and another
  service owning the machine each still exit non-zero (not mistaken for our service).
- `machine_discovery_path()` resolves beside the machine lock (STATUS_DIR-independent), and
  the daemon heartbeat writes the versioned discovery payload there; shutdown cleans it
  (unit tests with an isolated temp storage dir).
- `read_machine_discovery()` returns the payload when present and tolerates a missing/
  unreadable file as truthful absence, never raising (unit test).
- `just ci` (lint, basedpyright at zero, the unit suite) is green; `vaultspec-core vault check all` stays clean.
