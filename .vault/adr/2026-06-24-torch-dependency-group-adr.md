---
tags:
  - '#adr'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
related:
  - "[[2026-06-24-torch-dependency-group-research]]"
---



# `torch-dependency-group` adr: `optional dependency-group placement for the managed torch direct-dependency` | (**status:** `accepted`)

## Problem Statement

`vaultspec-rag install` declares the managed CUDA `torch` as a direct dependency in the
consuming project's `[project].dependencies` so uv applies the cu130 `[tool.uv.sources]` pin
(uv applies source pins only to *direct* deps, and torch is otherwise transitive). For a
project that uses rag as dev-only tooling (GitHub issue **#186**, e.g. vaultspec-core), that
leaks torch into the consuming package's published `Requires-Dist`, forcing every downstream
`pip install` to pull torch - and an unpinned/CPU torch at that, since the uv source pin is
not published. The research established that PEP 735 `[dependency-groups]` satisfy the same uv
direct-dep constraint without being published, that the install code's write target is
centralised in one helper while detection already understands groups, and that the reversal
path is marker-gated and assumes the project surface. This ADR decides an optional
dependency-group placement for the managed torch dep, and retroactively records the original
project-deps rationale (which has no ADR of record). Grounded in
`2026-06-24-torch-dependency-group-research`.

## Considerations

- Detection already scans `[dependency-groups]`; only the *write* target is hard-coded to
  `[project].dependencies` in a single helper (research F1). The change is therefore localised.
- The direct-dep promotion and its `managed-torch-direct-dependency` marker post-date the
  install-cuda ADR and have no ADR of record (F2); this ADR captures that rationale.
- Uninstall removes the managed dep from the marker-implied location, and the marker is a bare
  boolean assuming the project surface (F3) - so a group target requires the marker to record
  the location, with legacy back-compat (F5).
- The report model already carries a `location` field through to JSON (F4), so surfacing the
  chosen surface needs no schema churn.
- uv applies the source pin to a group dep only when that group is enabled for the resolve
  (F6), so a group target without an enabled group leaves an inert pin - the operator must be
  warned.

## Constraints

- Back-compat is mandatory: the default (no selector) must remain `[project].dependencies`, and
  existing installs carrying the boolean marker must uninstall correctly.
- Symmetric install/uninstall is a standing install-design guarantee: whatever surface install
  writes, uninstall must remove from exactly that surface and nowhere else.
- `tomlkit` round-trip preservation and the atomic-write discipline are existing invariants the
  change must keep.
- The selector must thread cleanly through the existing CLI -> install-run -> torch-flow ->
  ensure-direct-dep layers without breaking the idempotent re-run and the "never touch a
  user-declared torch" invariants.
- No frontier risk; uv, PEP 735, and tomlkit are mature and in-tree.

## Implementation

High-level; a plan sequences it.

**D1 - An optional group target, default unchanged.** Add a `--torch-group NAME` install flag
selecting a PEP 735 `[dependency-groups].<NAME>` surface for the managed torch direct-dependency
(default group name `dev` when the flag is given without a value). With no flag, the managed dep
continues to land in `[project].dependencies` exactly as today. (Resolves research open question
1; a persisted `[tool.vaultspec-rag]` setting is deferred as a possible follow-up.)

**D2 - A parameterised write-target helper.** Introduce a group-target helper alongside the
existing project-deps helper, creating the `[dependency-groups]` table and the named array when
absent and returning the location string `[dependency-groups].<NAME>`. The existing
`location`-bearing report carries it through to JSON with no schema change.

**D3 - A location-bearing marker, with legacy back-compat.** Promote
`managed-torch-direct-dependency` from a bare boolean to a value that records the written
location; read a legacy `true` as the `[project].dependencies` location so existing installs
uninstall correctly. Uninstall removes the managed dep from the marker-recorded surface only.
(Resolves research open question 2.)

**D4 - Migration out of scope for v1, with a warning.** A re-run with a different `--torch-group`
than the existing managed placement does not silently migrate; it warns that torch is already
managed in the recorded location and no-ops, leaving the original placement. Relocation is a
deliberate follow-up, not an implicit side effect. The "never touch a user-declared (unmarked)
torch" invariant is preserved for the group path. (Resolves research open question 3.)

**D5 - Warn when the pin would be inert.** When a group target is selected, the install output
warns that the group must be enabled for the resolve (`uv sync --group <NAME>` or a configured
default group) for the cu130 pin to apply, so a group-placed dep is never a silently inert pin.

**D6 - Tests, no mocks.** Tests against real tomlkit documents assert: a group target writes
`torch` under `[dependency-groups].<NAME>` and not `[project].dependencies`, with the cu130
index/sources block still written; the marker records the group location; uninstall removes the
group entry and a legacy-`true` marker still removes from project deps; the default path is
unchanged; and a user-declared torch in a group is left untouched.

## Rationale

The group placement is the minimal, uv-correct way to keep torch out of a dev-only consumer's
published metadata: PEP 735 groups are unpublished yet still receive uv source pins, so the
cu130 constraint that forced direct-dep placement is satisfied without the `Requires-Dist`
leak. The change is small because the write target is already centralised and the report
already carries a location; the real care is the marker (D3) and uninstall symmetry, which the
research flagged as the load-bearing correctness risk. Keeping the default on
`[project].dependencies` (D1) and migration out of scope (D4) bounds the blast radius. D6's
no-mock tomlkit tests follow the existing install-test pattern.

## Consequences

- Gains: dev-only consumers can adopt rag's managed torch without leaking torch into their
  published runtime requirements; the long-missing rationale for the direct-dep promotion is
  recorded; the report already surfaces which surface was used.
- Costs and risks: the marker shape changes - the migration from boolean to location-bearing
  must be perfectly back-compatible or existing installs orphan their torch dep on uninstall
  (the primary risk, covered by D3 and a dedicated test). A group-placed pin is inert unless the
  group is enabled, mitigated by the D5 warning but still an operator footgun.
- Pathways: a persisted `[tool.vaultspec-rag]` torch-group setting and an explicit relocation/
  migration command become natural follow-ups once the group target exists.

## Codification candidates

- **Rule slug:** `managed-dependency-marker-records-location`.
  **Rule:** When the installer can write a managed dependency to more than one pyproject
  surface, the ownership marker must record which surface was written (not a bare boolean), and
  uninstall must remove only from the marker-recorded surface, preserving symmetric
  install/uninstall and never touching a user-declared dependency.

  *(Candidate only - promoted after the constraint has held across at least one full execution
  cycle, per the codify discipline.)*
