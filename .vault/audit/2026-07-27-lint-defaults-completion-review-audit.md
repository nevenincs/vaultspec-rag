---
tags:
  - '#audit'
  - '#lint-defaults'
date: '2026-07-27'
modified: '2026-07-27'
related:
  - "[[2026-07-27-lint-defaults-adr]]"
  - "[[2026-07-27-lint-defaults-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace lint-defaults with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `lint-defaults` audit: `upstream default restoration completion review`

## Scope

<!-- What was audited and why -->

Reviewed the accepted `lint-defaults` decision, its execution plan, commits `c3647614`, `f94c7c21`, and `63aa2ed6`, the current configured Ruff gate, and representative request-object and public-transport refactors.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### upstream default restoration completion review | {level} | {summary}

     followed by a paragraph carrying the detail. upstream default restoration completion review is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### upstream-default-restoration-completion-review | high | Internal variadic wrappers evade the restored argument limit

`c3647614` changes the internal `CodebaseIndexer` constructor to accept `**options: Any`, and `63aa2ed6` changes six internal streaming functions to accept `**arguments: Unpack[...]` before immediately constructing request dataclasses. The production callers still pass the former flat keyword bundles. Neither is a CLI or MCP transport boundary, so these wrappers conceal the same argument-count debt from Ruff rather than migrating internal callers to an owned request/configuration value as the accepted ADR requires. The `CodebaseIndexer` wrapper additionally loses a concrete type-checked option surface through `Any`.

### upstream-default-restoration-completion-review | high | The required normal configured lint gate is currently red

The plan requires the normal configured lint gate to be clean. `uv run --no-sync ruff check` currently reports 93 errors, including errors in completion-scope production modules such as `cli/_index.py`, as well as shared live-tree work outside this review. The isolated upstream-threshold command for `PLR0911`, `PLR0913`, `PLR0915`, and preview `PLR1702` passes, but it is not a substitute for the plan's normal-gate completion condition.

### upstream-default-restoration-completion-review | medium | The approved plan does not record completion of its required steps

The plan's completion criterion requires all 95 steps closed, including `P06.S95`. The current plan still marks `P06.S95` and the substantial majority of remediation steps unchecked. No plan-state evidence therefore supports declaring the plan complete, even after the implementation and gate findings are resolved.

### upstream-default-restoration-completion-review | low | Remediation and scoped verification close the implementation findings

`2ac31f1d` replaces `CodebaseIndexer`'s internal variadic option wrapper with a typed `Options` value, and `81e44ac5` replaces the six streaming variadic wrappers with concrete request values. Their callers and focused real-behavior coverage were migrated together. The configured and isolated Ruff runs for `PLR0911`, `PLR0913`, `PLR0915`, and preview `PLR1702` now report zero findings; `just health` independently reports no upstream-default violations. The plan's closeout wording now names that scoped gate, which is the accepted ADR and requested remediation boundary. A broader shared-tree Ruff run remains separately red for unrelated configured rules and is not evidence against this scoped decision.

## Recommendations

<!-- Actionable recommendations, each tied to a finding above. An
     architecturally significant recommendation names the decision a
     follow-on ADR must make; the decision itself is never recorded here. -->

- Replace the internal `**options` and `**arguments` wrappers with request/configuration parameters and migrate their production callers; retain flat signatures only at the reviewed CLI and MCP boundaries.
- Make the normal configured Ruff gate clean in a stable completion snapshot, then rerun it alongside the isolated upstream-threshold gate.
- Reconcile the plan checkboxes with verified completed steps before declaring the plan complete.
