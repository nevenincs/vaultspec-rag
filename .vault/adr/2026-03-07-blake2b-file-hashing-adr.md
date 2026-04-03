---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: 2026-03-07
related:
  - '[[2026-03-07-continuous-research]]'
---

# ADR: Use blake2b via `file_digest()` for file change detection

## Status

Accepted

## Context

`VaultIndexer` needs to detect file content changes to determine which
documents require re-indexing. The previous approach used filesystem mtime,
which is unreliable (1-2 second resolution, not portable). Content hashing
is more reliable but the algorithm choice matters for performance.

## Decision

Use `hashlib.blake2b` via `hashlib.file_digest()` (Python 3.11+) for all
file change detection.

```python
import hashlib

def content_hash(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "blake2b").hexdigest()
```

## Rationale

Three algorithms were evaluated:

| Algorithm | Throughput | Stdlib? | Dependency           |
| --------- | ---------- | ------- | -------------------- |
| xxh64     | ~19 GB/s   | No      | pip `xxhash` (C ext) |
| blake2b   | ~1 GB/s    | **Yes** | None                 |
| sha256    | ~0.3 GB/s  | Yes     | None                 |

Key considerations:

1. **No new dependency.** blake2b is in stdlib. xxhash requires pip install
   and is a C extension with no pure-Python fallback.

1. **Fast enough.** Our vault has 213 markdown files (~1-50 KB each). At
   1 GB/s, hashing the entire corpus takes \<10ms. The 5.6x speedup of
   xxhash saves only microseconds.

1. **`file_digest()` is optimal.** Added in Python 3.11, it handles chunked
   reading with optimal block sizes internally. One-liner, zero configuration.
   We require Python 3.13, so it's always available.

1. **SHA-256 is overkill.** Cryptographic collision resistance is irrelevant
   for change detection (no adversary). blake2b is 3x faster and equally
   deterministic.

## Consequences

- No new dependency added to `pyproject.toml`.
- `VaultIndexer` stores blake2b hex digests per file for change comparison.
- If corpus grows to multi-GB codebases, xxhash can be a drop-in replacement.
