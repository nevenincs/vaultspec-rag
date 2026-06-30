---
tags:
  - '#research'
  - '#gpu-rag-stack'
date: 2026-03-07
modified: '2026-06-30'
---

# Continuous Research Loop Findings — 2026-03-07

______________________________________________________________________

## Topic 1: Tree-sitter byte offset vs Python str character offset

### The Problem

Our `ASTChunker._collect_chunks()` (indexer.py line 290) does:

```python
text = source[node.start_byte:node.end_byte]
```

where `source` is a Python `str`. Tree-sitter `start_byte`/`end_byte` are **byte
offsets into the UTF-8 encoded bytes**, not character offsets into the Python str.
For pure ASCII source, byte offset == character offset, so this works. For source
containing multi-byte UTF-8 characters (CJK, emoji, accented chars), the offsets
diverge and the slicing produces wrong text.

### Runtime proof

```python
code_str = '\u4e16 = 1\ny = 2\n'  # CJK char at start
code_bytes = code_str.encode('utf-8')
# str length: 12, bytes length: 14 (CJK char = 3 bytes)

# For the first assignment node (byte range [0:7]):
bytes_slice = code_bytes[0:7].decode('utf-8')  # '\u4e16 = 1'  (CORRECT)
str_slice   = code_str[0:7]                     # '\u4e16 = 1\ny'  (WRONG — includes next line)
```

### How LlamaIndex CodeSplitter solves it

LlamaIndex's CodeSplitter (the industry-standard tree-sitter chunker) keeps the
source as `bytes` throughout:

```python
# split_text() method:
text_bytes = bytes(text, "utf-8")
tree = self._parser.parse(text_bytes)

# _chunk_node() method — slices bytes, then decodes:
child_text = text_bytes[child.start_byte:child.end_byte].decode("utf-8")
```

**Pattern:** Parse `bytes`, slice `bytes` by byte offset, decode chunk to `str`.

### Recommended fix for our ASTChunker

```python
def chunk(self, source: str, grammar: str) -> list[...]:
    from tree_sitter_language_pack import get_parser

    parser = get_parser(grammar)
    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    top_nodes = _TOP_LEVEL_NODES.get(grammar, set())
    chunks: list[tuple[str, int, int, str | None]] = []
    self._collect_chunks(root, source_bytes, top_nodes, chunks)
    return self._merge_small(chunks)

def _collect_chunks(self, node, source_bytes: bytes, ...):
    text = source_bytes[node.start_byte:node.end_byte].decode("utf-8")
    # ... rest of method uses text (str) for len() and content
```

Key changes:

1. Pass `source_bytes: bytes` instead of `source: str`
1. Slice `source_bytes[start_byte:end_byte]` then `.decode("utf-8")`
1. `node.start_point[0]` for line numbers is unaffected (row/col, not byte)

### Impact assessment

**LOW for current codebase** — most source code is ASCII. But any file with
comments in CJK/Cyrillic/Arabic, string literals with emoji, or identifiers
in non-Latin scripts will produce silently wrong chunk boundaries. Worth fixing
proactively.

______________________________________________________________________

## Topic 2: pathspec GitIgnoreSpec negation patterns in subdirectory .gitignore files

### The Problem

The current `_scan_codebase()` (indexer.py lines 748-757) handles nested
`.gitignore` files by prefixing patterns with the subdirectory path:

```python
patterns.append(f"{str(rel_dir).replace(chr(92), '/')}/{stripped}")
```

This breaks **negation patterns**. If `subdir/.gitignore` contains `!important.log`,
the indexer produces `subdir/!important.log`. But pathspec requires the `!` at the
**start** of the pattern: `!subdir/important.log`.

### Runtime proof

```python
# BROKEN (current code): 'subdir/!important.log'
spec = pathspec.GitIgnoreSpec.from_lines(['*.log', 'subdir/!important.log'])
spec.match_file('subdir/important.log')  # True (STILL IGNORED — negation not recognized)

# CORRECT: '!subdir/important.log'
spec = pathspec.GitIgnoreSpec.from_lines(['*.log', '!subdir/important.log'])
spec.match_file('subdir/important.log')  # False (NOT IGNORED — negation works)
```

### Recommended fix

```python
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        continue
    if str(rel_dir) == ".":
        patterns.append(stripped)
    elif stripped.startswith("!"):
        # Negation: move ! before the directory prefix
        patterns.append(f"!{str(rel_dir).replace(chr(92), '/')}/{stripped[1:]}")
    else:
        patterns.append(f"{str(rel_dir).replace(chr(92), '/')}/{stripped}")
```

### Impact assessment

**MEDIUM** — affects any project with negation patterns in subdirectory
`.gitignore` files. Without the fix, negated files are silently ignored
(not indexed). Common in monorepos where subdirectories un-ignore specific
build artifacts or config files.

______________________________________________________________________

## Topic 3: Qdrant MatchAny filter for bulk path-based scroll queries

### Use case

`CodebaseIndexer._get_chunk_ids_for_files()` (indexer.py line 1014-1022)
currently loads ALL chunk IDs from the store and filters them in Python with
string prefix matching:

```python
all_ids = self.store.get_all_code_ids()
return [cid for cid in all_ids if any(cid.startswith(f"{rp}:") for rp in rel_paths)]
```

This is O(n\*m) and requires loading all IDs into memory. For large codebases
this is slow and wasteful.

### Better approach: Qdrant scroll with MatchAny payload filter

Since each chunk has a `path` payload field, we can scroll with a filter:

```python
from qdrant_client.models import Filter, FieldCondition, MatchAny

def _get_chunk_ids_for_files(self, rel_paths: set[str]) -> list[str]:
    """Return chunk IDs from the store that belong to the given files."""
    path_filter = Filter(
        must=[
            FieldCondition(
                key="path",
                match=MatchAny(any=list(rel_paths)),
            )
        ]
    )

    chunk_ids: list[str] = []
    offset = None
    while True:
        points, next_offset = self.store._client.scroll(
            collection_name=self.store._code_collection,
            scroll_filter=path_filter,
            limit=1000,
            offset=offset,
            with_payload=False,
            with_vectors=False,
        )
        chunk_ids.extend(str(p.id) for p in points)
        if next_offset is None:
            break
        offset = next_offset

    return chunk_ids
```

### Requirements

- A **payload index** on `path` field (type: `KEYWORD`) must exist for
  efficient filtering. Without the index, Qdrant scans all points.
- `MatchAny` accepts a list of values and matches if the stored value
  equals ANY of them — equivalent to SQL `IN` operator.

### scroll() API reference

```python
client.scroll(
    collection_name: str,
    scroll_filter: Filter | None = None,
    limit: int = 10,
    offset: PointId | None = None,  # use next_page_offset from previous call
    with_payload: bool = True,
    with_vectors: bool = False,
) -> tuple[list[Record], PointId | None]
```

Returns `(points, next_page_offset)`. When `next_page_offset` is `None`,
there are no more results.

### Impact assessment

**LOW priority** — the current approach works correctly, just inefficiently.
Worth refactoring when the codebase grows beyond ~10K chunks.

______________________________________________________________________

## Topic 4: tree-sitter-language-pack 0.13+ API additions

### Release history (from GitHub)

| Version | Date       | Changes                                           |
| ------- | ---------- | ------------------------------------------------- |
| 0.13.0  | 2025-11-26 | Added COBOL grammar                               |
| 0.12.0  | 2025-11-20 | Alpine Linux CI support                           |
| 0.11.0  | 2025-11-12 | Added BSL grammar                                 |
| 0.10.0  | 2025-10-10 | Drop Python 3.9, require 3.10+, tree-sitter 0.25+ |
| 0.9.1   | 2025-09-23 | Added F#, WASM WAT/WAST                           |

### Key findings

- **No API changes.** The public API remains the same three functions:
  `get_binding()`, `get_language()`, `get_parser()`.
- All recent releases are **language additions** (COBOL, BSL, F#, WASM).
- v0.10.0 is the important baseline: dropped Python 3.9, requires
  tree-sitter >= 0.25, which uses the new ABI.
- Our `pyproject.toml` specifies `tree-sitter-language-pack>=0.10` — correct.

### No action needed

The API is stable. No new features to adopt.

______________________________________________________________________

## Topic 5: decorated_definition handling across languages (tree-sitter)

Runtime tests confirm how decorators/annotations are represented per language:

### Python

`decorated_definition` is a wrapper node containing decorator children and a
`definition` field pointing to the actual `function_definition` or
`class_definition`.

```python
# To extract the name from a decorated_definition:
defn = node.child_by_field_name("definition")  # function_definition or class_definition
name = defn.child_by_field_name("name")         # identifier node
```

`decorated_definition` has NO direct `name` field — `node.child_by_field_name("name")`
returns `None`.

### Java

No wrapper node. Annotations are inside a `modifiers` child of
`method_declaration` or `class_declaration`. Name extraction works normally via
`child_by_field_name("name")` on the declaration node.

### TypeScript

Decorators are children of `export_statement`, alongside `class_declaration`.
No wrapper node. Name extraction works normally on the inner declaration.

### Rust

`attribute_item` is a **sibling** of `function_item`/`struct_item`, not a
wrapper. The `_TOP_LEVEL_NODES` set correctly lists `function_item` etc.
Attributes are separate nodes that get merged into adjacent chunks by the
greedy merge step.

### Implication for metadata extraction

When extracting `function_name`/`class_name` from a chunk whose primary node
is `decorated_definition`, the extractor must unwrap it:

```python
if node.type == "decorated_definition":
    inner = node.child_by_field_name("definition")
    if inner:
        node = inner  # now a function_definition or class_definition
```

______________________________________________________________________

## Topic 6: Qdrant payload index types — reference for code metadata

### Recommended indexes for code chunks

```python
from qdrant_client import models

# language: exact match filtering — use keyword
client.create_payload_index(
    collection_name="code_index",
    field_name="language",
    field_schema=models.PayloadSchemaType.KEYWORD,
)

# path: exact match filtering — use keyword
client.create_payload_index(
    collection_name="code_index",
    field_name="path",
    field_schema=models.PayloadSchemaType.KEYWORD,
)

# function_name, class_name: exact match — keyword
client.create_payload_index(
    collection_name="code_index",
    field_name="function_name",
    field_schema=models.PayloadSchemaType.KEYWORD,
)
client.create_payload_index(
    collection_name="code_index",
    field_name="class_name",
    field_schema=models.PayloadSchemaType.KEYWORD,
)

# line_start: range queries (e.g., "functions after line 100") — integer
client.create_payload_index(
    collection_name="code_index",
    field_name="line_start",
    field_schema=models.IntegerIndexParams(
        type=models.IntegerIndexType.INTEGER,
        lookup=False,  # no exact match needed
        range=True,    # range queries only
    ),
)

# content: full-text search on code text (BM25-like) — text
client.create_payload_index(
    collection_name="code_index",
    field_name="content",
    field_schema=models.TextIndexParams(
        type=models.TextIndexType.TEXT,
        tokenizer=models.TokenizerType.WORD,
        min_token_len=2,
        max_token_len=40,
        lowercase=True,
    ),
)
```

### Key best practices (from Qdrant docs)

1. **Create indexes immediately after collection creation** — allows HNSW
   graphs to benefit from index-aware optimization.
1. **Only index fields used in filters** — indexes consume RAM.
1. **High-cardinality fields benefit most** — `path` and `function_name`
   have high cardinality, making them good index candidates.
1. **Use `on_disk=True`** for large collections to reduce RAM at cost of latency.
1. **Use `is_tenant=True`** for multi-project setups where `project_id`
   partitions the data (keyword/uuid types only).

______________________________________________________________________

## Topic 7: tree-sitter Query API — pattern matching for metadata extraction

### Query creation and execution

```python
from tree_sitter_language_pack import get_language

lang = get_language("python")

# Find all function definitions with names
query = lang.query("""
(function_definition
  name: (identifier) @func_name)
""")

# captures returns dict: {"func_name": [Node, ...]}
captures = query.captures(tree.root_node)
for node in captures.get("func_name", []):
    print(node.text.decode())

# matches returns list of (pattern_index, dict) tuples
matches = query.matches(tree.root_node)
```

### Supported predicates

| Predicate      | Description                       |
| -------------- | --------------------------------- |
| `#eq?`         | Exact string equality             |
| `#not-eq?`     | String inequality                 |
| `#match?`      | Regex pattern match               |
| `#not-match?`  | Regex pattern non-match           |
| `#any-of?`     | Match any of listed strings       |
| `#not-any-of?` | Match none of listed strings      |
| `#any-eq?`     | Any captured node equals value    |
| `#any-match?`  | Any captured node matches pattern |
| `#is?`         | Property assertion                |
| `#set!`        | Property setting                  |

### Useful queries for code metadata extraction

```python
# All class methods (function inside class)
class_methods_query = lang.query("""
(class_definition
  name: (identifier) @class_name
  body: (block
    (function_definition
      name: (identifier) @method_name)))
""")

# Decorated functions
decorated_query = lang.query("""
(decorated_definition
  definition: (function_definition
    name: (identifier) @func_name))
""")

# All imports
import_query = lang.query("""
(import_statement) @import
(import_from_statement) @import_from
""")
```

### Performance note

Queries are compiled once and can be reused across multiple trees. For
metadata extraction on every chunk, compile the query once per language
at `ASTChunker.__init__` time, not per-file.

______________________________________________________________________

## Topic 8: Qdrant create_payload_index() on existing data — idempotency

### Findings (verified via runtime test)

1. **Non-destructive on existing data.** Calling `create_payload_index()` on a
   collection that already has points does NOT delete or modify any data. The
   existing points and payloads remain intact.

1. **Idempotent.** Calling `create_payload_index()` multiple times for the same
   field is safe — no error, no duplicate indexes. The API silently succeeds.

1. **No-op in local mode.** `QdrantClient(path=...)` (our setup) does NOT
   actually create payload indexes. The `payload_schema` in collection info is
   always empty `{}`. Payload indexes only take effect with Qdrant server/Docker
   mode.

1. **No need to check existence first.** Since the call is idempotent, there's
   no reason to guard it with an existence check. Just call it unconditionally.

### Checking index existence (for reference)

```python
info = client.get_collection("my_collection")
existing_indexes = info.payload_schema  # dict: field_name -> PayloadIndexInfo
if "language" not in existing_indexes:
    client.create_payload_index(...)
```

In local mode, `payload_schema` is always `{}`, so this check is meaningless.

### Recommendation

Keep calling `create_payload_index()` unconditionally at collection setup time.
When/if we migrate to Qdrant server mode, the indexes will automatically start
taking effect without code changes.

______________________________________________________________________

## Topic 9: CrossEncoder ms-marco-MiniLM-L6-v2 batch size on RTX 4080 SUPER

### Benchmark setup

- GPU: NVIDIA GeForce RTX 4080 SUPER (16 GB VRAM, 80 SMs, compute 8.9)
- Model: `cross-encoder/ms-marco-MiniLM-L6-v2` (6-layer, 22M params)
- Test: 500 query-document pairs, 5 iterations per batch size

### Results (500 pairs)

| batch_size | avg time (s) | throughput (pairs/s) | peak VRAM (MB) |
| ---------- | ------------ | -------------------- | -------------- |
| 16         | 0.3370       | 1,484                | 104            |
| 32         | 0.2012       | 2,485                | 112            |
| 64         | 0.1344       | 3,720                | 128            |
| 128        | 0.0873       | 5,726                | 159            |
| 256        | 0.0772       | 6,478                | 215            |
| 512        | 0.0754       | 6,635                | 338            |

### Results (1000 pairs, confirming plateau)

| batch_size | avg time (s) | throughput (pairs/s) | peak VRAM (MB) |
| ---------- | ------------ | -------------------- | -------------- |
| 256        | 0.1041       | 9,611                | 224            |
| 512        | 0.0956       | 10,465               | 345            |
| 1000       | 0.1022       | 9,783                | 581            |

### Analysis

- **Throughput plateaus at batch_size=512.** Going to 1000 actually decreases
  throughput slightly while nearly doubling VRAM usage.
- **VRAM is not a concern.** Even at batch_size=512, peak VRAM is only 345 MB —
  negligible on a 16 GB card. The Qwen3 embedding model uses far more.
- **The default batch_size=32 is suboptimal.** On this GPU, batch_size=256-512
  delivers 2.6-4.2x higher throughput than the default.

### Recommendation

Set `batch_size=256` for the CrossEncoder reranker. This gives ~96% of peak
throughput with moderate VRAM (~224 MB). Going to 512 gives only ~3% more
throughput but uses 55% more VRAM. The 256 sweet spot leaves more VRAM headroom
for concurrent embedding operations.

```python
# In search.py CrossEncoder.predict() call:
scores = self._reranker.predict(pairs, batch_size=256)
```

______________________________________________________________________

## Topic 10: Qdrant query_points filter + prefetch interaction

### The question

When using `prefetch` + `FusionQuery(RRF)`, can you apply a `query_filter` at
the top level to filter ALL prefetch branches at once? Or must you add `filter`
to each `Prefetch` individually?

### Runtime test results (Qdrant local mode)

| Scenario                                          | Filter placement                      | Result                                           |
| ------------------------------------------------- | ------------------------------------- | ------------------------------------------------ |
| Top-level `query_filter` only                     | `query_points(query_filter=...)`      | **FILTER IGNORED** — unfiltered results returned |
| Per-Prefetch `filter`                             | `Prefetch(filter=...)` on each branch | **WORKS** — only matching points returned        |
| No filter                                         | baseline                              | All points returned                              |
| Top-level `query_filter` + no per-Prefetch filter | `query_points(query_filter=...)`      | **FILTER IGNORED** — same as no filter           |

### Critical finding

**In Qdrant local mode, `query_filter` at the top level does NOT filter prefetch
results.** The filter is silently ignored when `prefetch` is used with
`FusionQuery`.

The correct approach is to add `filter=` to EACH `Prefetch` individually:

```python
# CORRECT — filter on each prefetch branch
query_filter = models.Filter(must=[
    models.FieldCondition(key="language", match=models.MatchValue(value="python"))
])

client.query_points(
    collection_name="code_index",
    prefetch=[
        models.Prefetch(
            query=dense_vector,
            using="dense",
            limit=20,
            filter=query_filter,  # <-- filter HERE
        ),
        models.Prefetch(
            query=sparse_vector,
            using="sparse",
            limit=20,
            filter=query_filter,  # <-- filter HERE
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
    # query_filter=query_filter  # <-- DO NOT rely on this alone
)
```

### API signatures (verified via inspect)

**`query_points()` parameters:**

- `collection_name`, `query`, `using`, `prefetch`, `query_filter`, `search_params`,
  `limit` (default 10), `offset`, `with_payload` (default True), `with_vectors`,
  `score_threshold`, `lookup_from`, `consistency`, `shard_key_selector`, `timeout`

**`Prefetch` fields:**

- `prefetch` (nested), `query`, `using`, `filter`, `params`, `score_threshold`,
  `limit`, `lookup_from`

Note: The top-level parameter is called `query_filter`, but the Prefetch field
is called `filter`. Different names.

### Our codebase status

**store.py is CORRECT.** It already adds `filter=query_filter` to each Prefetch
individually (lines 506, 519 for vault; lines 570, 583 for codebase). The
fallback single-vector queries also pass `query_filter` at the top level (lines
538, 605), which works because those don't use prefetch.

______________________________________________________________________

## Topic 11: SparseEncoder encode_query() truncation behavior

### API signatures (verified via inspect)

**`SparseEncoder.encode_query()` parameters:**

- `sentences`: `str | list[str] | np.ndarray`
- `prompt_name`: `str | None` (default None)
- `prompt`: `str | None` (default None)
- `batch_size`: `int` (default 32)
- `show_progress_bar`: `bool | None`
- `convert_to_tensor`: `bool` (default True)
- `convert_to_sparse_tensor`: `bool` (default True)
- `save_to_cpu`: `bool` (default False)
- `device`: `str | list | None`
- `max_active_dims`: `int | None` — controls max non-zero dimensions in output
- `pool`: `dict | None`
- `chunk_size`: `int | None`

**No `max_length` parameter.** Truncation is handled internally.

### Truncation behavior (verified via source code)

`MLMTransformer.tokenize()` calls the HuggingFace tokenizer with:

```python
self.tokenizer(
    *to_tokenize,
    padding=padding,
    truncation="longest_first",
    return_tensors="pt",
    max_length=self.max_seq_length,
)
```

This means:

1. **Automatic truncation** to `model.max_seq_length` tokens
1. **No error raised** for inputs exceeding the limit
1. **Silent truncation** — the input is simply cut to the first N tokens

For SPLADE models (BERT-based), `max_seq_length` is typically **256 tokens**
(from the model config). This is documented in sbert.net for
`naver/splade-cocondenser-ensembledistil`. The `naver/splade-v3` model uses
the same BERT base architecture, so 256 tokens is expected.

### encode_query() vs encode() — which to use

sentence-transformers v5.0 introduced `encode_query()` and `encode_document()`
as specialized alternatives to `encode()`:

| Method              | Purpose                | Prompt handling                         |
| ------------------- | ---------------------- | --------------------------------------- |
| `encode_query()`    | Query-side encoding    | Uses "query" prompt if model has one    |
| `encode_document()` | Document-side encoding | Uses "document" prompt if model has one |
| `encode()`          | General purpose        | No automatic prompt selection           |

For SPLADE-v3 specifically, the model card does not define separate query/document
prompts, so `encode()`, `encode_query()`, and `encode_document()` produce
identical output. However, using `encode_query()` / `encode_document()` is best
practice for forward compatibility with models that do distinguish.

### Our codebase status

**embeddings.py uses `encode()` for both queries and documents** (lines 293, 319).
This works correctly for SPLADE-v3 since it has no query/document distinction.
Switching to `encode_query()` / `encode_document()` would be a minor improvement
for forward compatibility but is not a bug.

The pre-truncation at line 289 (`t[:max_chars]`) with `MAX_EMBED_CHARS=8000`
provides a safety net before tokenization, but the tokenizer's own truncation
at `max_seq_length` is the real limit (256 tokens ~ roughly 800-1000 chars
for code).

______________________________________________________________________

## Topic 12: Qwen3-Embedding-0.6B query prompting

### Model prompt configuration (verified via runtime)

```python
model.prompts = {
    'query': 'Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:',
    'document': '',
}
model.default_prompt_name = None
model.max_seq_length = 32768
```

### How to use prompts with sentence-transformers

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")

# Queries: use prompt_name="query" — prepends the instruction
query_embeddings = model.encode(["search term"], prompt_name="query")

# Documents: no prompt needed (prompt_name="document" prepends empty string)
doc_embeddings = model.encode(["document text"])
```

### Performance impact

From the Qwen3 model card:

> "not using an instruct on the query side can lead to a drop in retrieval
> performance by approximately 1% to 5%"

### Custom prompts for code search

The built-in `"query"` prompt is designed for web search retrieval. For code
search, a custom instruction would be more appropriate:

```python
# Option 1: Use the built-in prompt (works, not optimal for code)
query_emb = model.encode(["binary search tree"], prompt_name="query")

# Option 2: Custom code-specific instruction via prompt= param
code_prompt = "Instruct: Given a code search query, retrieve relevant source code that implements the described functionality\nQuery:"
query_emb = model.encode(["binary search tree"], prompt=code_prompt)
```

When both `prompt` and `prompt_name` are provided, `prompt` takes priority.

### Our codebase status

**embeddings.py line 267-271 is CORRECT for queries:**

```python
embeddings = self._dense_model.encode(
    [query],
    prompt_name="query",
    normalize_embeddings=True,
)
```

**embeddings.py line 236-241 is CORRECT for documents:**

```python
embeddings = self._dense_model.encode(
    truncated,
    batch_size=batch_size,
    show_progress_bar=len(truncated) > 100,
    normalize_embeddings=True,
)
```

Documents correctly omit `prompt_name`, so no instruction is prepended.

**Potential improvement:** Consider a custom code-specific prompt for
`search_codebase()` queries. The default `"query"` prompt mentions "web search"
which is suboptimal for code retrieval. This would require adding a new method
or parameter to `encode_query()` in embeddings.py.

______________________________________________________________________

## Topic 13: Qdrant scroll() API for batch list_documents

### Method signature (verified via runtime)

```python
client.scroll(
    collection_name: str,
    scroll_filter: Optional[Filter] = None,
    limit: int = 10,
    order_by: Optional[str | OrderBy] = None,
    offset: Optional[int | str | UUID | PointId] = None,
    with_payload: Union[bool, Sequence[str], PayloadSelectorInclude,
                        PayloadSelectorExclude] = True,
    with_vectors: Union[bool, Sequence[str]] = False,
    consistency: Optional[int | ReadConsistencyType] = None,
    shard_key_selector: Optional[...] = None,
    timeout: Optional[int] = None,
) -> tuple[list[Record], PointId | None]
```

### Key findings (all runtime-verified)

1. **`with_payload` accepts a list of field names:** `with_payload=["path", "title"]`
   returns only those fields. Other fields (e.g., `content`) are excluded.

1. **Pagination uses `offset` from return value:**

   ```python
   records, next_offset = client.scroll(collection_name="docs", limit=10)
   # next_offset is None when no more pages
   ```

1. **`scroll_filter` works for payload filtering:**

   ```python
   adr_filter = models.Filter(must=[
       models.FieldCondition(key="doc_type", match=models.MatchValue(value="adr"))
   ])
   records, _ = client.scroll("docs", scroll_filter=adr_filter, limit=100)
   ```

### Complete working example for Task #26

```python
def list_documents(self, fields: list[str] | None = None) -> list[dict]:
    """Fetch all documents with selected payload fields via scroll."""
    payload_selector = fields if fields else True
    all_docs = []
    offset = None

    while True:
        records, next_offset = self._client.scroll(
            collection_name=self._collection,
            with_payload=payload_selector,
            with_vectors=False,
            limit=100,  # page size
            offset=offset,
        )
        for record in records:
            doc = {"id": record.id}
            doc.update(record.payload or {})
            all_docs.append(doc)

        if next_offset is None:
            break
        offset = next_offset

    return all_docs

# Usage:
docs = store.list_documents(fields=["path", "title", "doc_type"])
```

### Performance notes

- `limit=100` is a reasonable page size for local mode
- Excluding `content` from payload saves memory when only listing metadata
- scroll() is O(n) — fine for collections up to ~100K points

______________________________________________________________________

## Topic 14: MCP tool argument schema with field descriptions

### How FastMCP generates JSON schema

`@mcp.tool()` auto-generates JSON Schema from function type annotations via
pydantic. Three patterns exist, with different schema quality:

### Pattern 1: Plain annotations (current codebase) — NO descriptions

```python
@mcp.tool()
async def search(query: str, top_k: int = 5) -> str:
    """Search the codebase.

    Args:
        query: Search string.
        top_k: Number of results.
    """
    ...
```

Schema output: `{"query": {"title": "Query", "type": "string"}}` — **no
descriptions**. FastMCP does NOT parse docstring `Args:` sections.

### Pattern 2: Annotated + Field (RECOMMENDED) — descriptions in schema

```python
from typing import Annotated
from pydantic import Field

@mcp.tool()
async def search(
    query: Annotated[str, Field(description="Natural language search string")],
    top_k: Annotated[int, Field(description="Number of results to return")] = 5,
    language: Annotated[str | None, Field(description="Language filter")] = None,
) -> str:
    """Search the source codebase for relevant code."""
    ...
```

Schema output includes `"description": "Natural language search string"` per
field. **Flat schema, LLM-friendly.** This is the recommended pattern.

### Pattern 3: Pydantic BaseModel — descriptions but nested schema

```python
class SearchInput(BaseModel):
    query: str = Field(description="Search string")
    top_k: int = Field(default=5, description="Number of results")

@mcp.tool()
async def search(params: SearchInput) -> str:
    ...
```

Schema has `$defs` + `$ref` nesting with a `params` wrapper. Some LLM clients
handle nested `$ref` poorly. **Avoid for MCP tools.**

### Our codebase status

**mcp_server.py uses Pattern 1** (plain annotations). Descriptions from
docstring `Args:` are NOT included in the JSON schema. LLM clients (Claude,
GPT) see field names and types but no descriptions.

**Recommendation:** Migrate to Pattern 2 (`Annotated[type, Field(...)]`) for
all MCP tool parameters. This gives LLMs field-level descriptions without
schema nesting. Example migration for `search_codebase`:

```python
@mcp.tool()
async def search_codebase(
    query: Annotated[str, Field(description="Natural language search string or code snippet")],
    top_k: Annotated[int, Field(description="Number of code chunks to return")] = 5,
    language: Annotated[str | None, Field(description="Language filter (e.g. 'python', 'rust')")] = None,
    node_type: Annotated[str | None, Field(description="AST node type filter (e.g. 'function_definition')")] = None,
    function_name: Annotated[str | None, Field(description="Function/method name filter")] = None,
    class_name: Annotated[str | None, Field(description="Class/struct name filter")] = None,
    ctx: Context | None = None,
) -> SearchResponse:
    """Search the source codebase for relevant functions, classes, or logic."""
    ...
```

______________________________________________________________________

## References

- py-tree-sitter README: <https://github.com/tree-sitter/py-tree-sitter>
- LlamaIndex CodeSplitter source: <https://github.com/run-llama/llama_index/blob/main/llama-index-core/llama_index/core/node_parser/text/code.py>
- pathspec API docs: <https://python-path-specification.readthedocs.io/en/latest/api.html>
- pathspec GitHub: <https://github.com/cpburnz/python-pathspec>
- Qdrant filtering docs: <https://qdrant.tech/documentation/concepts/filtering/>
- Qdrant scroll API: <https://api.qdrant.tech/api-reference/points/scroll-points>
- Qdrant Python client: <https://python-client.qdrant.tech/qdrant_client.qdrant_client>
- tree-sitter-language-pack releases: <https://github.com/Goldziher/tree-sitter-language-pack/releases>
- Qdrant indexing docs: <https://qdrant.tech/documentation/concepts/indexing/>
- py-tree-sitter Query class: <https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.Query.html>
- tree-sitter query syntax: <https://tree-sitter.github.io/tree-sitter/using-parsers/queries/1-syntax.html>
- Qdrant hybrid queries: <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- Qdrant query_points API: <https://api.qdrant.tech/api-reference/search/query-points>
- SparseEncoder API reference: <https://www.sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html>
- sentence-transformers v5.0 release: <https://github.com/UKPLab/sentence-transformers/releases/tag/v5.0.0>
- Computing sparse embeddings guide: <https://sbert.net/examples/sparse_encoder/applications/computing_embeddings/README.html>
- Qwen3-Embedding-0.6B model card: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- MCP Python SDK tool system: <https://deepwiki.com/modelcontextprotocol/python-sdk/2.2-tool-system>
- Qdrant points/scroll docs: <https://qdrant.tech/documentation/concepts/points/>

______________________________________________________________________

## Topic 15: Score normalization for multi-source fusion (RRF + CrossEncoder)

### The problem

`search_all()` combines vault search results (graph-boosted RRF scores) with
codebase search results (CrossEncoder logits). These scores are on incompatible
scales, making combined ranking meaningless.

### RRF score range and distribution

Qdrant computes RRF as:

```
score(d) = sum( 1 / (k + rank_i) ) for each retriever i
```

**Qdrant uses k=2** (not the academic default of k=60). This means:

- Single retriever, rank 1: `1/(2+1)` = 0.333
- Single retriever, rank 10: `1/(2+10)` = 0.083
- Two retrievers, both rank 1: `1/3 + 1/3` = 0.667
- Typical range for 2-retriever fusion: **[0.05, 0.7]**
- Scores are compressed into a narrow band; top vs bottom results differ by ~10x

RRF is **rank-based** — it ignores raw similarity scores entirely. Two documents
with cosine similarities 0.99 and 0.95 get very different RRF scores if they're
at rank 1 vs rank 50.

### CrossEncoder ms-marco-MiniLM-L6-v2 score distribution

The CrossEncoder outputs **raw logits** (unbounded), not probabilities:

- Highly relevant: scores in range **[5, 12]**
- Somewhat relevant: scores in range **[-2, 5]**
- Irrelevant: scores in range **[-10, -4]**
- Full observed range: approximately **[-12, 12]**

To get bounded [0, 1] scores, use `activation_fn=torch.nn.Sigmoid()`:

```python
from sentence_transformers import CrossEncoder
import torch

model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2",
                     activation_fn=torch.nn.Sigmoid())
# Now .predict() returns values in [0, 1]
```

This does **not** affect ranking order — sigmoid is monotonic.

### Normalization approaches

#### Option 1: Min-max normalization per source (simple, effective)

```python
def min_max_normalize(scores: list[float]) -> list[float]:
    if not scores or len(scores) == 1:
        return [1.0] * len(scores) if scores else []
    lo, hi = min(scores), max(scores)
    if lo == hi:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]
```

Pros: Simple, maps both sources to [0, 1]. Works well when both result sets
are meaningful.
Cons: Sensitive to outliers. A single very high/low score distorts the range.

#### Option 2: Sigmoid normalization for CrossEncoder logits

Since CrossEncoder outputs logits, sigmoid is the natural normalization:

```python
import math
normalized = [1 / (1 + math.exp(-s)) for s in ce_scores]
```

This maps [-inf, +inf] to [0, 1] with a natural midpoint at 0.

#### Option 3: Qdrant DBSF (Distribution-Based Score Fusion)

Qdrant natively supports DBSF since v1.11:

```python
from qdrant_client import models

client.query_points(
    collection_name="code_index",
    prefetch=[
        models.Prefetch(query=dense_vec, using="dense", limit=20),
        models.Prefetch(query=sparse_vec, using="sparse", limit=20),
    ],
    query=models.FusionQuery(fusion=models.Fusion.DBSF),
    limit=10,
)
```

DBSF normalizes scores per query using `mean +/- 3*stddev` as limits, then
sums normalized scores. This handles heterogeneous score distributions better
than RRF when score magnitudes carry signal.

**However:** DBSF only works for fusion WITHIN a single `query_points()` call
(combining prefetch branches). It cannot normalize scores across separate
vault + codebase searches in `search_all()`.

### Recommendation for search_all()

For combining vault (RRF) and codebase (CrossEncoder) results:

1. **Normalize CrossEncoder logits with sigmoid** — maps to [0, 1]
1. **Normalize RRF scores with min-max** — maps to [0, 1]
1. **Weighted linear combination**: `final = w_vault * vault_norm + w_code * code_norm`
1. Default weights: `w_vault = 0.5, w_code = 0.5` (tunable)

Alternative: Convert both to rank-based fusion (apply RRF to both result
lists). This avoids score normalization entirely but loses score magnitude
information from the CrossEncoder.

### Our codebase status

**search.py `search_all()`** currently interleaves vault and codebase results
without score normalization. The graph-boosted RRF scores ([0.05, 0.7]) and
CrossEncoder logits ([-12, 12]) are directly compared, making the combined
ranking unreliable. Needs the normalization step described above.

______________________________________________________________________

## Topic 16: asyncio.to_thread() for MCP server GPU inference

### The problem

MCP tools in `mcp_server.py` are declared `async` but call synchronous blocking
operations: GPU inference (SentenceTransformer.encode, CrossEncoder.predict)
and Qdrant I/O (query_points, scroll). These block the asyncio event loop,
preventing concurrent MCP request handling.

### MCP SDK sync tool handling

**As of MCP Python SDK PR #1909 (merged):** The SDK now automatically wraps
synchronous tool functions in `anyio.to_thread.run_sync()`. If you declare
a tool as a regular `def` (not `async def`), the SDK offloads it to a thread
pool automatically.

However, if a tool is declared `async def` and then calls blocking sync code
inside, it **still blocks the event loop** — the auto-wrapping only applies
to non-async functions.

### Recommended pattern for our MCP tools

#### Option A: Declare tools as sync `def` (simplest)

```python
@mcp.tool()
def search_codebase(query: str, top_k: int = 5) -> str:
    """Search source code."""
    # Blocking GPU inference happens here — SDK auto-wraps in thread
    results = searcher.search_codebase(query, top_k=top_k)
    return format_results(results)
```

The SDK wraps the entire function in `anyio.to_thread.run_sync()`. No manual
threading code needed. This is the simplest approach.

#### Option B: Keep `async def` with explicit wrapping

```python
import anyio

@mcp.tool()
async def search_codebase(query: str, top_k: int = 5) -> str:
    """Search source code."""
    results = await anyio.to_thread.run_sync(
        lambda: searcher.search_codebase(query, top_k=top_k)
    )
    return format_results(results)
```

Use `anyio.to_thread.run_sync()` (not `asyncio.to_thread()`) because FastMCP
uses anyio internally. `anyio.to_thread.run_sync()` uses `copy_context()`
internally, so context variables propagate correctly.

### PyTorch thread safety for GPU inference

**Read-only inference is thread-safe with caveats:**

1. **Single model, multiple threads (our case):** PyTorch's C++ backend is
   thread-safe for read-only operations. `model.eval()` + `torch.no_grad()`
   inference from multiple threads sharing one model instance works in practice.

1. **GIL limits parallelism:** Python's GIL serializes the Python-level code.
   GPU kernel launches happen outside the GIL, so CUDA operations can overlap
   with Python code in other threads. But two threads cannot launch GPU kernels
   truly simultaneously from Python.

1. **Practical implication:** For MCP, concurrent requests will queue on the
   GPU. This is fine — the event loop stays unblocked (responds to heartbeats,
   accepts new connections) while GPU work proceeds serially on the device.

1. **What to avoid:**

   - Do NOT modify model weights from any thread during inference
   - Do NOT call `model.train()` while another thread is in `model.eval()`
   - Do NOT share CUDA tensors between threads without synchronization
   - CUDA streams are thread-local by default — each thread gets its own stream

1. **sentence-transformers specifically:** The `SentenceTransformer.encode()`
   method is self-contained (creates tensors, runs forward pass, returns numpy).
   It does not mutate model state. Safe to call from multiple threads.

### Qdrant thread safety

`QdrantClient(path=...)` in local mode uses SQLite + numpy internally. SQLite
in WAL mode supports concurrent reads. Qdrant's local client serializes writes
internally. Thread-safe for our read-heavy MCP workload.

### Recommendation

**Use Option A (sync `def` tools)** for simplicity. The MCP SDK handles
threading automatically. This avoids manual `anyio.to_thread` boilerplate
and is less error-prone.

If we need async operations within a tool (e.g., calling another MCP tool
or async API), then use Option B selectively for that specific tool.

### Concurrency protection for model loading

The `get_comp()` lazy loader in `mcp_server.py` is not thread-safe — two
concurrent requests could both trigger model loading simultaneously (R21-M7).
Add a `threading.Lock`:

```python
import threading

_comp_lock = threading.Lock()
_components: RAGComponents | None = None

def get_comp() -> RAGComponents:
    global _components
    if _components is not None:
        return _components
    with _comp_lock:
        if _components is not None:
            return _components
        _components = _build_components()
        return _components
```

Double-checked locking pattern — the outer check avoids lock contention on
the hot path after initialization.

______________________________________________________________________

## References (continued)

- RRF formula: <https://medium.com/@devalshah1619/mathematical-intuition-behind-reciprocal-rank-fusion-rrf-explained-in-2-mins-002df0cc5e2a>
- Azure hybrid search RRF: <https://learn.microsoft.com/en-us/azure/search/hybrid-search-ranking>
- CrossEncoder ms-marco-MiniLM-L6-v2: <https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2>
- CrossEncoder usage docs: <https://sbert.net/docs/cross_encoder/usage/usage.html>
- Qdrant DBSF hybrid queries: <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- Qdrant 1.11 DBSF announcement: <https://qdrant.tech/blog/qdrant-1.11.x/>
- Score normalization survey: <https://link.springer.com/chapter/10.1007/11880592_57>
- OpenSearch hybrid search normalization: <https://opensearch.org/blog/building-effective-hybrid-search-in-opensearch-techniques-and-best-practices/>
- PyTorch thread safety: <https://discuss.pytorch.org/t/is-pytorch-supposed-to-be-thread-safe/36540>
- MCP SDK sync tool wrapping: <https://github.com/modelcontextprotocol/python-sdk/issues/1839>
- FastMCP tools docs: <https://fastmcp.wiki/en/servers/tools>
- PyTorch CUDA threading: <https://discuss.pytorch.org/t/is-is-thread-safe-to-do-tensor-to-device-from-multiple-threads-to-the-same-gpu-device/157783>

______________________________________________________________________

## Topic 17: asyncio.Lock vs threading.Lock in FastMCP context

### The question

For `get_comp()` singleton initialization in `mcp_server.py`: should we use
`asyncio.Lock`, `threading.Lock`, or `anyio.Lock`? The function is called
from MCP tool handlers that may run in worker threads (via
`anyio.to_thread.run_sync()`).

### Lock type comparison

| Lock type        | Thread-safe | Async-safe        | Can use from worker thread | Can use from coroutine     |
| ---------------- | ----------- | ----------------- | -------------------------- | -------------------------- |
| `threading.Lock` | Yes         | **DEADLOCK RISK** | Yes                        | **NO** — blocks event loop |
| `asyncio.Lock`   | **No**      | Yes               | **No** — not thread-safe   | Yes                        |
| `anyio.Lock`     | **No**      | Yes               | **No** — not thread-safe   | Yes                        |

### Why threading.Lock deadlocks in async context

All coroutines on one event loop run in a **single OS thread**. If coroutine A
holds a `threading.Lock` and yields (awaits), coroutine B tries to acquire
the same lock on the **same thread**. Since `threading.Lock` is not reentrant,
the thread blocks — but it's the only thread running the event loop, so
coroutine A can never resume to release the lock. **Deadlock.**

Even without contention, `threading.Lock.acquire()` is a **blocking call**
that freezes the event loop for the duration of the critical section.

### Why asyncio.Lock / anyio.Lock don't work for worker threads

`asyncio.Lock` and `anyio.Lock` are **not thread-safe**. They must only be
acquired from coroutines on the event loop thread. When MCP tools run as
sync `def` (auto-wrapped in `anyio.to_thread.run_sync()`), they execute
in a **worker thread**, not the event loop thread. You cannot `await` an
`asyncio.Lock` from a worker thread.

### The dilemma for get_comp()

With sync `def` tools (recommended in Topic 16), `get_comp()` is called from
worker threads. This means:

- `asyncio.Lock` / `anyio.Lock` cannot be used (wrong thread)
- `threading.Lock` CAN be used safely (worker threads are real OS threads)

**Key insight:** The deadlock risk with `threading.Lock` only applies when
used between coroutines on the event loop thread. When used exclusively in
worker threads spawned by `anyio.to_thread.run_sync()`, it works correctly
because each worker thread is a real OS thread that can block independently.

### Recommendation: threading.Lock for get_comp()

Since `get_comp()` is called from worker threads (sync `def` tools):

```python
import threading

_comp_lock = threading.Lock()
_components: RAGComponents | None = None

def get_comp() -> RAGComponents:
    global _components
    if _components is not None:
        return _components
    with _comp_lock:
        if _components is not None:
            return _components
        _components = _build_components()
        return _components
```

This is safe because:

1. `get_comp()` runs in worker threads, not the event loop thread
1. `threading.Lock` correctly serializes concurrent worker threads
1. Double-checked locking avoids lock contention on the hot path
1. Model loading (the expensive operation) happens at most once

**If tools were `async def`** (calling `get_comp()` from the event loop
thread), we would need a different approach:

```python
import anyio

_comp_lock = anyio.Lock()

async def get_comp() -> RAGComponents:
    global _components
    if _components is not None:
        return _components
    async with _comp_lock:
        if _components is not None:
            return _components
        _components = await anyio.to_thread.run_sync(_build_components)
        return _components
```

But since we recommend sync `def` tools (Topic 16), `threading.Lock` is
the correct choice.

### Summary decision tree

```
Is get_comp() called from...
  ├─ worker thread (sync def tool) → threading.Lock ✓
  ├─ event loop (async def tool) → anyio.Lock + await ✓
  └─ both contexts → need two-layer approach (rare, avoid)
```

______________________________________________________________________

## Topic 18: Qdrant collection_exists caching — staleness and invalidation

### The question

If we cache `_vault_ensured = True` after first `collection_exists()` check
and collection creation, what happens if the collection is deleted externally
(user deletes `.qdrant/` directory)? Is there a Qdrant event/hook to
invalidate the cache?

### Qdrant local mode concurrency model

Qdrant local mode (`QdrantClient(path=...)`) uses **file locking** via
`portalocker` to ensure exclusive access to the storage directory. Key facts:

1. **Single-process only.** If a second `QdrantClient` tries to open the
   same path, it raises `RuntimeError("... use Qdrant server instead if you require concurrent access")`.

1. **No external modification detection.** There is no file watcher, inotify
   hook, or event system. If the `.qdrant/` directory is deleted while the
   client is running, the next operation will either:

   - Crash with an I/O error (file not found)
   - Silently create a new empty storage (depending on timing)

1. **No cache invalidation API.** `collection_exists()` is a direct filesystem
   check — there is no caching layer in the Qdrant client itself.

### Is caching safe?

**Yes, with one caveat.** Since Qdrant local mode enforces single-process
exclusive access, the only way a collection can disappear is:

1. **Our code explicitly deletes it** — `client.delete_collection()`
1. **External filesystem modification** — user deletes `.qdrant/` directory
1. **Process crash** — partial writes may corrupt storage

For case 1: We control this — invalidate cache when we delete.
For case 2: This is a catastrophic user action. No cache can protect against
filesystem-level deletion of the data directory. The client will crash on the
next operation regardless of whether we cached `_ensured`.
For case 3: Qdrant has no crash recovery in local mode. The entire storage
may be corrupt.

### Recommended caching pattern

```python
class VaultStore:
    def __init__(self, qdrant_path: str):
        self._client = QdrantClient(path=qdrant_path)
        self._vault_ensured = False
        self._code_ensured = False

    def _ensure_vault_collection(self) -> None:
        if self._vault_ensured:
            return
        if not self._client.collection_exists(self._vault_collection):
            self._client.create_collection(
                collection_name=self._vault_collection,
                vectors_config={...},
                sparse_vectors_config={...},
            )
        self._vault_ensured = True

    def _ensure_code_collection(self) -> None:
        if self._code_ensured:
            return
        if not self._client.collection_exists(self._code_collection):
            self._client.create_collection(...)
        self._code_ensured = True

    def reset_cache(self) -> None:
        """Call after delete_collection or if storage may be corrupted."""
        self._vault_ensured = False
        self._code_ensured = False
```

### Why NOT to add external invalidation

1. **No Qdrant hooks exist.** There is no event, callback, or subscription
   for collection lifecycle events in local mode.

1. **File watchers are overkill.** Adding `watchdog` or `inotify` to detect
   `.qdrant/` deletion is complex, platform-specific, and solves a problem
   that indicates a user error (deleting storage while app is running).

1. **collection_exists() is cheap.** In local mode, it's a dict lookup in
   memory (the `QdrantLocal` instance holds collections in a dict). The
   cache saves microseconds, not milliseconds. The real value is avoiding
   redundant `create_collection()` calls.

### Error handling alternative

Instead of caching, wrap operations with a try/except that resets state:

```python
def _ensure_vault_collection(self) -> None:
    if self._vault_ensured:
        return
    try:
        if not self._client.collection_exists(self._vault_collection):
            self._client.create_collection(...)
        self._vault_ensured = True
    except Exception:
        self._vault_ensured = False
        raise
```

This ensures the cache is only set on success and automatically resets on
any error (including I/O errors from deleted storage).

### Recommendation

**Cache with error-reset pattern.** The simple boolean cache is fine for
local mode. Add error handling to reset the flag on failure. Do NOT add
file watchers or periodic re-checks — they add complexity for an edge case
that already causes catastrophic failures regardless of caching.

______________________________________________________________________

## References (continued)

- threading.Lock deadlock in asyncio: <https://superfastpython.com/asyncio-use-threading-lock/>
- asyncio.Lock docs: <https://docs.python.org/3/library/asyncio-sync.html>
- anyio threading docs: <https://anyio.readthedocs.io/en/stable/threads.html>
- anyio synchronization: <https://anyio.readthedocs.io/en/stable/synchronization.html>
- anyio mixing async/sync discussion: <https://github.com/agronholm/anyio/discussions/584>
- Qdrant local mode source: <https://python-client.qdrant.tech/_modules/qdrant_client/local/qdrant_local>
- Qdrant local mode DeepWiki: <https://deepwiki.com/qdrant/qdrant-client/2.2-local-mode>
- Qdrant collection_exists issue: <https://github.com/qdrant/qdrant-client/issues/928>
- Qdrant create-if-not-exists issue: <https://github.com/qdrant/qdrant-client/issues/1022>

______________________________________________________________________

## Topic 19: search_all() score normalization — exact implementation

### The problem

`search_all()` combines vault search results (graph-boosted RRF scores in
~[0.05, 0.7]) with codebase search results (CrossEncoder logits in ~[-12, +12]).
These scores are on incompatible scales. Sorting the combined list by raw score
produces meaningless rankings.

### Sigmoid normalization for CrossEncoder logits

The standard sigmoid function maps unbounded logits to \[0, 1\]:

```python
import math

def sigmoid(x: float) -> float:
    """Map logit to [0, 1]. Numerically stable for large negative values."""
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    # For large negative x, exp(x) is safer than exp(-x)
    ex = math.exp(x)
    return ex / (1.0 + ex)
```

Properties:

- `sigmoid(0) = 0.5` (neutral midpoint)
- `sigmoid(8) ≈ 0.9997` (highly relevant CrossEncoder score)
- `sigmoid(-8) ≈ 0.0003` (irrelevant)
- Monotonic — preserves ranking order
- No parameters to tune

**Alternative:** Use `torch.nn.Sigmoid()` as `activation_fn` when constructing
the CrossEncoder to get [0, 1] scores directly from `.predict()`. This avoids
post-hoc normalization but changes the model API globally. For `search_all()`
where only the combined ranking needs normalization, post-hoc sigmoid is cleaner.

### Min-max normalization for RRF scores

```python
def min_max_normalize(scores: list[float]) -> list[float]:
    """Normalize scores to [0, 1] via min-max scaling.

    Edge cases:
    - Empty list: returns []
    - Single element: returns [1.0]
    - All same score: returns [1.0, 1.0, ...]
    """
    if not scores:
        return []
    if len(scores) == 1:
        return [1.0]
    lo = min(scores)
    hi = max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]
```

Properties:

- Maps minimum score to 0.0, maximum to 1.0
- Linear scaling — preserves relative differences
- Handles all edge cases without division by zero

### Should we normalize per-result-set or globally?

**Per-result-set (CORRECT).** Normalize each source's scores independently
before combining:

```python
# CORRECT: normalize each source separately, then combine
vault_scores_norm = min_max_normalize([r.score for r in vault_results])
code_scores_norm = [sigmoid(r.score) for r in code_results]

# Assign normalized scores back
for r, ns in zip(vault_results, vault_scores_norm):
    r.normalized_score = ns
for r, ns in zip(code_results, code_scores_norm):
    r.normalized_score = ns

# Combine and sort by normalized score
all_results = vault_results + code_results
all_results.sort(key=lambda r: r.normalized_score, reverse=True)
```

**Why not global normalization?** If you min-max across both sources combined,
one source's score distribution dominates the other. CrossEncoder logits
[-12, +12] would set the global range, compressing all RRF scores [0.05, 0.7]
into a tiny band near the middle.

This aligns with industry practice: OpenSearch's hybrid search normalizes
each sub-query's results independently using min-max before combining with
weighted arithmetic mean.

### Complete implementation for search_all()

```python
import math
from dataclasses import dataclass

@dataclass
class SearchResult:
    content: str
    path: str
    score: float
    source: str  # "vault" or "codebase"
    normalized_score: float = 0.0

def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    ex = math.exp(x)
    return ex / (1.0 + ex)

def _min_max(scores: list[float]) -> list[float]:
    if len(scores) <= 1:
        return [1.0] * len(scores)
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]

def normalize_and_combine(
    vault_results: list[SearchResult],
    code_results: list[SearchResult],
    vault_weight: float = 0.5,
    code_weight: float = 0.5,
) -> list[SearchResult]:
    """Normalize scores from heterogeneous sources and combine."""
    # Normalize vault (RRF) scores with min-max
    if vault_results:
        vault_norm = _min_max([r.score for r in vault_results])
        for r, ns in zip(vault_results, vault_norm):
            r.normalized_score = ns * vault_weight

    # Normalize codebase (CrossEncoder) scores with sigmoid
    if code_results:
        for r in code_results:
            r.normalized_score = _sigmoid(r.score) * code_weight

    combined = vault_results + code_results
    combined.sort(key=lambda r: r.normalized_score, reverse=True)
    return combined
```

### Is there a better alternative?

| Method                     | Pros                                               | Cons                                                | Use when                    |
| -------------------------- | -------------------------------------------------- | --------------------------------------------------- | --------------------------- |
| **Sigmoid + min-max**      | Simple, handles scale differences, tunable weights | Min-max sensitive to outliers                       | Default choice              |
| **Rank-based RRF on both** | No score normalization needed, robust to outliers  | Loses CrossEncoder score magnitude                  | Score magnitudes unreliable |
| **DBSF**                   | Statistically principled (mean +/- 3\*stddev)      | Only works within single Qdrant query_points() call | Intra-Qdrant fusion only    |
| **Z-score normalization**  | Handles outliers better than min-max               | Requires computing mean/stddev per query            | Large result sets (>50)     |

**Recommendation:** Sigmoid + min-max with configurable weights. It's simple,
handles the specific scale mismatch (unbounded logits vs bounded RRF), and
follows the OpenSearch best practice pattern (min-max + weighted arithmetic
mean). Start with equal weights (0.5/0.5) and tune based on quality tests.

______________________________________________________________________

## Topic 20: VaultGraph caching — safe singleton pattern

### The problem

`get_related()` in `api.py` builds a fresh `VaultGraph` on every call. This
means re-reading the graph data from disk on every request. We need a caching
pattern that:

1. Avoids redundant disk I/O
1. Invalidates after reindex (graph data changes)
1. Is thread-safe (MCP tools may call from multiple worker threads)

### Pattern: Version-stamped lazy singleton

```python
import threading
from pathlib import Path

class _GraphCache:
    """Thread-safe cached VaultGraph with version-based invalidation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._graph: VaultGraph | None = None
        self._version: int = 0  # bumped on reindex

    def get(self, graph_path: Path) -> VaultGraph:
        """Return cached graph, rebuilding if version changed."""
        if self._graph is not None:
            return self._graph
        with self._lock:
            if self._graph is not None:
                return self._graph
            self._graph = VaultGraph.from_path(graph_path)
            return self._graph

    def invalidate(self) -> None:
        """Call after reindex to force rebuild on next access."""
        with self._lock:
            self._graph = None
            self._version += 1

_graph_cache = _GraphCache()
```

### Why NOT weakref

`weakref` is for memory-pressure-driven eviction: the GC collects the object
when no strong references remain. This is the wrong semantic for VaultGraph:

- We WANT the graph to stay alive between calls (that's the whole point)
- We want explicit invalidation on reindex, not GC-driven eviction
- `weakref` would cause the graph to be re-loaded on almost every call
  if no external code holds a reference

**weakref verdict:** Do not use. It solves the wrong problem.

### When to invalidate

The cache should be invalidated in exactly one place: **after reindexing
completes**. The indexer (or the API facade that wraps it) should call
`_graph_cache.invalidate()`.

```python
# In api.py or indexer.py, after reindex:
def reindex(vault_path: Path) -> None:
    indexer.index_vault(vault_path)
    _graph_cache.invalidate()  # force graph reload on next access
```

### Is file-mtime checking worth it?

An alternative is to check the graph file's mtime on every access and
rebuild if it changed:

```python
def get(self, graph_path: Path) -> VaultGraph:
    current_mtime = graph_path.stat().st_mtime
    if self._graph is not None and self._mtime == current_mtime:
        return self._graph
    with self._lock:
        current_mtime = graph_path.stat().st_mtime
        if self._graph is not None and self._mtime == current_mtime:
            return self._graph
        self._graph = VaultGraph.from_path(graph_path)
        self._mtime = current_mtime
        return self._graph
```

**Pros:** Detects external changes (CLI reindex while MCP server runs).
**Cons:** `stat()` syscall on every access (~1-10us). Filesystem mtime
resolution is 1-2 seconds on some platforms — rapid reindex + query could
miss the change.

**Recommendation:** Use mtime checking IF the graph is stored as a file
on disk. Use version-stamped invalidation IF reindex always goes through
our API (same process). For our MCP server where reindex and search happen
in the same process, explicit invalidation is simpler and more reliable.

### Is a module-level singleton safe?

**Yes, with `threading.Lock`.** Module-level singletons in Python are
initialized once at import time. Since MCP tools run in worker threads
(Topic 16/17), the `threading.Lock` correctly serializes concurrent access.

The singleton pattern above (`_graph_cache = _GraphCache()`) is safe because:

1. Module-level instantiation is atomic (GIL protects import)
1. All mutations go through `threading.Lock`
1. `VaultGraph` is read-only after construction (no mutation during search)

### Thread safety of VaultGraph access

If `VaultGraph` is a read-only data structure after construction (typical
for graph representations), concurrent reads from multiple threads are safe
without additional locking. Only construction and invalidation need the lock.

### Summary

| Approach                               | Safe?             | Invalidation  | Overhead        | Recommended?           |
| -------------------------------------- | ----------------- | ------------- | --------------- | ---------------------- |
| No cache (rebuild every call)          | Yes               | N/A           | High disk I/O   | No                     |
| Module singleton + explicit invalidate | Yes               | After reindex | Zero per-access | **Yes (same process)** |
| Module singleton + mtime check         | Yes               | Automatic     | ~1-10us stat()  | Yes (cross-process)    |
| weakref cache                          | Unreliable        | GC-driven     | Re-loads often  | No                     |
| functools.lru_cache                    | Not invalidatable | None          | Stale forever   | No                     |

______________________________________________________________________

## References (continued)

- CrossEncoder activation_fn: <https://sbert.net/docs/cross_encoder/usage/usage.html>
- CrossEncoder API reference: <https://sbert.net/docs/package_reference/cross_encoder/cross_encoder.html>
- OpenSearch hybrid search normalization: <https://docs.opensearch.org/latest/search-plugins/search-pipelines/normalization-processor/>
- OpenSearch rank normalization overview: <https://opensearch.org/blog/how-does-the-rank-normalization-work-in-hybrid-search/>
- ms-marco-MiniLM-L6-v2 model card: <https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2>
- Python weakref docs: <https://docs.python.org/3/library/weakref.html>

______________________________________________________________________

## Topic 21: Python pathlib path normalization pitfalls

### The problem

`api.py:53` creates a new RAG engine per vault path, but `Path("./project")`
and `Path("project")` compare as unequal despite pointing to the same
location. This causes unnecessary engine recreation.

### Path comparison semantics in pathlib

Pathlib comparison is **lexical** (string-based), not filesystem-based:

```python
from pathlib import Path

Path("./project") == Path("project")        # False!
Path("project") == Path("project/")          # True  (trailing slash stripped)
Path("./a/../b") == Path("b")               # False!
Path("/foo/bar") == Path("/foo/./bar")       # False!
```

Two Path objects are equal only if their string representations are identical
after pathlib's minimal normalization (which only strips trailing separators
and collapses repeated separators).

### Path.resolve() — correct but has gotchas

`Path.resolve()` returns the canonical absolute path with all symlinks
resolved and `..`/`.` components eliminated:

```python
Path("./project").resolve() == Path("project").resolve()  # True
Path("a/../b").resolve() == Path("b").resolve()           # True
```

**Gotchas:**

1. **Follows symlinks.** If `project` is a symlink to `/elsewhere/real`,
   `Path("project").resolve()` returns `/elsewhere/real`. Two paths that
   are symlinks to different targets will compare as different even if
   the symlinks have the same name.

1. **Requires filesystem access.** `resolve()` calls `os.path.realpath()`
   which stats the filesystem. If the path doesn't exist, behavior varies:

   - Python 3.6+: resolves as far as possible, returns lexically cleaned
     remainder (no error)
   - This is fine for our use case (vault path should exist)

1. **Changes path identity through symlinks.** Given:

   ```
   /projects/my-vault -> /data/vaults/my-vault  (symlink)
   ```

   `Path("/projects/my-vault").resolve()` returns `/data/vaults/my-vault`.
   This is **correct behavior** for us — we want the canonical location.

1. **Performance.** `resolve()` does a stat() syscall per component. For a
   typical 3-5 component path, this is ~5-15us. Negligible for engine
   creation (which loads GPU models taking seconds).

### Alternative: os.path.normpath + absolute

If you want lexical normalization WITHOUT following symlinks:

```python
from pathlib import Path
import os

def normalize_path(p: Path) -> Path:
    """Normalize path lexically without resolving symlinks."""
    return Path(os.path.normpath(os.path.abspath(p)))

normalize_path(Path("./project")) == normalize_path(Path("project"))  # True
normalize_path(Path("a/../b")) == normalize_path(Path("b"))           # True
```

This handles `.` and `..` components but does NOT follow symlinks. If two
symlinks point to the same target, they will compare as different.

### Recommendation for api.py

**Use `Path.resolve()`** for the cache key:

```python
class RAGEngineCache:
    def __init__(self) -> None:
        self._engines: dict[Path, RAGEngine] = {}

    def get_or_create(self, vault_path: Path) -> RAGEngine:
        key = vault_path.resolve()
        if key not in self._engines:
            self._engines[key] = RAGEngine(key)
        return self._engines[key]
```

Why `resolve()` over `normpath`:

- We WANT symlink resolution — two symlinks to the same vault should share
  one engine
- The vault path must exist (we're about to read from it), so resolve()
  always succeeds
- The one-time cost (~10us) is negligible vs engine creation (seconds)

### On Windows specifically

`Path.resolve()` on Windows also normalizes drive letter case and UNC paths.
`Path("c:/foo")` and `Path("C:/foo")` resolve to the same canonical form.
This is relevant for our Windows development environment.

______________________________________________________________________

## Topic 22: SHA-256 vs xxHash for file change detection

### The question

For `VaultIndexer` switching from mtime to content hash: is SHA-256 overkill?
Is xxHash meaningfully faster? What are the tradeoffs?

### Performance comparison

| Algorithm | Throughput (GB/s) | Relative | Stdlib?             | Collision risk  |
| --------- | ----------------- | -------- | ------------------- | --------------- |
| xxh64     | ~19.4             | **65x**  | No (PyPI `xxhash`)  | 2^-64 per pair  |
| xxh128    | ~18.0             | 60x      | No (PyPI `xxhash`)  | 2^-128 per pair |
| blake2b   | ~1.0              | 3.3x     | **Yes** (`hashlib`) | Cryptographic   |
| sha256    | ~0.3              | 1x       | **Yes** (`hashlib`) | Cryptographic   |

Python benchmark (1 GiB data, Python 3.11):

- xxh64: **0.096s** (10,670 MiB/s)
- sha256: **0.541s** (1,893 MiB/s)
- Ratio: xxh64 is **~5.6x faster** in Python (less than C due to binding overhead)

### Is SHA-256 overkill?

**Yes.** For file change detection:

- We don't need cryptographic security (no adversary crafting collisions)
- We need speed (hashing potentially hundreds of files on every reindex check)
- We need determinism (same content = same hash, always)
- We need low collision probability (but 2^-64 is more than sufficient)

SHA-256's security properties (preimage resistance, collision resistance
against adversaries) are irrelevant for change detection.

### Is xxhash available in stdlib?

**No.** `xxhash` is an external PyPI package (e.g. `uv add xxhash`). It's
a C extension with no pure-Python fallback. This adds a dependency.

### The stdlib alternative: hashlib.blake2b

BLAKE2b is:

- In stdlib (`hashlib.blake2b()`)
- ~3x faster than SHA-256
- Cryptographic (overkill but not a downside)
- Supported by `hashlib.file_digest()` (Python 3.11+)

```python
import hashlib

def file_hash(path: str) -> str:
    """Hash file contents using blake2b (stdlib, fast)."""
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "blake2b").hexdigest()
```

`hashlib.file_digest()` (Python 3.11+) handles chunked reading internally
with optimal block sizes. No need to manually loop with `read(8192)`.

### Recommendation

**Use `hashlib.blake2b` via `file_digest()`.** Reasoning:

1. **No new dependency.** blake2b is in stdlib. xxhash needs an external PyPI install.
1. **Fast enough.** At ~1 GB/s, hashing 213 markdown files (typical vault,
   ~1-10 KB each) takes \<1ms total. The 5.6x speedup of xxhash saves
   microseconds — irrelevant.
1. **file_digest() is clean.** One-liner, optimal block size, Python 3.11+
   (we require 3.13).
1. **Future-proof.** If we later need xxhash for multi-GB codebases, it's a
   drop-in replacement (same API pattern).

```python
import hashlib
from pathlib import Path

def content_hash(path: Path) -> str:
    """Compute blake2b hash of file contents for change detection."""
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "blake2b").hexdigest()

# For comparing sets of files (e.g., vault directory):
def directory_hash(paths: list[Path]) -> str:
    """Hash all file contents + paths for directory change detection."""
    h = hashlib.blake2b()
    for p in sorted(paths):  # sort for deterministic order
        h.update(str(p).encode())
        with open(p, "rb") as f:
            while chunk := f.read(65536):
                h.update(chunk)
    return h.hexdigest()
```

### When xxhash IS worth it

- Hashing files >100 MB (e.g., large binary assets, database dumps)
- Hashing thousands of files where total size exceeds ~1 GB
- Hot-path hashing in a loop (e.g., streaming change detection)

For our vault of 213 markdown docs (~1-50 KB each), blake2b finishes in
well under 10ms. Not worth adding a dependency.

______________________________________________________________________

## References (continued)

- pathlib lexical normalization CPython issue: <https://github.com/python/cpython/issues/124825>
- pathlib resolve() gotchas blog: <https://pydev.blogspot.com/2025/01/using-or-really-misusing-pathresolve-in.html>
- pathlib normalize issue: <https://bugs.python.org/issue38924>
- pathlib symlink resolution issue: <https://bugs.python.org/issue25012>
- os.path.normpath guide: <https://thelinuxcode.com/python-ospathnormpath-in-practice-a-deep-guide-to-safer-cleaner-cross-platform-path-handling/>
- xxHash performance wiki: <https://github.com/Cyan4973/xxHash/wiki/Performance-comparison>
- xxhash Python package: <https://pypi.org/project/xxhash/>
- Python hash benchmark: <https://github.com/FRex/pyhashbench>
- hashlib file_digest docs: <https://docs.python.org/3/library/hashlib.html>
- BLAKE2 performance claims: <https://docs.python.org/3/library/hashlib.html#blake2>

______________________________________________________________________

## Topic 23: FastMCP sync tool return type handling

### The question

When converting MCP tools from `async def` to `def` (per Topic 16), do return
types or exception handling change?

### Return type handling: sync = async (no difference)

FastMCP treats sync and async tools identically for return values. From the
official docs: "FastMCP supports both asynchronous (async def) and synchronous
(def) functions as tools" with no differences in return value processing.

Sync tools automatically run in a threadpool: "Synchronous tools automatically
run in a threadpool to avoid blocking the event loop."

### Supported return types

All of these work identically for sync and async tools:

| Return type                        | Behavior                                                            |
| ---------------------------------- | ------------------------------------------------------------------- |
| `str`                              | Text content                                                        |
| `int`, `float`, `bool`             | Primitive content                                                   |
| `dict`                             | Structured content (JSON) -- **always**, even without output schema |
| Pydantic `BaseModel`               | Structured content (JSON) -- **always**                             |
| `dataclass`                        | Structured content (JSON) -- **always**                             |
| `list[T]`, `set[T]`                | Collection content                                                  |
| `None`                             | Empty response                                                      |
| `datetime`, `date`, `UUID`, `Path` | Serialized appropriately                                            |
| `Image`, `Audio`, `File`           | Media content                                                       |

**Key finding:** Object-like returns (dict, Pydantic models, dataclasses)
**always** become structured content with machine-readable JSON, even without
an explicit `output_schema`. Clients can deserialize back to Python objects.

For our MCP tools that return search results, returning a Pydantic model or
dict works directly -- no need to manually serialize to JSON string.

### Exception handling: automatic

FastMCP catches ALL exceptions from tools (sync and async) and converts them
to MCP error responses:

1. **Regular exceptions** -- caught, logged, converted to error response.
   If `mask_error_details=True`, internal details are hidden from clients.

1. **`ToolError`** -- special exception whose message is ALWAYS sent to the
   client, regardless of `mask_error_details`. Use this for user-facing errors:

   ```python
   from fastmcp import ToolError

   @mcp.tool()
   def search_vault(query: str) -> dict:
       if not query.strip():
           raise ToolError("Query cannot be empty")
       # ... search logic
   ```

1. **Pydantic ValidationError** -- currently mapped to Internal error (-32603)
   instead of Invalid params (-32602). Known issue in FastMCP.

### Recommendation for our conversion

Converting `async def` to `def` requires **zero changes** to:

- Return types (keep returning dicts, Pydantic models, or strings)
- Exception handling (keep raising regular exceptions or ToolError)
- Type annotations (FastMCP generates JSON schema from them identically)

The only change is removing `async` and `await`:

```python
# BEFORE (async, blocks event loop)
@mcp.tool()
async def search_codebase(query: str, top_k: int = 5) -> SearchResponse:
    results = searcher.search_codebase(query, top_k=top_k)
    return SearchResponse(results=results)

# AFTER (sync, auto-threaded, identical behavior)
@mcp.tool()
def search_codebase(query: str, top_k: int = 5) -> SearchResponse:
    results = searcher.search_codebase(query, top_k=top_k)
    return SearchResponse(results=results)
```

______________________________________________________________________

## Topic 24: Qdrant hybrid search with optional sparse vector

### The question

If `sparse_vector=None` is passed to the search function, should we still
include a sparse prefetch branch in `query_points`? What's the correct way
to handle dense-only search?

### Qdrant query_points without prefetch (dense-only)

`query_points` works perfectly without `prefetch`:

```python
# Dense-only search -- no prefetch, no fusion
results = client.query_points(
    collection_name="vault",
    query=dense_vector,        # direct vector query
    using="dense",             # named vector
    limit=10,
    with_payload=True,
)
```

When `prefetch` is omitted, `query_points` performs a direct nearest-neighbor
search on the specified named vector. No fusion is needed or possible.

### FusionQuery with single prefetch -- technically works but pointless

```python
# Single prefetch + RRF -- technically valid but wasteful
results = client.query_points(
    collection_name="vault",
    prefetch=[
        models.Prefetch(query=dense_vector, using="dense", limit=20),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
)
```

This works (no error) but adds unnecessary overhead. RRF with a single source
simply assigns `1/(k+rank)` scores -- equivalent to re-ranking by the original
score. Pointless extra computation.

### What happens if sparse_vector is None in a prefetch

You **cannot** pass `None` as the `query` in a Prefetch:

```python
# THIS WILL ERROR
models.Prefetch(query=None, using="sparse", limit=20)  # ValueError/TypeError
```

The `query` field in Prefetch expects a vector (dense or sparse). Passing
`None` is not a "skip this branch" signal -- it's an invalid argument.

### Correct pattern: conditional prefetch construction

Build the prefetch list dynamically based on available vectors:

```python
def hybrid_search(
    client: QdrantClient,
    collection: str,
    dense_vector: list[float],
    sparse_vector: models.SparseVector | None = None,
    limit: int = 10,
    query_filter: models.Filter | None = None,
) -> list[models.ScoredPoint]:
    """Search with hybrid (dense+sparse) or dense-only fallback."""

    if sparse_vector is not None:
        # Hybrid search: two prefetch branches + RRF fusion
        prefetches = [
            models.Prefetch(
                query=dense_vector,
                using="dense",
                limit=limit * 2,
                filter=query_filter,
            ),
            models.Prefetch(
                query=sparse_vector,
                using="sparse",
                limit=limit * 2,
                filter=query_filter,
            ),
        ]
        results = client.query_points(
            collection_name=collection,
            prefetch=prefetches,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
    else:
        # Dense-only fallback: direct query, no prefetch/fusion
        results = client.query_points(
            collection_name=collection,
            query=dense_vector,
            using="dense",
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )

    return results.points
```

### Key design decisions

1. **Dense-only uses direct query, not single-prefetch + fusion.** Simpler,
   faster, identical results.

1. **Sparse-only is not a supported path.** Dense embeddings are always
   available (our `EmbeddingModel` always produces them). Sparse may be
   unavailable if SPLADE fails or is disabled.

1. **The `if/else` is in the store layer, not the caller.** The search API
   accepts `sparse_vector: SparseVector | None` and handles the branching
   internally. Callers don't need to know about prefetch mechanics.

1. **Filter placement differs.** With prefetch, filters go on each `Prefetch`
   (per Topic 10). Without prefetch, filter goes on `query_filter` at top level.

### Our codebase status

**store.py** should implement this pattern: check if `sparse_vector` is None,
and if so, fall back to dense-only `query_points` without prefetch/fusion.
This handles the R26-M5 edge case where sparse encoding fails or is disabled.

______________________________________________________________________

## References (continued)

- FastMCP tools documentation: <https://gofastmcp.com/servers/tools>
- FastMCP ToolError handling: <https://github.com/jlowin/fastmcp/issues/1606>
- MCP SDK tool system: <https://deepwiki.com/modelcontextprotocol/python-sdk/2.2-tool-system>
- Qdrant query_points API reference: <https://api.qdrant.tech/api-reference/search/query-points>
- Qdrant hybrid queries docs: <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- Qdrant local mode prefetch issue: <https://github.com/qdrant/qdrant-client/issues/713>

______________________________________________________________________

## Topic 25: Late interaction / ColBERT vs our CrossEncoder reranker

### The question

Is `cross-encoder/ms-marco-MiniLM-L6-v2` still state-of-the-art for reranking
in 2025/2026? Are there better alternatives for code search?

### Current reranker landscape (2025-2026)

| Model                  | Params | BEIR nDCG@10             | CoIR (code) | Latency       | License    |
| ---------------------- | ------ | ------------------------ | ----------- | ------------- | ---------- |
| ms-marco-MiniLM-L6-v2  | 22M    | ~49-51                   | N/A         | ~1ms/pair CPU | Apache 2.0 |
| bge-reranker-v2-m3     | 568M   | ~60 (+11 over retriever) | N/A         | ~50-100ms GPU | Apache 2.0 |
| jina-reranker-v2-base  | 278M   | ~57                      | ~63         | ~30ms GPU     | Apache 2.0 |
| jina-reranker-v3       | 600M   | **61.94**                | **70.64**   | ~50ms GPU     | Apache 2.0 |
| NV-RerankQA-Mistral-4B | 4B     | **~74** (best)           | N/A         | ~200ms GPU    | Custom     |

### Key findings

1. **ms-marco-MiniLM-L6-v2 is dated.** It was SOTA in 2021. Current models
   outperform it by 10-25 NDCG points on BEIR. It's a 22M param, 6-layer
   model trained only on MS MARCO passage ranking. No code-specific training.

1. **bge-reranker-v2-m3 is the current open-source sweet spot.** 568M params,
   +11 NDCG points over retriever baseline on BEIR, multilingual, Apache 2.0.
   Runs efficiently on consumer GPUs (~50-100ms per query batch).

1. **jina-reranker-v3 leads on code retrieval.** 70.64 on CoIR (Code
   Information Retrieval benchmark), 61.94 BEIR nDCG@10. Uses a novel "last
   but not late interaction" architecture (hybrid of cross-encoder and
   ColBERT). 0.6B params, Apache 2.0.

1. **ColBERT architecture.** Late interaction models compute token-level
   similarities, achieving 180x fewer FLOPs than full cross-encoders at k=10.
   Jina-ColBERT-v2 supports 8192 tokens (vs 512 for standard cross-encoders).
   Better for long code chunks. However, requires precomputing document token
   embeddings, adding storage overhead.

1. **LLM-based reranking (GPT-4, etc.)** provides 5-8% higher accuracy on
   listwise tasks but adds 4-6 seconds latency. Impractical for real-time
   search (users abandon after 3s).

### Our stack assessment

**ms-marco-MiniLM-L6-v2 is the weakest link in our pipeline.** It was a
reasonable choice for prototyping, but:

- No code-specific training
- 22M params vs 568M-600M for modern rerankers
- ~10-20 NDCG points behind current SOTA on general benchmarks
- No CoIR benchmark data (likely poor on code retrieval)

### Recommended upgrade path

**Phase 1 (immediate, low risk):** Replace with `BAAI/bge-reranker-v2-m3`.

- Drop-in replacement via sentence-transformers CrossEncoder API
- ~11 NDCG point improvement on general retrieval
- 568M params, fits easily on RTX 4080 SUPER alongside Qwen3
- Apache 2.0, no licensing concerns

**Phase 2 (future, if code quality matters):** Evaluate `jina-reranker-v3`.

- Best known code retrieval score (70.64 CoIR)
- Uses late interaction architecture (different API)
- 0.6B params, similar VRAM footprint
- Requires different integration than CrossEncoder.predict()

### Impact assessment

**MEDIUM-HIGH.** The reranker is the quality-critical post-retrieval step.
Upgrading from MiniLM-L6-v2 to bge-reranker-v2-m3 is the single highest-ROI
change for retrieval quality. It's a model swap, not an architecture change.

______________________________________________________________________

## Topic 26: Hybrid retrieval quality -- sparse model choices

### The question

Is SPLADE-v3 still the best sparse encoder? Does sparse retrieval add value
for code search specifically?

### Sparse encoder landscape (2025-2026)

| Model            | Architecture            | Strengths                                 | Weaknesses                              |
| ---------------- | ----------------------- | ----------------------------------------- | --------------------------------------- |
| BM25             | Statistical (TF-IDF)    | Zero-cost, interpretable                  | No semantic expansion, exact match only |
| SPLADE-v3        | Neural (BERT-based)     | Learned term expansion, semantic matching | 256 token limit, GPU required           |
| SPLADE-v3-distil | Distilled SPLADE        | Faster inference, similar quality         | Slightly lower accuracy                 |
| UniCOIL          | Single-weight per token | Efficient                                 | Less expansion than SPLADE              |
| BM42 (Qdrant)    | Modified BM25           | Qdrant-native, no GPU                     | Lower quality than SPLADE               |

### SPLADE-v3 vs BM25 for code

**SPLADE advantages for code search:**

1. **Term expansion.** A query for "binary search" expands to include
   "bisect", "sorted", "find", "algorithm". BM25 requires exact keyword
   match.
1. **Term weighting.** SPLADE downweights common tokens ("def", "return",
   "self") and upweights distinctive identifiers. BM25's IDF does this
   partially but less effectively.
1. **Handling abbreviations.** Code uses abbreviations heavily (cfg, ctx,
   fmt, iter). SPLADE's BERT backbone can relate these to their full forms.

**BM25 advantages for code search:**

1. **Exact identifier matching.** When searching for `_collect_chunks`, BM25
   matches it exactly. SPLADE may dilute this with expanded terms.
1. **No GPU required.** BM25 runs anywhere.
1. **No 256-token limit.** BM25 processes arbitrarily long documents.

### Does sparse add value in our hybrid pipeline?

**Yes, meaningfully.** The hybrid (dense + sparse) approach is consensus
best practice in 2025-2026 retrieval. Key evidence:

1. Dense embeddings alone miss exact keyword matches (function names, class
   names, error messages, config keys).
1. Sparse alone misses semantic similarity (different words, same concept).
1. RRF fusion of both consistently outperforms either alone on BEIR and
   MS MARCO benchmarks.
1. For code specifically, exact identifier matching is critical -- users
   often search for specific function/variable names.

### SPLADE-v3 assessment for our stack

**SPLADE-v3 remains the best available sparse encoder.** No successor has
been released. The main alternatives are:

- BM25: lower quality but no GPU needed
- BM42: Qdrant-native but lower quality
- SPLADE-v3-distil: slightly faster, slightly lower quality

**The 256-token limit is the main weakness.** For code chunks that exceed
~800-1000 characters, the tail of the document is silently truncated by
SPLADE's BERT tokenizer. Our pre-truncation at 8000 chars (embeddings.py
line 289) provides a safety net, but the effective sparse coverage is only
the first ~256 tokens of each chunk.

### Recommendation

**Keep SPLADE-v3.** No change needed. It's the best available sparse encoder
for our GPU-required stack. The 256-token limit is a known trade-off, but
the alternative (BM25) would mean giving up learned term expansion.

**Potential future improvement:** If Qdrant adds native BM25 scoring on
payload text fields, consider adding BM25 as a third retrieval branch
alongside dense + SPLADE. This would catch long-tail exact matches that
SPLADE truncates.

______________________________________________________________________

## Topic 27: Chunking strategy quality for code RAG

### The question

How does our AST-based chunking compare to the latest research? Are there
better strategies?

### cAST: the 2025 state of the art (EMNLP 2025 Findings)

The **cAST** paper (Chunking via Abstract Syntax Tree) is the most relevant
recent work. Published at EMNLP 2025 Findings, it directly addresses code
RAG chunking quality.

**Algorithm:**

1. Parse source code to AST via tree-sitter
1. Top-down traversal: fit large AST nodes into single chunks when possible
1. If a node exceeds size budget, recursively split into child nodes
1. Greedily merge adjacent small sibling nodes to maximize density
1. Concatenating all chunks reproduces the original file verbatim

**Results vs baselines:**

| Strategy                | Recall@5 (RepoEval) | Pass@1 (SWE-bench) | EM (CrossCodeEval) |
| ----------------------- | ------------------- | ------------------ | ------------------ |
| Fixed-size (line-based) | 82.1                | 13.7               | 36.3               |
| cAST (AST-aware)        | **83.9 (+1.8)**     | **16.3 (+2.6)**    | **39.9 (+3.6)**    |

**Design goals (all four apply to our chunker):**

1. Syntactic integrity -- chunk boundaries align with complete syntactic units
1. High information density -- pack chunks up to a size budget
1. Language invariance -- no language-specific heuristics
1. Plug-and-play -- concatenating chunks reproduces original

**Languages tested:** Python, Java, C#, TypeScript.

### Comparison with our ASTChunker

Our `ASTChunker` in indexer.py already implements the core cAST pattern:

- Uses tree-sitter for parsing
- Chunks at function/class level (top-level syntactic units)
- Merges small adjacent chunks (`_merge_small()`)
- Works across multiple languages

**Where our chunker aligns with cAST:**

- AST-aware boundary detection (not line-based)
- Greedy merging of small siblings
- tree-sitter based, language-agnostic

**Where our chunker may differ from cAST:**

1. **Recursive splitting.** cAST recursively splits large nodes (e.g., a
   1000-line class) into child-level chunks. Our chunker may keep large
   top-level nodes as single chunks, exceeding the size budget.

1. **Size budget enforcement.** cAST strictly enforces a maximum chunk size
   (measured in non-whitespace characters). Our `_merge_small()` has a
   minimum threshold but may not have a maximum.

1. **Completeness guarantee.** cAST guarantees that concatenating all chunks
   reproduces the original file. Our chunker may skip non-top-level nodes
   (comments between functions, module-level assignments) that aren't in
   `_TOP_LEVEL_NODES`.

### Other approaches in the literature

1. **Sliding window over AST.** Overlapping chunks at function boundaries.
   Increases recall at cost of storage. Not well-studied for code.

1. **Repo-level context.** Including import context, class hierarchy, or
   call graph information in each chunk's metadata. Improves generation
   quality but not directly retrieval quality.

1. **Semantic chunking.** Using embeddings to find natural "topic breaks"
   in code. Works for prose, poorly studied for code.

1. **Call-graph augmentation.** Adding edges between chunks that call each
   other. Our `VaultGraph` link boosting partially does this for vault
   documents (backlinks), but not for code.

### Recommendations

1. **No architecture change needed.** Our AST-based approach is aligned with
   the 2025 SOTA (cAST). The +1.8 Recall@5 improvement from cAST over
   fixed-size chunking is already captured by our approach.

1. **Consider adding recursive splitting.** If large classes/modules produce
   oversized chunks, add cAST-style recursive descent into child nodes.
   Check if `_merge_small()` has a maximum size enforcement.

1. **Consider completeness guarantee.** If module-level code (assignments,
   imports, top-level expressions) is skipped by our chunker, it won't be
   searchable. cAST guarantees full file coverage.

1. **Low priority.** The chunking gains (+1.8 Recall@5) are modest compared
   to reranker upgrades (+10-20 NDCG points). Focus on the reranker first.

______________________________________________________________________

## References (continued)

- ZeroEntropy reranker guide: <https://www.zeroentropy.dev/articles/ultimate-guide-to-choosing-the-best-reranking-model-in-2025>
- Jina reranker v3 paper: <https://arxiv.org/abs/2509.25085>
- Jina reranker v3 model card: <https://huggingface.co/jinaai/jina-reranker-v3>
- BGE reranker v2: <https://huggingface.co/BAAI/bge-reranker-base>
- Reranker RAG comparison: <https://www.analyticsvidhya.com/blog/2025/06/top-rerankers-for-rag/>
- Reranker benchmark paper: <https://arxiv.org/html/2409.07691v1>
- BSWEN reranker comparison 2026: <https://docs.bswen.com/blog/2026-02-25-best-reranker-models/>
- cAST paper (EMNLP 2025): <https://arxiv.org/abs/2506.15655>
- cAST full text: <https://arxiv.org/html/2506.15655v1>
- SPLADE overview (Pinecone): <https://www.pinecone.io/learn/splade/>
- SPLADE vs BM25 (Zilliz): <https://zilliz.com/learn/comparing-splade-sparse-vectors-with-bm25>
- Qdrant modern sparse retrieval: <https://qdrant.tech/articles/modern-sparse-neural-retrieval/>
- SPLADE billion-scale efficiency: <https://arxiv.org/pdf/2511.22263>
- Jina ColBERT v2: <https://arxiv.org/html/2408.16672v2>
- CoIR code retrieval benchmark: <https://jina.ai/models/jina-reranker-v3/>

______________________________________________________________________

## Topic 28 — qdrant-client API Grounding (Round 1)

**Installed version:** qdrant-client 1.17.0

### Verified API Signatures (from installed package introspection)

#### `query_points()`

```
collection_name: str
query: Union[list[float], SparseVector, list[list[float]], int, str, UUID,
             Document, Image, InferenceObject, NearestQuery, RecommendQuery,
             DiscoverQuery, ContextQuery, OrderByQuery, FusionQuery, RrfQuery,
             FormulaQuery, SampleQuery, RelevanceFeedbackQuery, None] = None
using: Optional[str] = None
prefetch: Union[Prefetch, list[Prefetch], None] = None
query_filter: Optional[Filter] = None
limit: int = 10
offset: Optional[int] = None
with_payload: Union[bool, Sequence[str], ...] = True
with_vectors: Union[bool, Sequence[str]] = False
score_threshold: Optional[float] = None
```

**Our usage (store.py:562-567):** CORRECT. Uses `prefetch=prefetch, query=FusionQuery(fusion=Fusion.RRF), limit=limit`.

**Note on `query_filter` with prefetch:** Per Qdrant docs, when prefetch is used, top-level `query_filter` only applies to the main query stage (which is the fusion), not the prefetch stage. Our code correctly puts `filter=query_filter` on each `Prefetch` individually (store.py:544, 558). The fallback dense-only path (store.py:580) correctly uses top-level `query_filter` since there's no prefetch.

#### `Prefetch` model

```
prefetch: Union[list[Prefetch], Prefetch, None] = None
query: Union[list[float], SparseVector, ..., None] = None
using: Optional[str] = None
filter: Optional[Filter] = None          # <-- NOT query_filter
params: Optional[SearchParams] = None
score_threshold: Optional[float] = None
limit: Optional[int] = None
lookup_from: Optional[LookupLocation] = None
```

**Our usage (store.py:540-558):** CORRECT. Uses `filter=query_filter` which maps to the `filter` field.

#### `FusionQuery` vs `RrfQuery`

- `FusionQuery(fusion: Fusion)` — basic, no tuning parameters. `Fusion.RRF` and `Fusion.DBSF` are the enum values.
- `RrfQuery(rrf: Rrf)` — newer (v1.16.0+), supports `Rrf(k: Optional[int], weights: Optional[list[float]])`.

**Our usage (store.py:565):** Uses `FusionQuery(fusion=Fusion.RRF)`. This is VALID but uses the older API. `RrfQuery` allows tuning `k` (default 2 in standard RRF) and per-prefetch `weights`. Not a bug, but an optimization opportunity.

#### `scroll()`

```
collection_name: str
scroll_filter: Optional[Filter] = None   # <-- NOT query_filter
limit: int = 10
order_by: Optional[Union[str, OrderBy]] = None
offset: Optional[Union[int, str, UUID]] = None
with_payload: Union[bool, Sequence[str], ...] = True
with_vectors: Union[bool, Sequence[str]] = False
```

**Our usage (store.py:372-378, 411-418, 488-494):** CORRECT. Uses `scroll_filter=scroll_filter` (the correct param name), `with_payload=[id_field]` or `True`, `with_vectors=False`.

#### `create_payload_index()`

```
collection_name: str
field_name: str
field_schema: Optional[Union[PayloadSchemaType, KeywordIndexParams, IntegerIndexParams,
                             FloatIndexParams, GeoIndexParams, TextIndexParams,
                             BoolIndexParams, DatetimeIndexParams, UuidIndexParams,
                             PayloadIndexParams]] = None
```

**PayloadSchemaType enum values:** BOOL, DATETIME, FLOAT, GEO, INTEGER, KEYWORD, TEXT, UUID.

**Our usage (store.py:199-202, 220-223):** CORRECT. Uses `PayloadSchemaType.KEYWORD` for string fields (`doc_type`, `feature`, `path`, `language`, `function_name`, `class_name`).

#### `SparseVector`

```
indices: list[int]    # required
values: list[float]   # required
```

**Our usage (store.py:246-248, 293-295, 551-553):** CORRECT. Constructs `SparseVector(indices=list(...), values=list(...))`.

#### `MatchValue` / `MatchText` / `MatchAny`

- `MatchValue(value: bool | int | str)` — exact equality match on keyword/integer/bool fields
- `MatchText(text: str)` — full-text search with tokenization. **Requires a full-text index** (PayloadSchemaType.TEXT) to work properly. Without it, falls back to substring matching.
- `MatchAny(any: list[str] | list[int])` — IN operator, matches if stored value is in the list

### Discrepancies Found

#### D28-1: `_build_code_filter` uses `MatchText` for path prefix — WRONG SEMANTICS (store.py:718-723)

```python
if key == "path" and value.endswith("/"):
    conditions.append(
        models.FieldCondition(
            key="path",
            match=models.MatchText(text=value),
        )
    )
```

`MatchText` performs full-text search with tokenization. For `path` values like `"src/vaultspec_rag/"`, tokenization will split on `/` and match any document containing tokens `"src"`, `"vaultspec_rag"`, etc. independently. This could return false positives (e.g., a file at `"tests/vaultspec_rag/foo.py"` matching `"src/vaultspec_rag/"`).

Worse: there is no TEXT index on the `path` field — only a KEYWORD index (store.py:220-223). Without a TEXT index, `MatchText` falls back to basic substring matching, which might actually work for prefix-like behavior but is undocumented and unreliable.

**Correct fix:** Use Qdrant's `MatchValue` with the exact path, or if prefix matching is truly needed, use `MatchText` with a properly created TEXT index on `path`. Alternative: store a `path_prefix` payload field and use `MatchValue`.

**Severity:** MEDIUM — the KEYWORD index + MatchText mismatch is semantically wrong even if it happens to work in some cases.

#### D28-2: `FusionQuery` is functional but `RrfQuery` is preferred (store.py:565, 635)

Not a bug. `FusionQuery(fusion=Fusion.RRF)` works but cannot tune the RRF constant `k` or set per-prefetch weights. `RrfQuery(rrf=Rrf(k=60))` is the newer API available since v1.16.0 (we have v1.17.0).

**Severity:** LOW — optimization opportunity, not a correctness issue.

#### D28-3: No discrepancies in core APIs

The following are all verified CORRECT against the installed qdrant-client 1.17.0:

- `create_collection()` with `vectors_config` dict + `sparse_vectors_config` dict
- `SparseVectorParams()` construction (no required args)
- `VectorParams(size=, distance=)` construction
- `upsert(collection_name=, points=)` with `PointStruct` list
- `delete()` with `PointIdsList(points=)` selector
- `retrieve(collection_name=, ids=, with_payload=, with_vectors=)`
- `count(collection_name=).count` attribute access
- `collection_exists(name)` call

### Sources

- Installed package introspection: qdrant-client 1.17.0
- Qdrant hybrid queries docs: <https://qdrant.tech/documentation/concepts/hybrid-queries/>
- Qdrant filtering docs: <https://qdrant.tech/documentation/concepts/filtering/>
- Qdrant payload docs: <https://qdrant.tech/documentation/concepts/payload/>

______________________________________________________________________

## Topic 29 — sentence-transformers API Grounding (Round 2)

**Installed version:** sentence-transformers 5.2.3

### SentenceTransformer.encode()

```
sentences: str | list[str] | np.ndarray
prompt_name: str | None = None
prompt: str | None = None
batch_size: int = 32
show_progress_bar: bool | None = None
output_value: Literal['sentence_embedding', 'token_embeddings'] | None = 'sentence_embedding'
precision: Literal['float32', 'int8', 'uint8', 'binary', 'ubinary'] = 'float32'
convert_to_numpy: bool = True
convert_to_tensor: bool = False
normalize_embeddings: bool = False
truncate_dim: int | None = None
```

**Our usage:**

- `encode_documents` (embeddings.py:236-241): `encode(truncated, batch_size=..., show_progress_bar=..., normalize_embeddings=True)` — CORRECT. No `prompt_name` for documents is correct for Qwen3 (verified in Topic 12).
- `encode_query` (embeddings.py:267-271): `encode([query], prompt_name="query", normalize_embeddings=True)` — CORRECT. Qwen3 uses `prompt_name="query"` for queries.

### SparseEncoder

**Methods available:**

- `encode()` — generic encoding, no automatic prompt selection
- `encode_query()` — auto-sets `prompt_name="query"` if prompts dict has "query" key, passes `task="query"`
- `encode_document()` — auto-sets `prompt_name` from `["document", "passage", "corpus"]` candidates, passes `task="document"`

**SPLADE-v3 prompts:** `{'query': '', 'document': ''}` — both are empty strings. Therefore `encode()`, `encode_query()`, and `encode_document()` produce identical output for SPLADE-v3.

**Our usage (embeddings.py:293, 319):** Uses plain `encode()` for both documents and queries. This is CORRECT for SPLADE-v3 since its prompts are empty. If the sparse model were ever changed to one with non-empty prompts (e.g., a future SPLADE variant), the code would need to switch to `encode_query()`/`encode_document()`.

**Severity:** NO BUG — but worth noting as a future-proofing concern.

### SparseEncoder.**init**()

```
model_name_or_path: str | None = None
device: str | None = None
model_kwargs: dict[str, Any] | None = None
tokenizer_kwargs: dict[str, Any] | None = None
```

**Our usage (embeddings.py:186-189):** `SparseEncoder(sparse_name, device="cuda", model_kwargs={"torch_dtype": torch.float16})` — CORRECT. `model_kwargs` is passed through to `AutoModelForMaskedLM.from_pretrained(**model_args)`. `torch.float16` (the dtype object) is the correct type, not the string `"float16"`. The R22b-m13 audit finding was incorrect — our code already passes the dtype object.

### CrossEncoder.predict()

```
sentences: list[tuple[str, str]] | list[list[str]] | tuple[str, str] | list[str]
batch_size: int = 32
activation_fn: Callable | None = None
apply_softmax: bool = False
convert_to_numpy: bool = True
convert_to_tensor: bool = False
```

**Returns:** numpy array of scores (when `convert_to_numpy=True`, which is the default).

**Our usage (search.py:229-230):**

```python
pairs = [(query, r.snippet) for r in results]
scores = reranker.predict(pairs, batch_size=32)
```

CORRECT. Passes `list[tuple[str, str]]` which matches the signature. `batch_size=32` matches the default. Return type is `np.ndarray` of floats (logits for ms-marco models).

### CrossEncoder.rank()

Also available (sentence-transformers 5.x):

```
query: str
documents: list[str]
top_k: int | None = None
return_documents: bool = False
batch_size: int = 32
```

Our code uses `predict()` directly instead of `rank()`. Both are valid — `rank()` is a convenience wrapper that internally calls `predict()` and sorts. Our manual predict+sort in `_rerank()` is equivalent.

### CrossEncoder initialization

**Our usage (search.py:211):** `CrossEncoder(self._reranker_model_name, device="cuda")` — CORRECT. CrossEncoder.**init** accepts `model_name_or_path` and `device` parameters.

### Discrepancies Found

**None.** All sentence-transformers API usage in embeddings.py and search.py is correct against the installed v5.2.3.

### Notes for Future

- If upgrading reranker to `BAAI/bge-reranker-v2-m3`, it loads as a `CrossEncoder` with the same API. Drop-in replacement confirmed.
- `SparseEncoder.encode_query()` / `encode_document()` would become relevant if switching to a sparse model with non-empty prompts.

### Sources

- Installed package introspection: sentence-transformers 5.2.3
- SPLADE-v3 cached config: `config_sentence_transformers.json` prompts field

______________________________________________________________________

## Topic 30 — MCP SDK API Grounding (Round 3)

**Installed version:** mcp 1.26.0 (FastMCP is bundled as `mcp.server.fastmcp`)

### CRITICAL CORRECTION: MCP 1.26.0 does NOT auto-wrap sync tools

**Previous finding (Topic 16, ADR `docs/adr/2026-03-07-mcp-sync-tools.md`)** stated that the MCP SDK auto-wraps sync `def` tools in `anyio.to_thread.run_sync()`. This was based on PR #1909 discussion.

**Actual behavior verified from installed source code:**

`mcp.server.fastmcp.utilities.func_metadata.FuncMetadata.call_fn_with_arg_validation()`:

```python
if fn_is_async:
    return await fn(**arguments_parsed_dict)
else:
    return fn(**arguments_parsed_dict)  # <-- BLOCKS the event loop
```

Sync tools are called **directly** within the async context. There is NO `anyio.to_thread.run_sync()` wrapping for tools in MCP 1.26.0. The `anyio.to_thread` usage in the package is limited to file resource operations (`resources/types.py`), not tool execution.

**Impact on our code (mcp_server.py):** All 7 tools (`search_vault`, `search_codebase`, `search_all`, `get_index_status`, `get_code_file`, `reindex_vault`, `reindex_codebase`) are sync `def` and will block the event loop during GPU inference (10+ seconds for model loading, 100ms-5s per search). This means the MCP server cannot handle concurrent requests.

**Correct fix for Task #84:** Must manually wrap blocking calls in `asyncio.to_thread()` or use `anyio.to_thread.run_sync()`. Converting tools to `async def` with explicit thread offloading is the correct approach. The ADR recommendation to use sync `def` was based on incorrect assumptions about MCP 1.26.0 behavior.

### ToolError

`mcp.server.fastmcp.exceptions.ToolError` inherits from `FastMCPError`. When a tool raises `ToolError`, `Tool.run()` catches it and re-raises, which FastMCP then serializes as a user-facing error message to the MCP client. Regular exceptions are also caught and wrapped in `ToolError(f"Error executing tool {self.name}: {e}")`.

**Our usage:** Our tools don't explicitly raise `ToolError`. They let exceptions propagate naturally, which FastMCP wraps. This is acceptable but means error messages include the generic prefix "Error executing tool search_vault: ...".

### Tool return types — Pydantic model serialization

`Tool.run()` calls `self.fn_metadata.convert_result(result)` which handles Pydantic BaseModel return types by serializing them to JSON. Our tools return `SearchResponse`, `IndexStatus`, and `IndexResponse` (all Pydantic BaseModel subclasses). This is correct and works with FastMCP's built-in serialization.

### get_comp() thread safety

Our `get_comp()` (mcp_server.py:46-82) uses `threading.Lock()` with double-checked locking. Since MCP 1.26.0 runs sync tools directly on the event loop (not in worker threads), the `threading.Lock()` will work because there's only one thread. However, if we switch to `async def` with `anyio.to_thread.run_sync()`, the lock becomes essential for the worker thread pool.

### Discrepancies Found

#### D30-1: ADR `2026-03-07-mcp-sync-tools.md` is WRONG — sync tools are NOT auto-wrapped (CRITICAL)

The ADR states: "MCP SDK (v1.26+) auto-wraps sync `def` tools in `anyio.to_thread.run_sync()`". This is false for the installed mcp 1.26.0. The ADR needs correction.

**Impact:** Task #84 fix approach must change. Tools need explicit `async def` + `anyio.to_thread.run_sync()` wrapping, not plain sync `def`.

**Severity:** CRITICAL — directly affects the MCP server's ability to handle concurrent requests.

### Sources

- Installed package introspection: mcp 1.26.0
- Source file: `.venv/Lib/site-packages/mcp/server/fastmcp/utilities/func_metadata.py`
- Source file: `.venv/Lib/site-packages/mcp/server/fastmcp/tools/tool.py`

______________________________________________________________________

## Topic 31 — tree-sitter API Grounding (Round 4)

**Installed versions:** tree-sitter 0.25.2, tree-sitter-language-pack 0.13.0

### Runtime-verified API

All verified by executing actual tree-sitter parsing on this machine:

| API                                  | Type/Return                     | Status |
| ------------------------------------ | ------------------------------- | ------ |
| `get_parser(grammar_name)`           | `tree_sitter.Parser`            | OK     |
| `parser.parse(bytes)`                | `tree_sitter.Tree`              | OK     |
| `tree.root_node`                     | `tree_sitter.Node`              | OK     |
| `node.type`                          | `str`                           | OK     |
| `node.text`                          | **`bytes`** (not `str`)         | OK     |
| `node.start_byte`                    | `int`                           | OK     |
| `node.end_byte`                      | `int`                           | OK     |
| `node.start_point`                   | `Point(row, column)` namedtuple | OK     |
| `node.end_point`                     | `Point(row, column)` namedtuple | OK     |
| `node.start_point[0]`                | `int` (row via index)           | OK     |
| `node.start_point.row`               | `int` (row via name)            | OK     |
| `node.children`                      | `list[Node]`                    | OK     |
| `child_by_field_name("name")`        | `Node` (if exists)              | OK     |
| `child_by_field_name("nonexistent")` | `None`                          | OK     |

### Grammar name verification

Already verified in `docs/research/2026-03-07-api-verification.md`:

- `c_sharp` is INVALID, must be `csharp` (CRITICAL bug in indexer.py:172,218)
- All other grammar names verified OK

### `node.text` returns `bytes`

Confirmed: `node.text` returns `bytes`, e.g., `b'def foo():\n    pass'`. Our indexer uses `source[node.start_byte:node.end_byte]` where `source` is a Python `str`. This works for ASCII source code but is technically a byte-offset vs character-offset mismatch for multi-byte UTF-8 (already noted as MINOR in the API verification report).

### Discrepancies Found

**None new.** The `c_sharp` -> `csharp` bug was already identified. All other tree-sitter API usage is correct.

### Sources

- Runtime verification on installed tree-sitter 0.25.2 + tree-sitter-language-pack 0.13.0
- Previous verification: `docs/research/2026-03-07-api-verification.md`
