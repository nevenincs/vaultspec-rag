---
tags:
  - '#exec'
  - '#sparse-search-latency'
date: '2026-06-08'
step_id: 'S04'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---




# `sparse-search-latency` P02 plan: S04

Phase P02

## Description

Attempted to translate include_paths and exclude_paths globs to Regex strings inside `src/vaultspec_rag/search/_searcher.py`.

## Outcome

Failed.

## Notes

The ADR authorized translating globs to `MatchPattern` filters for Qdrant. However, after investigation, Qdrant does not natively support a `MatchPattern` or regular expression matching capability on payload fields in the `qdrant-client` 1.18.0 library. The `MatchPattern` type does not exist, and attempting to use it causes Python type checker and Pydantic validation errors. I have aborted the code changes for Phase P02.
