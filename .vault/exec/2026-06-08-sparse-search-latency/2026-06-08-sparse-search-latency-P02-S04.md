---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
step_id: 'S04'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace {feature} with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.
     step_id is the originating Step's canonical identifier, e.g. S01.

     Related: use wiki-links as '[[YYYY-MM-DD-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add frontmatter fields
     outside the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path. -->

# `sparse-search-latency` P02 plan: S04

Phase P02

## Description

Attempted to translate include_paths and exclude_paths globs to Regex strings inside `src/vaultspec_rag/search/_searcher.py`.

## Outcome

Failed.

## Notes

The ADR authorized translating globs to `MatchPattern` filters for Qdrant. However, after investigation, Qdrant does not natively support a `MatchPattern` or regular expression matching capability on payload fields in the `qdrant-client` 1.18.0 library. The `MatchPattern` type does not exist, and attempting to use it causes Python type checker and Pydantic validation errors. I have aborted the code changes for Phase P02.
