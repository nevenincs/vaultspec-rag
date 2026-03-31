# Research: CodebaseIndexer Tech Stack — 2026 GPU-First

Date: 2026-03-06
Sources: PyPI, GitHub, arXiv, library docs, web research.

---

## 1. AST-Based Code Chunking (replacing TextSplitter)

### Why AST chunking

The cAST paper (arXiv 2506.15655, EMNLP 2025 Findings) demonstrates that
AST-aware chunking outperforms character/line-based splitting for code RAG:

- +4.3 pts Recall@5 on RepoEval retrieval
- +2.67 pts Pass@1 on SWE-bench generation
- Used by Cursor, Cody, CocoIndex in production

### Algorithm: split-then-merge (cAST)

1. Parse source file into AST via tree-sitter.
2. Depth-first traversal from root. Attempt to place each top-level node
   (function, class, impl block) into a single chunk.
3. If a node exceeds the token/char budget, recurse into its children.
4. Greedily merge adjacent sibling nodes until the budget is reached.
5. Concatenating all chunks reproduces the original file verbatim
   (no information loss, no overlap artifacts).

Design goals: syntactic integrity, high information density, language
invariance (no language-specific heuristics), plug-and-play compatibility.

### Library: tree-sitter-language-pack (RECOMMENDED)

**Package:** `tree-sitter-language-pack` (PyPI)
**Status:** Actively maintained (v0.13.0, Nov 2025). Successor to the
unmaintained `tree-sitter-languages` by Grant Jenks.
**Python:** >=3.9
**Requires:** `tree-sitter>=0.23`

API (identical to tree-sitter-languages):

```python
from tree_sitter_language_pack import get_language, get_parser

parser = get_parser("python")
tree = parser.parse(source_code.encode("utf-8"))
root = tree.root_node

# Walk AST nodes
for child in root.children:
    print(child.type, child.start_point, child.end_point)
    # child.text gives the source bytes for that node
```

**Key node types per language:**

| Language   | Top-level chunk nodes                          |
|------------|------------------------------------------------|
| Python     | function_definition, class_definition, decorated_definition |
| Rust       | function_item, impl_item, struct_item, enum_item, trait_item |
| TypeScript | function_declaration, class_declaration, lexical_declaration, export_statement |
| JavaScript | function_declaration, class_declaration, variable_declaration, export_statement |
| Go         | function_declaration, method_declaration, type_declaration |
| Java       | class_declaration, method_declaration, interface_declaration |
| C/C++      | function_definition, struct_specifier, class_specifier |
| C#         | class_declaration, method_declaration, namespace_declaration |
| Ruby       | method, class, module                          |
| Shell      | function_definition, command                   |
| YAML/TOML/JSON/HTML/CSS | Use character-based fallback (no semantic nodes) |
| Markdown   | section, atx_heading (tree-sitter-markdown)    |

**Supported languages:** 100+ pre-built grammars in binary wheels (no
compilation step needed).

### NOT recommended: tree-sitter-languages

`tree-sitter-languages` (Grant Jenks) is **unmaintained** — last release
predates tree-sitter 0.23 ABI changes. Use `tree-sitter-language-pack` instead.
Same API (`get_language`, `get_parser`), actively maintained fork.

### NOT recommended: astchunk / code-chunk

Third-party AST chunking libraries exist (yilinjz/astchunk,
supermemoryai/code-chunk) but add unnecessary dependencies. The cAST algorithm
is simple enough to implement directly (~100 lines) with tree-sitter.

---

## 2. Gitignore-Compliant File Scanning (replacing git ls-files fallback)

### Problem

Current `CodebaseIndexer._scan_codebase()` calls `git ls-files`, falling back
to `rglob("*")` which ignores `.gitignore` entirely. The `git ls-files` path
also misses untracked-but-not-ignored files.

### Library: pathspec (RECOMMENDED)

**Package:** `pathspec` (PyPI, v0.12.1+)
**API:** `GitIgnoreSpec` for gitignore-compliant pattern matching.

```python
import pathspec

# Load .gitignore patterns
gitignore_path = root_dir / ".gitignore"
if gitignore_path.exists():
    spec = pathspec.GitIgnoreSpec.from_lines(
        gitignore_path.read_text().splitlines()
    )
else:
    spec = pathspec.GitIgnoreSpec.from_lines([])

# Get all non-ignored files
all_files = root_dir.rglob("*")
kept = [f for f in all_files if f.is_file() and not spec.match_file(
    str(f.relative_to(root_dir))
)]
```

**Advantages over git ls-files:**

- Works without git installed
- Handles nested `.gitignore` files (scan each directory level)
- No subprocess overhead
- Handles negation patterns correctly
- `GitIgnoreSpec` replicates Git's actual behavior (not just documented spec)

**Backend options:** "simple" (always available), "re2", "hyperscan" for perf.

### Implementation pattern for nested gitignores

```python
def _load_gitignore_specs(root: Path) -> list[pathspec.GitIgnoreSpec]:
    specs = []
    for gitignore in root.rglob(".gitignore"):
        rel_dir = gitignore.parent.relative_to(root)
        lines = gitignore.read_text().splitlines()
        # Prefix patterns with the directory they apply to
        prefixed = [f"{rel_dir}/{line}" if rel_dir != Path(".") else line
                     for line in lines if line.strip() and not line.startswith("#")]
        specs.append(pathspec.GitIgnoreSpec.from_lines(prefixed))
    return specs
```

---

## 3. Incremental Indexing via Content Hashing

### Problem

`CodebaseIndexer` has no `incremental_index()`. `VaultIndexer` uses mtime-based
detection, but mtime is unreliable (git checkout resets mtime, file copies
preserve content but change mtime).

### Recommendation: SHA256 content hash

```python
import hashlib

def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
```

Store `{rel_path: content_hash}` in `.qdrant/code_index_meta.json`.
On incremental run:

1. Scan all files (via pathspec-filtered rglob).
2. Hash each file.
3. Compare against stored hashes:
   - New file (path not in meta) -> index
   - Changed file (hash differs) -> re-index
   - Deleted file (in meta but not on disk) -> delete from Qdrant
   - Unchanged (hash matches) -> skip
4. Update meta with new hashes.

**Why SHA256 over mtime:**

- Deterministic: same content = same hash regardless of filesystem metadata
- Git-proof: `git checkout` changes mtime but not content
- Copy-proof: copying a file changes mtime but not content
- SHA256 of a 10MB file takes <10ms — negligible vs embedding cost

---

## 4. Chunk ID Strategy

### Problem

Current: `id = f"{rel_path}:{line_start}-{line_end}"` — collides when
duplicate code exists at different locations (content.find() returns first
occurrence).

### Recommendation: content-addressed IDs

```python
chunk_hash = hashlib.sha256(chunk_text.encode()).hexdigest()[:12]
chunk_id = f"{rel_path}:{line_start}-{line_end}:{chunk_hash}"
```

With AST chunking, line_start/line_end come directly from tree-sitter node
`start_point` and `end_point` (accurate, not approximated via `content.find()`).
The content hash suffix guarantees uniqueness even if line ranges somehow
overlap.

---

## 5. File Safety Guards

### Binary file detection

```python
def _is_binary(path: Path, sample_size: int = 8192) -> bool:
    chunk = path.read_bytes()[:sample_size]
    return b"\x00" in chunk
```

### File size limit

10MB threshold. Files larger than this are unlikely to be useful for RAG
and would consume excessive VRAM during embedding.

```python
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

def _is_too_large(path: Path) -> bool:
    return path.stat().st_size > MAX_FILE_SIZE
```

---

## 6. Extended Language Support

### Current (7 extensions)

`.py`, `.rs`, `.md`, `.js`, `.ts`, `.tsx`, `.jsx`

### Proposed (24 extensions)

| Extension(s)          | Language     | tree-sitter grammar |
|-----------------------|-------------|---------------------|
| `.py`                 | Python       | python              |
| `.rs`                 | Rust         | rust                |
| `.md`                 | Markdown     | markdown            |
| `.js`, `.jsx`         | JavaScript   | javascript          |
| `.ts`, `.tsx`         | TypeScript   | typescript          |
| `.go`                 | Go           | go                  |
| `.java`               | Java         | java                |
| `.c`, `.h`            | C            | c                   |
| `.cpp`, `.hpp`, `.cc` | C++          | cpp                 |
| `.cs`                 | C#           | c_sharp             |
| `.rb`                 | Ruby         | ruby                |
| `.sh`, `.bash`        | Shell        | bash                |
| `.yaml`, `.yml`       | YAML         | yaml                |
| `.toml`               | TOML         | toml                |
| `.json`               | JSON         | json                |
| `.html`               | HTML         | html                |
| `.css`                | CSS          | css                 |
| `.kt`                 | Kotlin       | kotlin              |

For config/data formats (YAML, TOML, JSON, HTML, CSS), AST chunking adds
minimal value — use character-based splitting as fallback.

---

## 7. Dependency Changes for pyproject.toml

```toml
dependencies = [
    # ... existing ...
    "tree-sitter>=0.23",
    "tree-sitter-language-pack>=0.10",
    "pathspec>=0.12",
]
```

Both are pure-Python or have pre-built wheels. No CUDA dependency. No
compilation step on Windows/Linux/macOS.

---

## 8. Implementation Plan

### Task #3: Critical bug fixes (no new deps)

1. Replace `content.find(text)` line tracking with offset-tracking during split
2. Add SHA256 content hash to chunk IDs
3. Implement `CodebaseIndexer.incremental_index()` using SHA256 file hashing

### Task #4: AST chunking + pathspec (new deps)

1. Add `tree-sitter-language-pack` and `pathspec` to pyproject.toml
2. Replace `TextSplitter` with `ASTChunker` implementing cAST algorithm
3. Replace `_scan_codebase()` with pathspec-based scanning
4. Expand supported extensions to 24
5. Add binary detection and file size limit
6. Add per-chunk metadata: `function_name`, `class_name` from AST node type
7. Keep `TextSplitter` as fallback for non-AST languages (YAML, TOML, etc.)

---

## 9. Tree-Sitter API Deep Dive

### Parser setup (py-tree-sitter >= 0.23 + tree-sitter-language-pack)

```python
from tree_sitter import Language, Parser
from tree_sitter_language_pack import get_language, get_parser

# Option A: get_parser returns a ready-to-use Parser
parser = get_parser("python")
tree = parser.parse(b"def foo(): pass")

# Option B: manual setup
lang = get_language("python")
parser = Parser(lang)
tree = parser.parse(source_bytes)
```

### Node properties

Every `Node` exposes:

| Property          | Type              | Description                              |
|-------------------|-------------------|------------------------------------------|
| `type`            | `str`             | Grammar node type (`function_definition`) |
| `text`            | `bytes`           | Source bytes for this node                |
| `start_point`     | `(row, col)`      | 0-indexed start position                 |
| `end_point`       | `(row, col)`      | 0-indexed end position                   |
| `start_byte`      | `int`             | Byte offset start                        |
| `end_byte`        | `int`             | Byte offset end                          |
| `children`        | `list[Node]`      | Direct child nodes                       |
| `named_children`  | `list[Node]`      | Non-anonymous children only              |
| `parent`          | `Node | None`     | Parent node                              |
| `child_count`     | `int`             | Number of children                       |
| `is_named`        | `bool`            | True for grammar-defined nodes           |

Key methods:

- `child_by_field_name("name")` — get child by grammar field (e.g., function name)
- `children_by_field_name("body")` — get multiple children by field
- `next_named_sibling` / `prev_named_sibling` — sibling navigation
- `sexp()` — S-expression string for debugging

### TreeCursor (efficient traversal for large files)

```python
cursor = tree.walk()  # starts at root_node

# Navigation methods (all return bool):
cursor.goto_first_child()
cursor.goto_last_child()
cursor.goto_next_sibling()
cursor.goto_previous_sibling()
cursor.goto_parent()
cursor.goto_descendant(index)
cursor.goto_first_child_for_byte(byte_offset)
cursor.goto_first_child_for_point((row, col))

# Properties:
cursor.node        # current Node
cursor.field_name  # field name if current node is a named field
cursor.depth       # depth from start node
```

Complete tree walk generator:

```python
def walk_tree(node):
    """Yield all nodes via depth-first traversal using TreeCursor."""
    cursor = node.walk()
    visited_children = False
    while True:
        if not visited_children:
            yield cursor.node
            if not cursor.goto_first_child():
                visited_children = True
        elif cursor.goto_next_sibling():
            visited_children = False
        elif not cursor.goto_parent():
            break
```

### Query API (pattern matching on AST)

```python
lang = get_language("python")

# Find all function definitions with their names
query = lang.query("""
(function_definition
  name: (identifier) @function.name
  body: (block) @function.body)
""")

captures = query.captures(tree.root_node)
# Returns dict: {"function.name": [Node, ...], "function.body": [Node, ...]}
for name, nodes in captures.items():
    for node in nodes:
        print(f"{name}: {node.text.decode()}")
```

### Extracting metadata from AST nodes

```python
def extract_chunk_metadata(node) -> dict[str, str | None]:
    """Extract function_name, class_name from a tree-sitter node."""
    meta: dict[str, str | None] = {
        "function_name": None,
        "class_name": None,
        "node_type": node.type,
    }

    if node.type in ("function_definition", "function_declaration",
                      "function_item", "method_declaration"):
        name_node = node.child_by_field_name("name")
        if name_node:
            meta["function_name"] = name_node.text.decode()

    if node.type in ("class_definition", "class_declaration",
                      "class_specifier", "impl_item"):
        name_node = node.child_by_field_name("name")
        if name_node:
            meta["class_name"] = name_node.text.decode()

    # Walk up to find enclosing class
    parent = node.parent
    while parent:
        if parent.type in ("class_definition", "class_declaration",
                            "class_specifier"):
            name_node = parent.child_by_field_name("name")
            if name_node:
                meta["class_name"] = name_node.text.decode()
            break
        parent = parent.parent

    return meta
```

---

## 10. Code Embedding Models — 2026 Landscape

### Qwen3-Embedding-0.6B (current stack)

| Spec               | Value                                          |
|---------------------|-------------------------------------------------|
| Parameters          | 0.6B                                            |
| Dimensions          | Up to 1024 (MRL: user-selectable 32-1024)       |
| Context length      | 32K tokens                                      |
| License             | Apache 2.0 (fully open)                         |
| MTEB Multilingual   | 64.33 mean                                      |
| MTEB English v2     | 70.70 mean (Retrieval: 61.83)                   |
| Code support        | 100+ languages including programming languages  |
| Code benchmarks     | Not separately reported for 0.6B                |
| Inference           | Local GPU, sentence-transformers, fp16           |

The 0.6B model does not have explicit code-specific benchmark scores published.
The larger Qwen3-Embedding-8B leads MTEB-Code leaderboard, but 8B is too large
for single-GPU local inference alongside SPLADE + reranker.

**Verdict for our use case:** Adequate. We already use it for docs, and code
retrieval quality is augmented by SPLADE sparse vectors + CrossEncoder reranker.
The hybrid search pipeline compensates for any single-model weakness.

### voyage-code-3 (API-only alternative)

| Spec               | Value                                          |
|---------------------|-------------------------------------------------|
| Parameters          | Unknown (proprietary)                           |
| Dimensions          | 2048, 1024, 512, 256 (Matryoshka)               |
| Context length      | 32K tokens                                      |
| License             | Proprietary API (Voyage AI / Anthropic)         |
| Code benchmarks     | +13.8% over OpenAI-v3-large on 238 datasets     |
| Language coverage   | 300+ programming languages                      |
| Pricing             | First 200M tokens free, then paid               |
| Inference           | API-only (not local)                             |

**Verdict:** Superior code retrieval quality, but API-only. Violates our
GPU-first local-inference mandate. Not recommended unless we add an optional
API fallback path in the future.

### Recommendation

**Keep Qwen3-Embedding-0.6B.** Reasons:

1. Already integrated and working
2. Local GPU inference (no API dependency, no latency, no cost)
3. Hybrid search (dense + SPLADE + reranker) compensates for model size
4. Apache 2.0 license — no vendor lock-in
5. 32K context handles large code files
6. If code retrieval quality is insufficient, upgrade path is Qwen3-Embedding-4B
   (same API, still fits on RTX 4080 SUPER 16GB)

---

## 11. Qdrant Payload Filtering for Code Metadata

### Storing code metadata as Qdrant payload

When upserting code chunks, attach metadata as payload fields:

```python
from qdrant_client.models import PointStruct

points = [
    PointStruct(
        id=chunk_id,
        vector={
            "dense": dense_embedding,
            "sparse": sparse_vector,
        },
        payload={
            "file_path": "src/vaultspec_rag/indexer.py",
            "language": "python",
            "function_name": "incremental_index",
            "class_name": "CodebaseIndexer",
            "node_type": "function_definition",
            "line_start": 142,
            "line_end": 198,
            "content_hash": "a1b2c3d4e5f6",
            "text": chunk_text,
        },
    )
]

client.upsert(collection_name="code_index", points=points)
```

### Creating payload indexes for fast filtering

```python
from qdrant_client.models import PayloadSchemaType

# Index frequently-filtered fields
client.create_payload_index(
    collection_name="code_index",
    field_name="language",
    field_schema=PayloadSchemaType.KEYWORD,
)
client.create_payload_index(
    collection_name="code_index",
    field_name="class_name",
    field_schema=PayloadSchemaType.KEYWORD,
)
client.create_payload_index(
    collection_name="code_index",
    field_name="function_name",
    field_schema=PayloadSchemaType.KEYWORD,
)
client.create_payload_index(
    collection_name="code_index",
    field_name="file_path",
    field_schema=PayloadSchemaType.KEYWORD,
)
```

### Filter syntax examples

```python
from qdrant_client.models import (
    Filter, FieldCondition, MatchValue, MatchAny,
)

# Filter: language=python AND class_name=CodebaseIndexer
python_class_filter = Filter(
    must=[
        FieldCondition(
            key="language",
            match=MatchValue(value="python"),
        ),
        FieldCondition(
            key="class_name",
            match=MatchValue(value="CodebaseIndexer"),
        ),
    ]
)

# Filter: language IN (python, typescript) AND function_name exists
multi_lang_filter = Filter(
    must=[
        FieldCondition(
            key="language",
            match=MatchAny(any=["python", "typescript"]),
        ),
    ],
    must_not=[
        models.IsNullCondition(
            is_null=models.PayloadField(key="function_name"),
        ),
    ],
)

# Search with filter
results = client.query_points(
    collection_name="code_index",
    query=dense_embedding,
    using="dense",
    query_filter=python_class_filter,
    with_payload=True,
    limit=10,
)
```

### Filter conditions reference

| Condition      | Use case                                    | Example                                      |
|----------------|---------------------------------------------|----------------------------------------------|
| `MatchValue`   | Exact match (keyword, int, bool)            | `language == "python"`                       |
| `MatchAny`     | IN operator                                 | `language IN ("python", "go", "rust")`       |
| `MatchExcept`  | NOT IN operator                             | `language NOT IN ("yaml", "json")`           |
| `Range`        | Numeric comparison (gt, gte, lt, lte)       | `line_start >= 100`                          |
| `IsNull`       | Field is null                               | `class_name IS NULL`                         |
| `IsEmpty`      | Field is empty array                        | `tags IS EMPTY`                              |
| `HasVector`    | Point has a specific named vector           | `HAS "dense"`                                |

Clauses: `must` (AND), `should` (OR), `must_not` (NOT). Nestable.

Nested key access via dot notation: `metadata.author.name`.

---

## References

- cAST paper: <https://arxiv.org/abs/2506.15655>
- tree-sitter-language-pack: <https://pypi.org/project/tree-sitter-language-pack/>
- tree-sitter-language-pack GitHub: <https://github.com/Goldziher/tree-sitter-language-pack>
- pathspec: <https://pypi.org/project/pathspec/>
- pathspec API docs: <https://python-path-specification.readthedocs.io/en/latest/api.html>
- py-tree-sitter: <https://github.com/tree-sitter/py-tree-sitter>
- supermemory code-chunk: <https://supermemory.ai/blog/building-code-chunk-ast-aware-code-chunking/>
- py-tree-sitter TreeCursor docs: <https://tree-sitter.github.io/py-tree-sitter/classes/tree_sitter.TreeCursor.html>
- Qwen3-Embedding-0.6B model card: <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B>
- Qwen3 Embedding blog: <https://qwenlm.github.io/blog/qwen3-embedding/>
- voyage-code-3 blog: <https://blog.voyageai.com/2024/12/04/voyage-code-3/>
- Qdrant payload docs: <https://qdrant.tech/documentation/concepts/payload/>
- Qdrant filtering docs: <https://qdrant.tech/documentation/concepts/filtering/>
