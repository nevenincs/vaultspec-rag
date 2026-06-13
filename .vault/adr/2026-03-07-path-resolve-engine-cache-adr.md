---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-03-07'
related:
  - '[[2026-03-07-continuous-research]]'
---

# ADR: Use `Path.resolve()` for engine cache key

## Status

Accepted

## Context

`api.py` creates RAG engines keyed by vault path. But pathlib comparison is
lexical: `Path("./project") != Path("project")` despite pointing to the same
location. This causes unnecessary engine recreation and wasted GPU memory.

## Decision

Use `Path.resolve()` to normalize vault paths before using them as cache keys.

```python
key = vault_path.resolve()
if key not in self._engines:
    self._engines[key] = RAGEngine(key)
```

## Rationale

1. **pathlib comparison is lexical**, not filesystem-based. These are all
   unequal: `Path("./project")`, `Path("project")`, `Path("a/../project")`,
   `Path("/abs/project")` (from a relative CWD). Only string-identical paths
   compare equal.

1. **`Path.resolve()` canonicalizes** by making the path absolute, resolving
   symlinks, and eliminating `.`/`..` components. Two paths to the same
   filesystem location always resolve to the same string.

1. **Symlink resolution is desired**: two symlinks pointing to the same vault
   should share one engine (same data, same index).

1. **Windows compatibility**: `resolve()` normalizes drive letter case and
   UNC paths. `Path("c:/foo").resolve() == Path("C:/foo").resolve()`.

1. **Negligible cost**: `resolve()` does ~5-15us of stat() syscalls. Engine
   creation loads GPU models (seconds). The normalization cost is invisible.

1. **Alternative rejected**: `os.path.normpath(os.path.abspath(...))` does
   lexical normalization without symlink resolution. Not suitable because
   symlinks to the same vault would create duplicate engines.

## Consequences

- `api.py` calls `.resolve()` on vault paths before cache lookup.
- Duplicate engine creation eliminated for `./`, `../`, relative, and
  symlinked vault paths.
- Vault path must exist at resolution time (it should -- we're about to read
  from it).
