---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace large-index-resilience with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S02 and 2026-07-21-large-index-resilience-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Define typed no-progress, memory-ceiling, circuit-open, and admission outcomes with shared remediation and ## Scope

- `src/vaultspec_rag/_job_errors.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define typed no-progress, memory-ceiling, circuit-open, and admission outcomes with shared remediation

## Scope

- `src/vaultspec_rag/_job_errors.py`

## Description

- Define one string-compatible typed vocabulary for legacy and resilience outcomes.
- Add a typed exception that preserves outcome identity through the existing text boundary.
- Recover exact canonical prefixes before applying backward-compatible free-text markers.
- Centralize actionable remediation for timeout, memory, circuit, profile, corpus, disk, and capacity outcomes.
- Keep the taxonomy import surface free of torch, Qdrant, service, and CLI dependencies.

## Outcome

Indexing policy and adapter work can now exchange stable typed safety outcomes without
breaking existing persisted text or string-based consumers. Every actionable refusal or
termination shares one service-domain remediation source.

## Notes

Production probes covered four legacy classifications and eight typed outcomes, remediation
parity, JSON serialization, and import lightness. Seven focused existing tests, Ruff, ty,
BasedPyright, formatting, and diff checks passed. Independent review returned PASS with no
findings.
