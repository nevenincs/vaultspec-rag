---
tags:
  - '#audit'
  - '#gpu-rag-stack'
date: 2026-03-07
---

# Round 9 Audit -- store.py (deep dive, post-fix verification)

**Auditor:** docs-researcher-2-2
**File:** `src/vaultspec_rag/store.py` (746 lines)
**Date:** 2026-03-07

______________________________________________________________________

## Check 1: Boolean Cache on `ensure_table` / `ensure_code_table`

### `ensure_table()` (lines 185-204)

```python
def ensure_table(self) -> None:
    if self._vault_ensured:
        return
    ...
    if self._client.collection_exists(self.TABLE_NAME):
        self._vault_ensured = True
        return
    self._ensure_collection(self.TABLE_NAME)
    ...payload indexes...
    self._vault_ensured = True
```

**Verdict: PASS.** The `self._vault_ensured` boolean (initialized `False` at line 141) is checked first, preventing `collection_exists` RPC on subsequent calls. It is set to `True` in both branches: existing collection (line 193) and newly created (line 204).

### `ensure_code_table()` (lines 206-230)

Same pattern with `self._code_ensured` (initialized `False` at line 142). Set `True` at lines 214 and 230.

**Verdict: PASS.** Identical correct pattern.

______________________________________________________________________

## Check 2: Payload Indexes

### `ensure_table()` (lines 198-203)

```python
for fname in ("doc_type", "feature", "date", "tags"):
    self._client.create_payload_index(
        collection_name=self.TABLE_NAME,
        field_name=fname,
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
```

All four fields indexed as KEYWORD. This is correct for `doc_type`, `feature`, and `tags` (string/list-of-string fields used with `MatchValue`/`MatchAny`).

### R9-m1: `date` payload index uses KEYWORD schema -- correct for `MatchValue` but limits range queries (Minor)

The `date` field is indexed as `KEYWORD`, which is correct for the current `MatchValue` exact-match filter (line 690). However, if date prefix/range filtering is ever needed (e.g., "all docs from 2026-02"), a `KEYWORD` index won't support range queries. This is a design note, not a bug -- current usage is consistent.

**File:** `store.py:198-203`

### `ensure_code_table()` (lines 219-229)

```python
for fname in ("path", "language", "function_name", "class_name"):
    self._client.create_payload_index(
        ...
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
self._client.create_payload_index(
    ...
    field_name="line_start",
    field_schema=models.PayloadSchemaType.INTEGER,
)
```

**Verdict: PASS.** Four KEYWORD indexes + one INTEGER index for `line_start`. Schema types are correct for each field's data type.

______________________________________________________________________

## Check 3: Date Filter -- `MatchValue` not `MatchText`

### `_build_filter()` (lines 686-692)

```python
if key == "date":
    conditions.append(
        models.FieldCondition(
            key="date",
            match=models.MatchValue(value=value),
        )
    )
```

**Verdict: PASS.** Uses `MatchValue` (exact match) as intended. The earlier `MatchText` bug (R22b-M1) has been fixed.

______________________________________________________________________

## Check 4: Tag Filter

### `_build_filter()` (lines 693-699)

```python
elif key == "tag":
    conditions.append(
        models.FieldCondition(
            key="tags",
            match=models.MatchAny(any=[value]),
        )
    )
```

**Verdict: PASS.** Correctly maps filter key `"tag"` to payload field `"tags"`. Uses `MatchAny(any=[value])` which checks if the `tags` list-of-strings payload contains the given value. This is the correct Qdrant filter for "any element of the array matches".

Note: `MatchAny(any=[value])` with a single-element list is functionally equivalent to `MatchValue(value=value)` for array payloads, but `MatchAny` is semantically clearer for array fields. If multi-tag filtering is needed (e.g., `tag:research tag:adr`), the caller would need to add multiple `tag` entries to the filters dict or the code would need a list-valued filter. Currently `search.py` only extracts the last `tag:` from the query string, so single-tag is the only supported mode.

______________________________________________________________________

## Check 5: `hybrid_search` / `hybrid_search_codebase` -- Count Guard and Prefetch Filter

### Count guard removed

Neither `hybrid_search` (lines 510-589) nor `hybrid_search_codebase` (lines 591-662) call `self.count()` or `self.count_code()` before searching. They call `self.ensure_table()` / `self.ensure_code_table()` at the top, then go directly to `query_points`.

**Verdict: PASS.** The redundant count guard (R22b-M2) has been removed.

### Prefetch uses `filter=` not `query_filter=`

`hybrid_search` line 549: `filter=query_filter` on `Prefetch`
`hybrid_search_codebase` line 619: `filter=query_filter` on `Prefetch`

Top-level `query_points` (lines 567-572, 637-642) uses no `query_filter=` parameter (correct -- filter is on prefetch).

Dense-only fallback (lines 580-586, 653-658) uses `query_filter=query_filter` on the top-level `query_points` call (correct for non-prefetch queries).

**Verdict: PASS.** `filter=` on Prefetch, `query_filter=` on fallback top-level query. Both correct per qdrant-client API.

______________________________________________________________________

## Check 6: Sparse=None Guard

### `hybrid_search` (lines 553-564)

```python
if sparse_vector is not None:
    prefetch.append(
        models.Prefetch(
            query=models.SparseVector(...),
            using="sparse",
            ...
        ),
    )
```

### `hybrid_search_codebase` (lines 623-634)

Same pattern.

**Verdict: PASS.** When `sparse_vector is None`, only the dense Prefetch is created. The RRF fusion still works with a single prefetch (it just returns dense-only results). No crash risk from `None` sparse vectors.

______________________________________________________________________

## Check 7: `_stable_id` hashlib Import

### `_stable_id()` (lines 735-745)

```python
@staticmethod
def _stable_id(string_id: str) -> int:
    import hashlib
    h = hashlib.sha256(string_id.encode("utf-8")).digest()
    return int.from_bytes(h[:8], byteorder="big") & 0x7FFFFFFFFFFFFFFF
```

### R9-M1: `_stable_id` still imports `hashlib` inside method body (MEDIUM)

The `import hashlib` is still inside the `_stable_id` static method (line 742), not at module level. While Python caches module imports after first load (so subsequent `import hashlib` is just a `sys.modules` dict lookup), this is called once per document/chunk in `upsert_documents`, `upsert_code_chunks`, `delete_documents`, `delete_code_chunks`, and `get_by_id`. For a 1000-document upsert, that is 1000 redundant `sys.modules` lookups.

`hashlib` is already imported at module level in `indexer.py` (line 10). In `store.py`, it is NOT at module level -- it is only inside `_stable_id`.

This was flagged as R22b-m2 and the recommendation was to move it to module level. It has not been addressed.

**File:** `store.py:742`
**Severity:** MEDIUM (performance on bulk operations, trivial fix)

______________________________________________________________________

## Check 8: `_build_filter` Unknown Keys

### `_build_filter()` (lines 676-709)

```python
for key, value in filters.items():
    if key == "date":
        ...
    elif key == "tag":
        ...
    elif key in ("doc_type", "feature"):
        ...
if not conditions:
    return None
```

### R9-m2: `_build_filter` silently drops unknown filter keys (Minor)

If a filter dict contains an unrecognized key (e.g., `{"title": "foo"}`), it falls through all the `if/elif` branches and no condition is added. No warning is logged. The caller believes the filter is active but it has no effect.

This was flagged as R22b-m4 and has not been addressed.

**File:** `store.py:685-709`

### `_build_code_filter()` (lines 711-733)

Same pattern -- unknown keys silently dropped.

**File:** `store.py:721-733`

______________________________________________________________________

## Check 9: `_build_filter` Empty String Values

### `_build_filter()` (lines 685-706)

There is no check for empty string values. If `filters={"doc_type": ""}` is passed:

- Line 700-706: `key in ("doc_type", "feature")` is true, so `MatchValue(value="")` is created
- This matches documents with an empty `doc_type` field, which is likely unintended

### R9-m3: `_build_filter` does not skip empty string values (Minor)

Empty string values create `MatchValue(value="")` conditions which match documents with empty string payloads. In practice, `prepare_document()` always sets `doc_type` from a non-None enum value and `feature` to either a tag string or `""`. So `feature=""` actually IS a valid filter (matches docs with no feature tag). This makes the empty-string behavior arguably correct for the `feature` field but confusing for `doc_type` (where `""` should never appear).

This was flagged as R22b-m5 and has not been addressed.

**File:** `store.py:700-706`

______________________________________________________________________

## Check 10: `upsert_documents` / `upsert_code_chunks` Batching

### `upsert_documents()` (lines 232-277)

```python
points = []
for doc in docs:
    ...
    points.append(...)
self._client.upsert(
    collection_name=self.TABLE_NAME,
    points=points,
)
```

### `upsert_code_chunks()` (lines 279-324)

Same pattern -- all points in a single `upsert()` call.

### R9-m4: No batching on upsert -- all points sent in a single call (Minor)

Both methods send all points in one `upsert()` call regardless of count. For typical vault sizes (tens to hundreds of documents) this is fine. For very large codebase indexing (thousands of chunks), this could be a concern. Qdrant local mode handles large batches internally, so this is low risk.

This was flagged as R22b-m3 and has not been addressed.

**File:** `store.py:273-276, 320-323`

______________________________________________________________________

## Check 11: `_points_to_dicts` Fallback ID

### `_points_to_dicts()` (lines 664-673)

```python
@staticmethod
def _points_to_dicts(scored_points: list, id_field: str) -> list[dict]:
    results = []
    for point in scored_points:
        row = dict(point.payload) if point.payload else {}
        row["id"] = row.pop(id_field, str(point.id))
        row["_relevance_score"] = point.score
        results.append(row)
    return results
```

### R9-m5: `_points_to_dicts` uses `str(point.id)` as silent fallback (Minor)

If the `id_field` (`doc_id` or `chunk_id`) is missing from the payload, `row.pop(id_field, str(point.id))` falls back to `str(point.id)`. The `point.id` is the integer hash from `_stable_id`, so the fallback produces something like `"4582719306421"` instead of the original document stem. No warning is logged.

In practice, all upsert paths include `doc_id`/`chunk_id` in the payload (lines 260, 307), so this fallback should never trigger. But if it does, downstream code receiving an integer-string ID will silently break lookups.

This was flagged as R22b-m8 and has not been addressed.

**File:** `store.py:670`

______________________________________________________________________

## Additional Observations

### Hybrid search exception handling (lines 574-578, 644-648)

```python
except (
    UnexpectedResponse,
    ResponseHandlingException,
    ValueError,
) as exc:
```

The broad `except Exception` from the original code (R22b-m6) has been narrowed to three specific exception types. This is a correct fix -- only Qdrant fusion-related errors trigger the dense-only fallback, while other exceptions (auth errors, corrupted state, etc.) propagate up.

**Verdict: PASS.** Exception handling properly narrowed.

### `list_all_documents` fallback ID (line 503)

```python
payload["id"] = payload.pop("doc_id", str(point.id))
```

Same `str(point.id)` fallback pattern as `_points_to_dicts`. Same minor concern (R9-m5 applies here too).

**File:** `store.py:503`

______________________________________________________________________

## Summary

| ID    | Severity | Finding                                                                             | Status                 |
| ----- | -------- | ----------------------------------------------------------------------------------- | ---------------------- |
| R9-M1 | MEDIUM   | `_stable_id` still imports `hashlib` inside method body (not moved to module level) | Unfixed (from R22b-m2) |
| R9-m1 | MINOR    | `date` payload index uses KEYWORD schema -- limits future range queries             | Design note            |
| R9-m2 | MINOR    | `_build_filter` silently drops unknown filter keys (no warning logged)              | Unfixed (from R22b-m4) |
| R9-m3 | MINOR    | `_build_filter` does not skip empty string values                                   | Unfixed (from R22b-m5) |
| R9-m4 | MINOR    | No batching on `upsert_documents` / `upsert_code_chunks`                            | Unfixed (from R22b-m3) |
| R9-m5 | MINOR    | `_points_to_dicts` and `list_all_documents` use `str(point.id)` as silent fallback  | Unfixed (from R22b-m8) |

### Verified Fixes (from prior rounds)

| Prior Finding                                        | Status                                    |
| ---------------------------------------------------- | ----------------------------------------- |
| R22b-M1: `_build_filter` date uses `MatchText`       | **FIXED** -- now uses `MatchValue`        |
| R22b-M2: `hybrid_search` count() guard               | **FIXED** -- removed                      |
| R22b-m1: `ensure_table` repeated `collection_exists` | **FIXED** -- boolean cache added          |
| R22b-m6: `except Exception` swallows all errors      | **FIXED** -- narrowed to 3 specific types |

**1 MEDIUM finding (R9-M1). 5 MINOR findings (all unfixed carryovers from R22b).**
