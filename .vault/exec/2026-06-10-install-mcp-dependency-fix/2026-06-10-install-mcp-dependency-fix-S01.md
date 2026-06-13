---
tags:
  - '#exec'
  - '#install-mcp-dependency-fix'
date: '2026-06-10'
modified: '2026-06-10'
step_id: 'S01'
related:
  - "[[2026-06-10-install-mcp-dependency-fix-plan]]"
---

# Promote mcp to core dependencies, collapse the mcp extra to a deprecated no-op alias kept for backward-compat, and drop the duplicate mcp from the dev extra and dev dependency-group

## Scope

- `pyproject.toml`

## Description

- Add `mcp>=1.26.0` to the core `dependencies` array in `pyproject.toml`.
- Collapse the `mcp` optional-dependency extra to a deprecated no-op alias
  (`mcp = []`) with a comment noting it is retained only for backward-compat.
- Remove the duplicate `mcp` entry from the `dev` extra and the `dev`
  dependency-group so the core array is the single source of truth.

## Outcome

Implemented and shipped out-of-band in commit `4e4af36`
(`fix(packaging): declare mcp as a core dependency (#182)`) and released as
vaultspec-rag `0.2.19`. Verified against the working tree: `mcp>=1.26.0` is
present in core `dependencies`; the `mcp` extra is the documented no-op alias;
neither the `dev` extra nor the `dev` dependency-group lists `mcp`. The
regression guard added in `S03` passes, confirming the metadata declares `mcp`
as a core requirement.

## Notes

This Step's code change landed before this execution trail was committed; the
Step Record documents the delivered change rather than re-applying it. No
further code edit was required.
