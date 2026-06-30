---
tags:
  - '#research'
  - '#preprocess-hooks'
date: '2026-06-10'
modified: '2026-06-30'
related: []
---

# `preprocess-hooks` research: `document preprocessing hook infrastructure`

Downstream projects use vaultspec-rag as a resident index/search service over large
mixed corpora, but a significant fraction of high-value grounding material is invisible
to the indexer because it is binary (PDF, XLS/XLSX, DOCX), has an unsupported extension
(XSD, plain-text tails like `.txt/.xml/.properties`), or indexes poorly as raw markup
(large structured HTML). These formats are domain-specific, so vaultspec-rag must not
learn them. Instead this feature researches a **general preprocess-hook infrastructure**:
any project supplies its own extraction logic and the output is indexed first-class,
against a versioned contract vaultspec-rag owns. Tracked upstream as issue 185. The
illustrative downstream is a ~16k-file corpus with ~220 currently-invisible binaries.

Research was conducted across four grounded streams (registration config, output schema
and payload flow, runtime mechanics, and the two adjacent asks plus an extraction-library
survey), each pinned to the actual indexer seams. All recommendations below cite the code
they are grounded in.

## Findings

### F1 — Registration config: `.vaultragpreprocess.toml`, root-only, per-root

The sibling `.vaultragignore` is read from exactly one location, the project root
(`self.root_dir / ".vaultragignore"`), guarded by `is_file()`, parsed line-by-line with
`#`-comment stripping, and compiled into a `pathspec.GitIgnoreSpec`; an unreadable file
warns-and-degrades to `--exclude` patterns only. Matching is OR-combined with
`.gitignore` so ignore always wins ("`.vaultragignore` can never un-ignore `.gitignore`").
The watcher does **not** resolve config itself — it is constructed per-root with already
-resolved indexers and scalar knobs, so per-root config resolution belongs at indexer
construction time keyed on `root_dir`.

**Recommendation.** Mirror `.vaultragignore` exactly: a root-only `.vaultragpreprocess.toml`
resolved lazily inside `CodebaseIndexer` via a new `_build_preprocess_rules()` method
(do **not** walk subtrees; do **not** put it in `config.py`, which is scalar-knobs-only).
TOML is parsed with stdlib `tomllib` (the project is 3.13-only; `tomlkit>=0.13` is present
but only needed for round-trip writing, e.g. a future `preprocess add` CLI verb — and
`tomlkit` rejects a BOM that `tomllib` accepts, favouring `tomllib` for read-only).
Pattern matching reuses `pathspec.GitIgnoreSpec` (already a dependency) so authors learn
one glob dialect.

Schema: an array-of-tables, one `[[rule]]` per rule, with a top-level `version` for
forward-compat. Each rule carries `pattern` (one gitignore-style glob), **exactly one of**
`command` (subprocess template with `{path}` substitution → JSON on stdout) or
`entry_point` (`"module:callable"`), an optional `priority` (lower = higher precedence;
ties broken by file order; sort once at construction), `on_error`
(`skip` | `fail` | `passthrough`, default `skip`), a command-only `timeout_s`, and an
opaque `[rule.options]` sub-table forwarded to the preprocessor. Determinism: sort by
`(priority, file_index)`, then first-match wins.

**Composition with ignore — ignore wins.** Preprocess lookup runs only on files that
survive the existing ignore gauntlet; a preprocess match must never resurrect an ignored
file. The one legitimate interaction with the *extension* gate is the opposite: a
preprocess `pattern` match must **expand** the indexable set (admit a `.pdf`/`.ipynb`
that is not in `SUPPORTED_EXTENSIONS`), a deliberate scoped exception distinct from the
inviolable ignore boundary. Parse errors degrade (warn, zero rules — never wedge the
resident service); per-rule schema violations drop that rule with a warning; hard-fail is
reserved for an explicit `preprocess check` validation verb.

### F2 — Versioned output schema: pydantic v2 at the ingest boundary

The preprocessor output is an untrusted, versioned, cross-process JSON boundary — exactly
how the repo already treats its MCP wire models (pydantic v2 is a **core** dependency).
The internal embed/upsert path stays on the existing `@dataclass` `CodeChunk` /
`VaultDocument`; convert at the seam so nothing downstream of ingest changes.

**Document wrapper** (`PreprocOutput`): `schema_version: int`, `preprocessor_id: str`,
`preprocessor_version: str`, `source_path: str`, and **exactly one of** `units: list[PreprocUnit]` (pre-chunked) or `text: str` (plain text + doc metadata, which the
indexer then runs through the existing `TextSplitter`/AST path), plus a doc-level
`metadata` dict. The `units`/`text` XOR is enforced by a model validator; `extra="forbid"`
rejects typo'd keys loudly.

**Unit** (`PreprocUnit`): `text` (required), optional `title`, `section`, `anchor`
(deep-link into the source's own addressing scheme, e.g. `#page=12`, `A1:C4`), an optional
`locator { kind: byte|page|sheet|line|char|none, value: int|str, end?: int|str }`, and a
free-form `metadata` dict whose values are restricted to JSON scalars/lists so they
round-trip through Qdrant payload and the `--json` envelope. `source_path` lives at the
document level and is threaded down to each stored chunk (mirroring how `chunk_file`
carries `rel_path`).

**Validation** is `PreprocOutput.model_validate(json)` wrapped per-source-file in a
`ValidationError` handler that logs and skips — never raises out of the indexing loop —
matching the established per-file fault isolation (`prepare_document` returns `None` on
read failure; `chunk_file` returns `[]` on decode failure). **schema_version** is gated
against an indexer-pinned `SUPPORTED_SCHEMA_VERSION = 1`: newer = reject the file with a
clear "upgrade vaultspec-rag" message; older = accept if still constructable (adapter
table when v2 lands). The stored `schema_version` payload field lets a future re-index
detect stale-schema chunks.

**Wire format.** One JSON object per invocation on **stdout** (primary contract:
language-agnostic, composes with per-file fault model, no cache-invalidation bugs), with
an **optional sidecar** `<source>.vsprep.json` keyed by the source blake2b hash for
expensive extractors (OCR/large PDF). Never emit `vector`/`sparse_*` — embedding is the
GPU consumer's exclusive job.

### F3 — Payload mapping and result surfacing

The codebase chunk payload today is `chunk_id, path, language, content, line_start, line_end, node_type, function_name, class_name`; chunk IDs embed the locator
(`path:line_start-line_end:blake2b(text)`) so line-range churn yields a new ID and
modified-file reconciliation drops old chunks by `path`. Local-mode Qdrant ignores payload
indexes (server-mode only), but declaring them stays correct.

**Recommendation.** Use a **third collection** `preproc_docs` rather than overloading the
code or vault collections (preproc units are neither code nor vault markdown; overloading
their KEYWORD indexes with foreign semantics confuses the filter builders). Map:
`source_path → path` (KEYWORD, required for purge-by-path reconciliation),
`preprocessor_id → preprocessor_id` (KEYWORD, filterable), `preprocessor_version` /
`schema_version` stored unindexed (diagnostic), unit `text → content`, `title`, `section`
(optional KEYWORD), `anchor` (unindexed deep-link), and a **split** locator —
`locator_value_int` INTEGER for numeric kinds (byte/page/line/char) vs `locator_value_str`
KEYWORD for string kinds (sheet) — because a polymorphic field cannot take one typed
index. Free-form `metadata` is stored under one payload key (unindexed by default), with an
opt-in per-rule allowlist promoting selected keys to top-level KEYWORD fields (never
auto-index arbitrary keys — unbounded index creation). Stored-chunk ID:
`source_path:locator_kind:locator_value:blake2b(text)`, falling back to the existing
`path:line_start-line_end:hash` form for text-split units with no native locator.

**Surfacing cost (carry to ADR/plan):** showing `anchor`/`locator` to users requires
editing **three** types in lockstep — `SearchResult`, the pydantic `SearchResultItem`, and
the CLI renderer (which today shows only `:{line_start}`) — populated at
`_map_codebase_results`.

### F4 — Execution model: split by rule form, both originate in the CPU worker

The full-index hot path is a producer (orchestrator thread draining a spawn
`ProcessPoolExecutor`, single-read + blake2b + decode + chunk in a CPU-only worker)
feeding one dedicated GPU-consumer thread that owns `gpu_lock` and is the only CUDA
toucher. Serial, incremental, and scoped paths all funnel through the same `_chunk_worker`
callables (the chunk-identity-parity guarantee).

**Recommendation.** Insert a `preprocess_decoded(path, root_dir, rules)` step at the top of
both `chunk_file` and `chunk_and_hash_file` (after read+hash, before decode/chunk), so
emitted text replaces `content`. The embed/upsert seam is **untouched** — preprocessing is
pure CPU produce-side work, so `gpu-consumer-single-thread` is satisfied cleanly.

- **`command` form** runs the real compute in a `subprocess.run` **grandchild** — a
  separate OS process that cannot pollute the worker import chain or CUDA state, so
  `index-workers-stay-cpu-only` is satisfied **by construction**. Time-bound it with
  `subprocess.run(timeout=rule.timeout_s)` (mirroring the existing 300 s deadline-bounded
  GPU-consumer shutdown); `TimeoutExpired` → preprocess-skip.
- **`entry_point` form** runs in-process in the spawn worker. This is the one **rule-conflict
  risk**: arbitrary user code can `import torch`/init CUDA inside the worker, defeating the
  lazy-import invariant `index-workers-stay-cpu-only` protects, and it **cannot be cleanly
  timed out** (no portable safe interrupt for sync CPU-bound callables). Spawn already
  neutralises the hard fork-CUDA crash, degrading the failure to wasted per-worker CUDA
  startup. **Open decision for the ADR:** accept-and-document the CPU-only contract (keeps
  the pool's parallelism — recommended) vs. run *every* preprocessor out-of-process for
  uniform isolation (per-file spawn cost). `timeout_s` is documented as command-only.

### F5 — Cache, incremental, watcher, size cap, failure visibility

**Cache.** Reuse the existing source digest (`hashlib.file_digest(f, "blake2b")` /
`blake2b(raw)` in the worker — they are byte-identical) as the source-hash component of the
key `(source_hash, preprocessor_id, preprocessor_version, schema_version)`. Store one JSON
per source under `.vault/data/search-data/preprocess-cache/<sha-prefix>/<source-hash>.json`
(per-source files avoid a single-writer manifest bottleneck across parallel workers; shard
dir bounds directory size), written atomically with the same `.tmp` + `os.replace` idiom as
the metadata sidecar. **Version-bump precision falls out for free:** version components are
in the key, so a bump changes the filename → miss → re-run, and sources matched by other
unchanged rules keep hitting their old cache. On `clean=True`, `rmtree` the cache subtree;
on incremental, leave (harmless, bounded) orphans.

**Incremental + watcher.** Because preprocessing lives **below** `_chunk_paths` /
`incremental_index(changed_paths=...)` (the PR 152 targeted-reindex work), a changed
preprocessable file routes preprocess → cache → chunk transparently with no new
incremental plumbing, and the watcher routes it through the **same** debounce/cooldown and
single-writer (`_writer_lock`) machinery with **no watcher logic change** — *except* one:
the watcher's hardcoded `_CODE_EXTENSIONS` allowlist (and the indexer's
`SUPPORTED_EXTENSIONS` scan gate, in both full and scoped paths) must become
**preprocess-rule-aware** so a `.pdf` change actually triggers a reindex. Apply the
"gate is preprocess-aware" change in three sites: the watcher's `_is_code_change`, the
full-scan extension gate, and the scoped-path extension gate. Add the preprocess step to
**both** `chunk_file` and `chunk_and_hash_file` so full and incremental stay in parity.

**Size cap.** `_MAX_FILE_SIZE = 10 MB` currently gates **source** size (plus extension and
binary gates) at the full-scan and scoped sites. For a preprocess-matched file all three
pre-gates must be relaxed (a 12 MB binary PDF is legitimate); the cap moves to **emitted
text length**, enforced inside the worker after preprocessing, via a *separate* config knob
(`preprocess_max_emitted_bytes`) following the `_RAG_DEFAULTS` + `_ENV_OVERRIDE_MAP`
pattern — not by overloading `_MAX_FILE_SIZE`, whose semantics now differ.

**Failure visibility.** `IndexResult` today has **no** skipped/failed field and drops its
`files` list before status/jobs/CLI surfacing; preprocess-style failures would be silently
swallowed. Extend `IndexResult` with `preprocess_skipped`, `preprocess_failed`, and a
`preprocess_failures` file list (default-valued so existing constructors stay valid); carry
per-file status back on `FileChunkResult`; accumulate in the orchestrator where it already
inspects every result; and append `~skipped !failed` to the jobs/watcher summary strings
plus the CLI JSON source dicts. Per the no-swallow mandate, every skip/fail must **both**
`logger.warning` **and** increment a surfaced counter.

### F6 — Adjacent ask (a): default extensions `.txt/.xml/.xsd/.properties`

Trivial and safe. Add to `LANGUAGE_MAP` (the `SUPPORTED_EXTENSIONS` set derives from it):
`.txt → ("text", None)`, `.properties → ("text", None)`, `.xml → ("xml", None)`,
`.xsd → ("xml", None)` (grammar `None` = plain text, no useful AST; they flow through
`TextSplitter`). The `"text"` separator key exists explicitly and is also the `.get`
default, so `"xml"` (no separator entry) degrades gracefully to the same paragraph/line/
space split while staying queryable as its own `--language xml`. `_is_binary` (NUL-byte
test) accepts all four. `.html` is already mapped. Tests: bump the
`len(SUPPORTED_EXTENSIONS) >= 25` floor to `>= 29` and add positive `LANGUAGE_MAP[...]`
assertions; the bijective-consistency test passes as-is.

### F7 — Adjacent ask (b): optional HTML-to-text normalisation

`.html` (grammar `None`) routes through `chunk_with_splitter`, embedding raw markup
verbatim and wasting ~1/3 of each chunk budget on tags/`<script>`/`<style>`. Insert an
opt-in normalisation step in the worker's `_chunk_decoded` (after decode, before split),
gated on `language == "html"`, using **stdlib `html.parser`** (no new dependency — bs4/lxml
/html2text are absent and a ~15-line `HTMLParser` subclass that drops script/style and
emits newlines on block-close tags is the licence-clean default; `html.unescape` handles
entities). Gate with an `html_strip` bool following the `sparse_enabled` env/default
convention (`VAULTSPEC_RAG_HTML_STRIP`, default on), **threaded into the spawn worker** as a
call parameter (workers cannot read parent config — the one non-trivial plumbing point).
Fallback to raw-markup chunking on any parse error so behaviour never regresses. Runs
CPU-side only.

### F8 — Illustrative downstream extractors (project-side, not shipped; prove the schema generalises)

All conform to `PreprocOutput` (units with `text` + `anchor` + `locator`). Licence flags
explicit (downstream wants licence-clean):

- **PDF → `pypdf` (BSD-3)**: page index is the `locator.kind=page` value; clean text,
  pure-Python. `pdfplumber` (MIT) for tables/positions if needed. **`PyMuPDF`/fitz is
  AGPL-3.0** — the one licence trap; name it explicitly as the counter-example, never the
  default.
- **XLSX → `openpyxl` (MIT)**: iterate worksheets then rows; sheet name is
  `locator.kind=sheet`. Legacy `.xls` needs `xlrd` (BSD) or pre-conversion.
- **DOCX → `python-docx` (MIT)**: paragraph index locator (Word has no render-time page
  numbers).
- **XSD/XML → stdlib `xml.etree` (PSF)**: element/tag locator; `lxml` (BSD) only if XPath
  or `sourceline` numbers are needed.

A licence-clean downstream picks pypdf + openpyxl(+xlrd) + python-docx + xml.etree and
never imports PyMuPDF.

## Open decisions for the ADR

- **D-exec-isolation:** `entry_point` preprocessors cannot be CPU-only-enforced or timed
  out in-worker. Accept-and-document the contract (recommended) vs. out-of-process-everything
  for uniform isolation. This is the single load-bearing safety decision.
- **D-collection:** dedicated `preproc_docs` collection (recommended) vs. overloading the
  codebase collection.
- **D-html-default:** `html_strip` default on (recommended) vs. off.
- **D-locator-index:** split `locator_value_int`/`locator_value_str` (recommended) vs.
  string-only value losing INTEGER-range filtering.
- **D-entry-point-support:** ship both `command` and `entry_point` in v1, or `command`-only
  first (simpler, uniformly isolatable) with `entry_point` deferred.

## Recommended next step

Proceed to `vaultspec-adr` to formalise the decisions above (config format, schema
contract and versioning, payload/collection, execution-and-isolation model, cache key,
failure/`on_error` semantics, watcher/extension-gate awareness, emitted-text size cap, and
the two adjacent asks) into numbered ADR decisions, then a plan.
