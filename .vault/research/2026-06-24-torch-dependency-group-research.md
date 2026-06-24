---
tags:
  - '#research'
  - '#torch-dependency-group'
date: '2026-06-24'
modified: '2026-06-24'
related: []
---



# `torch-dependency-group` research: `placing the managed torch direct-dependency in a dependency group`

GitHub issue **#186**: `vaultspec-rag install` patches the *consuming* project's pyproject to
pin a CUDA torch, and it adds `torch` to `[project].dependencies` - the published runtime
surface. When rag is used as dev-only tooling (e.g. inside vaultspec-core), this leaks `torch`
into the consuming package's published `Requires-Dist`, forcing a downstream `pip install` to
pull torch (and, since the uv cu130 source pin is not published, an unpinned/CPU torch at
that). The issue asks for an option to place the managed torch direct-dependency in a PEP 735
`[dependency-groups]` group instead, which uv still applies source pins to but which is not
published. This research grounds the change in the actual install code and weighs the design.
It feeds an ADR. No implementation here.

## Findings

### F1 - The write target is hard-coded in exactly one helper; detection already understands groups

The torch-patch logic lives in `src/vaultspec_rag/torch_config/`, orchestrated by
`_torch_flow.py` and exposed via flags in the install CLI. It uses `tomlkit` (round-trip
preserving) and writes through the shared atomic-write helper. Crucially, the decision of
*where* the managed torch dep is written is centralised in a single helper
(`_project_dependencies`) that creates and hard-returns the `[project].dependencies` location.
Detection is already broader than the write: `has_direct_torch_dep` / `_iter_dep_lists` scans
every dependency surface *including* `[dependency-groups]`. So the asymmetry is narrow: rag can
already *detect* torch in a group, it just always *writes* to `[project].dependencies`.

### F2 - WHY `[project].dependencies` was chosen - and that it has no ADR of record

The only recorded rationale is a code docstring: uv applies `[tool.uv.sources]` pins only to
*direct* dependencies, and torch is otherwise transitive
(`vaultspec-rag` -> `transformers` -> `torch`), so it must be declared directly for the cu130
index pin to take effect. `[project].dependencies` was chosen as the universal direct surface
with no recorded deliberation against `[dependency-groups]`, and no consideration of the
published-`Requires-Dist` leak this issue raises. The governing install-cuda ADR documents
only the `[[tool.uv.index]]` + `[tool.uv.sources]` block; the direct-dependency promotion and
its `managed-torch-direct-dependency` marker were added *after* that ADR and have no ADR of
record. PEP 735 dependency groups are not published in `Requires-Dist`, and uv does apply
source pins to direct deps declared in a group - so the group placement satisfies the same uv
constraint without the leak.

### F3 - The reversal path is marker-gated and assumes the project surface

Uninstall removes the cu130 index/sources block by canonical-shape match, and removes the
direct torch dep only when the `managed-torch-direct-dependency` marker is set - then it removes
the entry from the *same* hard-coded `[project].dependencies` helper. The marker is a bare
boolean. So today uninstall structurally assumes the dep lives in the project surface. This is
the load-bearing correctness concern for the change (see F5).

### F4 - The report plumbing already carries a location, so no schema churn

The direct-dep operation returns a structured report that already includes a `location` field
(found/written location), and that location is already threaded onto the install/uninstall
report models and serialised to JSON. So recording and surfacing *which* surface the managed
dep landed in needs no new report schema - only the write helper and the marker need to learn
the location.

### F5 - The marker must become location-bearing, with legacy back-compat

Because uninstall removes from wherever the marker says rag wrote, supporting a group target
means the marker can no longer be a bare boolean - it must record the location (e.g.
`managed-torch-direct-dependency = "[dependency-groups].dev"`). Existing installs carry the
boolean `true`; uninstall must treat `true` as "the legacy `[project].dependencies` location"
and a non-empty string as the explicit recorded location. Missing this would orphan the entry
on uninstall and break the symmetric install/uninstall mirror the install design guarantees.

### F6 - Idempotency, migration, and uv-sync gating edge cases

- Re-runs are safe: `has_direct_torch_dep` finds torch anywhere (including the chosen group)
  and no-ops. But a re-run with a *different* target than the original finds the dep in the old
  location and no-ops without migrating it - so migration between surfaces is a deliberate
  decision, not automatic.
- The marker is only set when rag actually appends the dep, never when it reports "already
  present" - so a user's pre-declared torch (in project deps or a group) is left untouched and
  not marker-owned; this invariant must hold for the group path too.
- uv applies the source pin to a group dep only when that group is enabled for the resolve
  (`uv sync --group <name>` or a configured default group); a group-targeted install should warn
  the operator so the cu130 pin is not silently inert.

## Options weighed (for the ADR)

- **Selector surface.** Option A: a `--torch-group NAME` install flag (explicit, discoverable,
  matches existing `--torch-config` flags). Option B: a `[tool.vaultspec-rag]` setting read from
  the consuming pyproject (persistent across re-runs, but there is no existing reader for
  vaultspec-rag settings beyond the marker, so it adds a read path). A flag is the lighter v1;
  a persisted setting could follow. Default with neither remains `[project].dependencies`
  (back-compat).
- **Marker shape.** Promote the boolean marker to a location-bearing value, with `true` read as
  the legacy project-deps location. Required for correct uninstall (F5).
- **Migration policy.** Either explicitly out of scope for v1 (a re-run with a different target
  warns and no-ops, leaving the original placement), or a follow-up that relocates on an
  explicit re-install. Recommend out-of-scope-with-a-warning for v1 to keep the change tight.
- **uv-sync gating.** Warn when a group target is selected that the group must be enabled for
  the pin to apply; do not silently leave an inert pin.

## Open questions for the ADR

- Confirm the selector (flag vs persisted `[tool.vaultspec-rag]` setting vs both) and the
  default group name when `--torch-group` is given without a value (e.g. `dev`).
- Confirm the marker's new shape and the legacy-`true` read mapping.
- Confirm migration is out of scope for v1 (warn-and-no-op on a changed target) or in scope.
- Confirm the ADR also retroactively records the original `[project].dependencies` rationale,
  since the direct-dep promotion has no ADR of record today.
