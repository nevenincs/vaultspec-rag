---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S35'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Add unit tests for HTML stripping and the new extension behaviour (D13)

## Scope

- `src/vaultspec_rag/tests/test_html_strip.py`

## Description

Added `test_html_strip.py` (8 tests): `html_to_text` strips tags, drops script/style
bodies, decodes entities, produces block line-structure, and never raises on malformed
HTML; `_chunk_decoded` strips HTML when enabled and keeps markup when disabled; and the new
`.txt/.properties/.xsd` extensions chunk as text (D13).

## Outcome

8/8 pass; combined with the extension assertions in S32, the adjacent asks are fully
covered.

## Notes

No mocks; real HTMLParser + real splitter.
