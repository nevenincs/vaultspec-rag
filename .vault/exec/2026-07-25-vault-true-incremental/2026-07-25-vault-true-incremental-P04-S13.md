---
tags:
  - '#exec'
  - '#vault-true-incremental'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S13'
related:
  - "[[2026-07-25-vault-true-incremental-plan]]"
---

# Prove the metadata-only guard bidirectionally: assert a tags-only edit updates payloads with zero encodes, route metadata changes into the re-embed branch, watch it fail, restore, watch it pass

## Scope

- `src/vaultspec_rag/tests/`

## Description

- Add `TestMetadataOnlyChangeSkipsTheGpu` to the same integration module.
- Assert a tags-only edit yields `payload_updated == 1` and `updated == 0`, that
  the stored vectors are byte-identical before and after, and that the new tag is
  actually present in the stored payload.
- Assert an untouched document's payload is left alone.
- Add a guard over a document that splits into six chunks, asserting the reported
  figure counts documents rather than chunks and that every chunk's payload was
  refreshed.
- Drive both red by mutation, restore, drive them green.

## Outcome

Proven able to fail, in one uninterrupted sequence. Routed metadata deltas into
the re-embed branch in `_classify_documents()` - adding them to the body set
instead of the metadata set - ran the guard alone, and watched it fail on its own
branch assertion: `a tags-only edit did not take the payload-only branch`,
`assert 0 == 1`, with `updated == 1` in the reported result confirming the
re-embed. Restored the routing; the guard passed again. No mutation was left on
disk.

## Notes

The guard caught a real defect in its own first run - in the test helper, not the
production code. The original helper appended the tag after the last list item in
the frontmatter, which is in `related:`, not `tags:`; both fields are YAML lists
with the same item prefix. The classification and the payload write were correct
throughout - a `related:` change is equally a metadata delta - but the assertion
that the payload actually gained the new *tag* failed, which is precisely the
assertion that had to be there. The helper is now anchored on the `tags:` key and
says why.

Asserting the payload content, not just the branch taken, is what made that
visible. A guard that only checked `payload_updated == 1` would have passed while
editing the wrong field.

The multi-chunk guard was added after the payload branch's reported figure turned
out to be a chunk count. It is proven able to fail the same way: restoring the
chunk count makes it fail with `reported 6 documents for one document of 6 chunks`. Every guard in this phase used single-chunk documents, where the two
numbers agree, which is exactly why none of them saw it.
