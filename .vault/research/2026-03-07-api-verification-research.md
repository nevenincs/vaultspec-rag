---
tags:
  - '#research'
  - '#gpu-rag-stack'
date: 2026-03-07
related: []
---

# API Verification Report — 2026-03-07

Verified against live library docs + runtime tests on the actual installed
packages in this project's venv.

______________________________________________________________________

## 1. tree-sitter-language-pack

**Installed:** tree-sitter-language-pack 0.13.0 (requires tree-sitter >= 0.23)
**tree-sitter:** 0.25.2

### Import: `from tree_sitter_language_pack import get_parser`

**VERIFIED OK.** The package exports exactly three functions:

- `get_binding(grammar_name)` -> pycapsule object
- `get_language(grammar_name)` -> `tree_sitter.Language`
- `get_parser(grammar_name)` -> `tree_sitter.Parser`

### `get_parser(grammar_name)` signature

**VERIFIED OK.** Takes a single string argument (grammar name). Returns a
fully initialized `tree_sitter.Parser` instance with the language already set.

### `parser.parse(source.encode("utf-8"))` -> Tree

**VERIFIED OK.** `Parser.parse()` accepts `bytes`. Returns a `tree_sitter.Tree`.
The indexer correctly uses `source.encode("utf-8")`.

### `tree.root_node`

**VERIFIED OK.** Returns the root `tree_sitter.Node`.

### Node attributes

All verified via runtime test:

| Attribute                     | Type                 | Status                                   |
| ----------------------------- | -------------------- | ---------------------------------------- |
| `node.type`                   | `str`                | OK                                       |
| `node.text`                   | `bytes`              | OK (note: bytes, not str)                |
| `node.start_byte`             | `int`                | OK                                       |
| `node.end_byte`               | `int`                | OK                                       |
| `node.start_point`            | `Point(row, column)` | OK (namedtuple, supports `[0]` indexing) |
| `node.end_point`              | `Point(row, column)` | OK (namedtuple, supports `[0]` indexing) |
| `node.children`               | `list[Node]`         | OK                                       |
| `child_by_field_name("name")` | `Node \| None`       | OK                                       |

The indexer uses `node.start_point[0]` (line 295-296) — this works because
`Point` is a namedtuple supporting index access. `.row` also works.

The indexer uses `source[node.start_byte:node.end_byte]` (line 290) — this
correctly slices the Python `str` by byte offset. **However**, this is only
correct when the source is pure ASCII or the byte offsets align with character
offsets. For UTF-8 source with multi-byte chars, `start_byte`/`end_byte` are
byte offsets into the `bytes` object, not character offsets into the `str`.
The indexer passes `source` as a `str` and slices by byte offset — this could
produce wrong text for files with non-ASCII content. **MINOR** issue since most
source code is ASCII, but worth noting for future hardening.

### Grammar names

**CRITICAL BUG: `c_sharp` is not a valid grammar name.**

Runtime test results:

| Grammar name | Status                                                     |
| ------------ | ---------------------------------------------------------- |
| `python`     | OK                                                         |
| `rust`       | OK                                                         |
| `javascript` | OK                                                         |
| `typescript` | OK                                                         |
| `tsx`        | OK                                                         |
| `go`         | OK                                                         |
| `java`       | OK                                                         |
| `c`          | OK                                                         |
| `cpp`        | OK                                                         |
| `c_sharp`    | **FAILED** — `Could not find language library for c_sharp` |
| `csharp`     | OK                                                         |
| `ruby`       | OK                                                         |
| `bash`       | OK                                                         |
| `kotlin`     | OK                                                         |

**The correct grammar name is `csharp`, not `c_sharp`.**

This bug exists in two places in `src/vaultspec_rag/indexer.py`:

1. **Line 172:** `".cs": ("csharp", "c_sharp")` — the second element (grammar
   name) must be `"csharp"`, not `"c_sharp"`.
1. **Line 218:** `_TOP_LEVEL_NODES` dict uses `"c_sharp"` as the key. This key
   must also be `"csharp"` to match the corrected grammar name.

**Impact:** Any `.cs` file will trigger a `get_parser("c_sharp")` call which
raises an exception. The `_chunk_with_ast` method catches this and falls back
to `TextSplitter`, so it doesn't crash — but C# files get no AST chunking.

______________________________________________________________________

## 2. pathspec

**Installed:** pathspec 1.0.4 (Jan 2026)

### `import pathspec` then `pathspec.GitIgnoreSpec.from_lines(patterns)`

**VERIFIED OK.** `GitIgnoreSpec` exists. `from_lines()` accepts:

- `from_lines(lines)` — list of pattern strings (most common usage)
- `from_lines(pattern_factory, lines)` — with explicit factory (not needed)

The `pattern_factory` defaults to `GitIgnoreSpecPattern` for `GitIgnoreSpec`,
so passing just `lines` is correct. The indexer uses
`pathspec.GitIgnoreSpec.from_lines(patterns)` at line 759 — **correct**.

### `spec.match_file(rel_path_string)` -> bool

**VERIFIED OK.** `match_file()` takes a string path and returns:

- `True` when the file **matches** the patterns (i.e., the file IS ignored)
- `False` when the file does NOT match (i.e., the file is NOT ignored)

This is the gitignore convention: patterns specify what to EXCLUDE.

### Indexer usage at line 768-769

```python
if spec.match_file(rel):
    continue
```

**VERIFIED CORRECT.** `match_file` returns `True` for ignored files, and the
indexer correctly `continue`s (skips) those files.

Runtime test confirmed:

- `"foo.pyc"` with pattern `"*.pyc"` -> `match_file` returns `True` (ignored) -> skipped: correct
- `"foo.py"` -> `match_file` returns `False` (not ignored) -> kept: correct
- `"__pycache__/cache.db"` with pattern `"__pycache__/"` -> `True`: correct
- `".env"` with pattern `".env"` -> `True`: correct

### Note on `negate` parameter

`match_file()` does NOT have a `negate` parameter. Only the plural methods
(`match_files()`, `match_tree_files()`) support `negate`. The indexer doesn't
use `negate` — correct.

______________________________________________________________________

## Summary

| API Call                                           | Status           | Notes                                     |
| -------------------------------------------------- | ---------------- | ----------------------------------------- |
| `from tree_sitter_language_pack import get_parser` | OK               |                                           |
| `get_parser(grammar)`                              | OK               | Returns `tree_sitter.Parser`              |
| `parser.parse(bytes)`                              | OK               | Returns `Tree`                            |
| `tree.root_node`                                   | OK               | Returns `Node`                            |
| `node.start_byte`, `end_byte`                      | OK               |                                           |
| `node.start_point`, `end_point`                    | OK               | Point namedtuple, `[0]` works             |
| `node.children`, `node.type`                       | OK               |                                           |
| Grammar: `"c_sharp"`                               | **CRITICAL BUG** | Must be `"csharp"`                        |
| `pathspec.GitIgnoreSpec.from_lines(lines)`         | OK               |                                           |
| `spec.match_file(path)` -> True=ignored            | OK               | Indexer usage correct                     |
| `source[node.start_byte:node.end_byte]` on `str`   | **MINOR**        | Byte vs char offset mismatch on non-ASCII |

### Required fixes

1. **CRITICAL:** `indexer.py` line 172: change `"c_sharp"` to `"csharp"`
1. **CRITICAL:** `indexer.py` line 218: change `"c_sharp"` key to `"csharp"`
1. **MINOR:** `_collect_chunks` slices `str` by byte offset — works for ASCII
   source but technically incorrect for multi-byte UTF-8. Low priority.
