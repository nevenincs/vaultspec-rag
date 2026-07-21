---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace service-job-control with a kebab-case feature tag, e.g. #foo-bar.
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

# `service-job-control` audit: `W01.P02.S04 canonical resources`

## Scope

Read-only review of the authoritative `W01.P02.S04` commit, including the complete
`jobs.py` module, the Step Record, accepted grounding documents, legacy registry
behavior, and current route and CLI consumers.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### W01.P02.S04 canonical resources | {level} | {summary}

     followed by a paragraph carrying the detail. W01.P02.S04 canonical resources is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

No critical, high, medium, or low findings were identified. The canonical vocabularies
match the architecture, terminal classification is complete, and the frozen slotted
resource types cover specifications, capabilities, attempt lineage, timestamps,
progress, runtime, and execution-resource ownership.

Revision and attempt numbers reject invalid non-positive values. Serialization exposes
the exact identifier, revision, desired and observed states, flattened attempt lineage,
control timestamps, capabilities, runtime, and resources. `force_killable` safely
defaults to false, and structured command outcomes use one consistent envelope.

The change is additive: legacy aliases and registry behavior remain unchanged, preserving
existing route and CLI dictionary consumers. No GPU, storage, watcher, HTTP, CLI,
persistence, or state-transition behavior was introduced prematurely.

Ruff, ty, BasedPyright, the 34-test jobs unit suite, and `git diff --check` passed. A
longer registry integration run was stopped because concurrently incomplete managed-log
changes affected shared service imports; this infrastructure interference produced no
confirmed S04 defect.

Status: **PASS**. There are no critical or high findings.

## Recommendations

Keep later manager Steps as the sole authority that constructs state-compatible
specifications, capabilities, timestamps, and lineage. The state-authority verification
Phase should directly test every serialized field and invalid lineage combination.
