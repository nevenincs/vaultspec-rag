---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace index-cuda-ceiling with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- PHASE SUMMARY:
     This file rolls up every <Step Record> belonging to one Phase
     of the originating plan. Each Step (S##) in the Phase produces
     one <Step Record> in `.vault/exec/`; this summary aggregates
     them, lists modified / created files across the Phase, and
     reports verification status. -->

# `index-cuda-ceiling` `P01` summary

<!-- Brief summary of overall progress across every Step in this Phase,
     followed by a list of files touched across the Phase, e.g.:
     - Modified: `{file1}`
     - Created: `{file2}` -->

All three Steps (`S01`-`S03`) complete. Documents encode on their own
sub-batch, decoupled from the vault and code knobs.

- Modified: `src/vaultspec_rag/config.py`
- Modified: `src/vaultspec_rag/indexer/_document_indexer.py`
- Modified: `src/vaultspec_rag/tests/test_config.py`

## Description

<!-- High-level description of work accomplished. -->

`embedding_document_encode_batch_size` (default 12, own env override) now
drives both document encode call sites, sized for window-bounded document
fragments (~2.7x the vault chunk's token volume) instead of falling through
to the vault sub-batch of 32. This retires the restart-fragile runtime env
workaround that had lowered the shared knob for every domain. An
independence test binds the decoupling in both directions: the document
default differs from vault/code, and its override perturbs neither sibling
knob.
