# ADR: Payload indexes are no-ops in local mode; add for forward compatibility

Date: 2026-03-07
Status: Accepted

## Context

Qdrant supports payload indexes for efficient filtering on fields like
`path`, `language`, `function_name`. Our codebase uses `QdrantClient(path=...)`
(local mode). The question is whether to call `create_payload_index()` when
it has no effect in local mode.

## Decision

Call `create_payload_index()` unconditionally at collection setup time, even
though it is a no-op in local mode.

## Rationale

1. **Verified no-op in local mode.** Runtime testing confirmed that
   `create_payload_index()` in local mode:
   - Does not create actual indexes (`payload_schema` remains `{}`)
   - Does not error or affect data
   - Is fully idempotent (safe to call multiple times)
   - Is non-destructive on existing points and payloads

2. **Forward compatibility.** When/if we migrate to Qdrant server mode
   (Docker), the index creation calls will automatically take effect without
   code changes. This is the recommended practice from Qdrant docs.

3. **No existence check needed.** Since the call is idempotent, there is no
   reason to guard with `if field not in payload_schema`. In local mode
   `payload_schema` is always `{}`, making such checks meaningless anyway.

4. **Recommended indexes for code chunks:**
   - `path`: KEYWORD (high cardinality, used in `MatchAny` filters)
   - `language`: KEYWORD (used in language-specific filtering)
   - `function_name`, `class_name`: KEYWORD (metadata filtering)
   - `line_start`: INTEGER with `range=True` (range queries)

## Consequences

- `store.py` calls `create_payload_index()` after `create_collection()`.
- Zero runtime cost in local mode (no-op).
- Automatic benefit when migrating to Qdrant server mode.
- No need to maintain index existence checks or migration logic.
