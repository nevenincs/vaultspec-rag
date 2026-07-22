# Document preprocessing hooks

vaultspec-rag keeps vault records, conventional source code, and extracted documents in
separate index domains. A project can contain other useful formats that the built-in
source parsers should not interpret as code.

Preprocessing hooks let each project supply its own extraction logic and explicitly route
the result to either the `code` or `document` domain. You register a command per file
pattern. vaultspec-rag runs it, validates the output against a versioned schema, and
indexes the extracted text first-class. The indexed chunks are searchable with anchors
that deep-link back into the original document. vaultspec-rag does not infer ownership
from directory names or ship client-specific file rules; it owns the contract and runs
your extractor.

## How it works

1. Add a version-2 `.vaultragpreprocess.toml` to your project root (a sibling of
   `.vaultragignore`) mapping file patterns to extraction commands and explicit targets.
1. During indexing, a file matching a rule is handed to your command, which prints one
   JSON document on stdout.
1. vaultspec-rag validates that JSON, turns it into searchable chunks (carrying your
   anchors and locators), and indexes them.
1. Search results for those chunks surface the source path and an anchor (for
   example `report.pdf#page=12`) instead of a line number.

Only the owning route admits a matched file. The extractor can turn binary or otherwise
unsupported input into text without making it source code. A preprocess rule never
re-includes files excluded by `.gitignore` or `.vaultragignore`; ignore always wins.

## Configure rules

Create `.vaultragpreprocess.toml` at the project root:

```toml
version = 2

[[rule]]
pattern  = "*.pdf"                 # gitignore-style glob (same dialect as .vaultragignore)
command  = "my-pdf-extract {path}" # {path} is replaced with the file path
target = "document"                # code | document; required ownership
extractor_version = "1.0.0"        # required; bump when extraction semantics change
on_error = "skip"                  # skip | fail | passthrough  (default: skip)
timeout_s = 60                     # wall-clock bound for the command
max_source_bytes = 52428800         # optional per-rule input ceiling

[[rule]]
pattern  = "docs/**/*.xlsx"
command  = "python tools/xlsx_extract.py {path}"
target = "document"
extractor_version = "2.1.0"
priority = 10                      # lower priority sorts first; first matching rule wins; ties break by file order
```

Rule fields:

- **`pattern`** (required) - one gitignore-style glob. Add more `[[rule]]` tables for
  more patterns.
- **`target`** (required) - the sole owner of matching output: `code` or `document`.
  Ownership is explicit and stable; paths and extensions do not choose the domain.
- **`extractor_version`** (required, non-empty string) - your extractor's semantic
  version. Change it whenever output semantics change so signatures and cache entries
  are invalidated deterministically.
- **One of `command` or `entry_point`** (required, exactly one):
  - `command` is a command template. `{path}` is substituted with the source file path.
    The command is split with shell-style tokenization and run **without** a shell, so
    spaces and metacharacters in paths can't inject. On Windows, use forward slashes in
    the interpreter or script path (a backslash path breaks the POSIX-style tokenizer
    even inside a TOML literal).
  - `entry_point` is a `"module:callable"` reference. The callable
    (`def my_callable(source_path: str) -> Mapping | BaseModel`) runs **out-of-process**
    (the same isolation and `timeout_s` bound as `command`); the module must be
    importable in the service's Python environment.
- **`priority`** (optional, default 100) - lower priority sorts first; the first matching
  rule wins; ties break by file order.
- **`on_error`** (optional, default `skip`):
  - `skip` - drop the file from the index and report it (never a silent gap).
  - `fail` - abort the whole index run (use when missing a document is unacceptable).
  - `passthrough` - index the raw file unprocessed instead of failing.
- **`timeout_s`** (optional) - kill the command after this many seconds and treat it as
  a failure per `on_error`. Must be a positive number.
- **`path_independent`** (optional, default `false`) - permit byte-identical inputs at
  different paths to share an extraction-cache entry. Enable it only when output never
  embeds the source path in text, anchors, locators, or metadata.
- **`max_source_bytes`** (optional) - a positive per-rule input ceiling. The effective
  ceiling is the lower of this value and the active document/source support profile.
- **`[rule.options]`** (optional) - an opaque table forwarded to your preprocessor for
  its own use.

Both `command` and `entry_point` rules run out-of-process (a subprocess), so they share
the same CPU-only isolation and `timeout_s` bound. An `entry_point` callable must be
importable in the service's environment and return a mapping (or pydantic model) shaped
like the [output schema](#output-schema).

### Inspect and validate your configuration

Three commands cover authoring and debugging. Prefix each with `uv run` in a uv-managed
environment:

```bash
uv run vaultspec-rag preprocess list            # show resolved rules, in precedence order
uv run vaultspec-rag preprocess check           # validate the config; non-zero exit on a bad config
uv run vaultspec-rag preprocess run-one a.pdf   # trial the matching rule against one file
```

- `preprocess list` prints each resolved rule with its target, extractor version,
  cache-binding mode, pattern, priority, failure handling, timeout, and command, sorted
  in precedence order.
- `preprocess check` strictly validates `.vaultragpreprocess.toml` and reports the first
  defect. Invalid or legacy targetless configuration is rejected before indexing can
  mutate a collection, sidecar, ledger, or cache.
- `preprocess run-one <path>` runs the matching rule against one file and prints the
  validated output, with no indexing side effect. Routing and migration defects, plus an
  extractor abort under `on_error = "fail"`, are structured errors with a non-zero exit.
  Other malformed rules use the non-strict loader and may appear as no match; run
  `preprocess check` first when validating configuration.

All three accept `--json` for scripting. `preprocess status` adds the effective execution
mode, schema version, targets, extractor versions, rule count, and whether the kill switch
prevents hooks from running.

## Invocation envelope

Every extractor process receives a versioned JSON envelope in the
`VAULTSPEC_PREPROCESS_INVOCATION` environment variable. Extractors can load and validate
it with `vaultspec_rag.indexer._preprocess_schema.load_preprocess_invocation()`.

```json
{
  "schema_version": 1,
  "source_paths": ["docs/report.pdf"],
  "options": {"layout": "pages"},
  "extractor_version": "1.0.0",
  "target": "document",
  "mode": "single"
}
```

For a batch rule, `source_paths` contains the bounded manifest members and `mode` is
`batch`. The envelope is the authoritative place for rule options, target, and extractor
version; command-line placeholders remain only the transport for source paths.

## Output schema

Your command receives a source file path and prints **one JSON object** on stdout. This
is the contract between your extractor and the indexer; invalid output is a per-file
error, never a crash. The models are pydantic v2 with unknown fields forbidden, so a
typo is a loud validation error rather than silent data loss.

```jsonc
{
  "schema_version": 1,                 // required; the schema major (currently 1)
  "preprocessor_id": "pdf-extract",    // required; your extractor's id
  "preprocessor_version": "1.2.0",     // required; your extractor's version
  "source_path": "docs/report.pdf",    // required; the path you were given
  // EXACTLY ONE of `units` or `text`:
  "units": [                           // (a) pre-chunked units
    {
      "text": "Quarterly revenue ...", // required; non-empty
      "title": "Q3 Results",           // optional
      "section": "Finance > Q3",       // optional
      "anchor": "docs/report.pdf#page=12", // optional anchor that deep-links into the source
      "locator": {"kind": "page", "value": 12}, // optional; see locator fields
      "metadata": {"author": "ACME"}   // optional; JSON values (scalars, arrays, or nested objects)
    }
  ],
  "text": "....",                      // (b) plain extracted text (indexer chunks it)
  "metadata": {}                       // optional document-level metadata
}
```

Document-level fields:

- **`schema_version`** (required, integer) - the schema major. A `schema_version` newer
  than the running vaultspec-rag is rejected with an "upgrade vaultspec-rag" message.
- **`preprocessor_id`** (required, non-empty string) - your extractor's id, surfaced in
  `preprocess run-one` output.
- **`preprocessor_version`** (required, non-empty string) - your extractor's version.
- **`source_path`** (required, non-empty string) - the path you were given.
- **`units`** (one of `units` or `text`) - pre-chunked units you produced.
- **`text`** (one of `units` or `text`) - plain extracted text the indexer runs through
  its normal text splitter.
- **`metadata`** (optional) - document-level metadata, JSON values (scalars, arrays, or
  nested objects).

Unit fields (each entry in `units`):

- **`text`** (required, non-empty string) - the unit's body.
- **`title`** (optional) - a heading for the unit.
- **`section`** (optional) - a breadcrumb path within the document.
- **`anchor`** (optional) - an anchor that deep-links into the source, surfaced verbatim
  in search results (for example `report.pdf#page=12`).
- **`locator`** (optional) - a typed pointer into the source's own addressing scheme,
  rendered as, for example, `page 12` or `sheet Summary`.
- **`metadata`** (optional) - per-unit metadata, JSON values (scalars, arrays, or nested
  objects).

Locator fields (the optional `locator` object):

- **`kind`** (required) - one of `byte`, `page`, `sheet`, `line`, `char`, or `none`.
- **`value`** (required) - an integer (page, line, byte, char) or a string (sheet name).
- **`end`** (optional) - an integer or string marking the end of a range.

Rules:

- Provide **either** `units` (you chunk) **or** `text` (the indexer chunks it), never
  both and never neither. When you provide `units`, it must be non-empty.

## Batch hooks

One subprocess per file makes cheap hooks dominated by interpreter startup: a bare
`python` noop hook measures **102.7 ms/file** (and **217.3 ms/file** through `uv run`),
versus **1.2 ms/file** when one spawn handles 100 files. On a first index or a clean
rebuild that constant is paid for every matched file. A batch hook amortizes it: one
subprocess processes many files at once.

Opt in per rule with `batch = true`. A batch rule's `command` receives a **manifest**
of source paths via a `{paths}` placeholder (not the per-file `{path}`) and emits a JSON
**array** of per-file outputs:

```toml
[[rule]]
pattern  = "*.pdf"
command  = "python tools/pdf_batch.py {paths}"   # {paths} is the manifest file path
target = "document"
extractor_version = "1.0.0"
batch    = true
on_error = "skip"
timeout_s = 5                                     # per-file budget; see scaling below
```

Rules for a batch rule:

- **`command` only.** `batch = true` is rejected on an `entry_point` rule (the
  entry-point form keeps per-file semantics), on a command missing `{paths}`, or on a
  command that also carries `{path}`. A non-batch command carrying `{paths}` is likewise
  rejected. Like any config defect, an invalid batch rule is dropped (or fails
  `preprocess check` in strict mode).

The manifest and response contract:

- **Manifest** - `{paths}` is replaced with the path of a temp file holding one absolute
  source path per line, UTF-8 encoded. Read it, process each path, and delete nothing
  (vaultspec-rag removes the manifest after the run).
- **Response** - print **one JSON array** on stdout. Each element is a normal
  [output object](#output-schema) plus a `"path"` field naming the source file it belongs
  to (the absolute path from the manifest). vaultspec-rag maps each element back to its
  file by that `"path"`.

```jsonc
[
  {
    "path": "/abs/docs/a.pdf",         // required; maps this element to its source file
    "schema_version": 1,
    "preprocessor_id": "pdf-batch",
    "preprocessor_version": "1.0",
    "source_path": "/abs/docs/a.pdf",
    "units": [ /* ... */ ]
  },
  { "path": "/abs/docs/b.pdf", "schema_version": 1, /* ... */ "text": "..." }
]
```

Bounds scale with the batch:

- **Timeout** - the wall-clock budget is `timeout_s * (files in the batch)`, capped at
  600 s, so the per-file budget you declared scales with the work handed over.
- **Stdout cap** scales the same way so the whole array fits; the per-file emitted-text
  cap (`VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES`) still applies unchanged to every
  element.

Failure handling is per file:

- A file **missing** from the response array, or whose element fails schema validation or
  the emitted-text cap, is resolved through the rule's `on_error` for that file alone
  (`skip` / `passthrough` / `fail`); the other files in the batch are unaffected.
- A **malformed envelope** - non-JSON, not an array, a non-zero exit, or a timeout -
  fails the whole batch, and every file in it is resolved through `on_error`.
- `on_error = "fail"` aborts the index run on the first affected file, exactly as it does
  per file.

`on_error = "fail"` has the same meaning for batch and single-file rules: the first
affected file raises a preprocessing abort that propagates through the worker pool and
stops the index run. `skip` and `passthrough` remain per-file outcomes, so unaffected
members of a valid batch can still succeed.

Batch results are cached per file under the same [cache](#cache-and-incremental-indexing)
key, so cache hits keep bypassing the hook entirely and a mixed hit/miss set shrinks the
manifest to just the misses. Matched files are grouped into manifests of at most 64 paths,
each group a single spawn.

## Cache and incremental indexing

Successful extraction output is cached under the data directory. The key binds the source
path and content hash to the output schema and canonical execution fingerprint, including
the target, extractor version, command or entry point, and options. An unchanged file is
not re-extracted on a full or resumed reindex. A changed input or execution fingerprint
produces a new key. Only successful outputs are cached, so a transient extractor failure
is never made sticky. Cross-path reuse requires the rule's explicit
`path_independent = true` declaration.

To force re-extraction of unchanged files after upgrading your extractor, bump
`extractor_version`. Collection cleanup is intentionally separate from cache lifecycle:
cleaning or rebuilding `code`, `document`, or `combined` does not erase extraction-cache
entries. Their complete execution fingerprints make obsolete entries unreachable without
coupling one domain's cleanup to another domain's extractor work.

- From the CLI: `vaultspec-rag index --rebuild --type document` (or `--type combined`),
  or `vaultspec-rag clean document` followed by a fresh index. See
  [rebuild from scratch](search-and-index.md#rebuild-from-scratch) for the full rebuild
  and clean surface.
- From MCP: use the targeted document or combined reindex and clean tools.

The filesystem watcher routes a changed matched file (an edited `.pdf`, for example)
through your extractor on the same debounce and cooldown machinery as code changes. See
[keep the index fresh automatically](service-mode.md#keep-the-index-fresh-automatically)
for the watcher's timing knobs.

## Failure visibility

Coverage gaps are the problem this feature exists to remove, so they're never silent.
Files skipped by an `on_error = "skip"` rule are counted and listed on every path:

- `IndexResult.preprocess_skipped` and `preprocess_failures` on a full index,
- the `~N` suffix on the `vaultspec-rag server jobs` reindex summary,
- the `preprocess_skipped` and `preprocess_failures` fields in
  `vaultspec-rag index --json`,
- and a warning in the service log for every skip.

Success is just as visible. Extractors run in worker subprocesses whose own logging
never reaches the service log, so the indexer counts every rule-fed file and surfaces
the tally where the skips already live: `IndexResult.preprocess_ok`, the
`preprocess_ok` field in `vaultspec-rag index --json` and on the reindex job record,
and the `preprocess_rules` / `preprocess_ok` fields on the service log's
`service.index completed` event. A run whose rules matched nothing reports
`preprocess_ok=0` there — the discriminating signal when rule-fed content seems to be
missing from the index.

For a non-interactive client of the resident service, two response fields carry the
same visibility. A reindex job record from `/jobs` (and `vaultspec-rag server jobs --json`) carries `preprocess_skipped` and `preprocess_failures`, so the client sees
exactly which files a hook failed to extract. The `/reindex` response also includes a `preprocess` pre-flight
block reporting whether the root ships a config, its resolved rule count, and the
effective mode, mirroring the notice `server start` prints - so a client learns whether
hooks will fire *before* the job runs.

## Size limits

Input and output are both bounded. Source bytes are streamed and checked against the
active support profile and optional `max_source_bytes` before an extractor launches.
Emitted encoded bytes, unit counts, payloads, queue weight, subprocess output, timeout,
and no-progress time are bounded independently. A limit failure remains a typed per-file
outcome and cannot silently publish the file as converged. See the
[configuration reference](configuration.md#core-variables) for the operational ceilings.

## Security posture

A root's `.vaultragpreprocess.toml` **is code execution with your privileges**. When you
index a repository, its preprocess rules run as arbitrary local commands under the account
running the service - the same trust class as running that repo's `make`, `npm install`,
or any of its build scripts. The rule is simple and load-bearing: **do not index a
repository you would not build.** Indexing a repo is an act of trust in that repo, so its
hooks run **by default**, with no consent prompt and no OS containment between a
`/reindex` call and the hook running.

Because the hook runs with your privileges, its filesystem and network access are those of
the account running the service. It can read and write what you can, and reach the network
as you can. Treat `.vaultragpreprocess.toml` as executable project configuration and review
it exactly as you would a build script or a CI job before running it.

Two bounds still apply to every hook, and they earn their place at near-zero cost rather
than as a security boundary:

- **Secrets** - the child runs under a curated environment stripped of every
  `VAULTSPEC_RAG_*` knob and every credential (Qdrant API key, HF/cloud tokens, Git
  tokens), so a hook inherits none of the daemon's secrets.
- **Process, time, and output bounds** - the hook runs out-of-process (a subprocess
  grandchild, which also keeps it off the GPU worker), with the project root as its
  working directory (so `uv run`, `npm exec`, and other project launchers resolve the
  project exactly as they do when you validate a rule with `preprocess run-one`), a
  wall-clock `timeout_s`, and stdout/stderr caps, so a misbehaving extractor is bounded
  in time and output rather than left to run away.

`vaultspec-rag preprocess status` reports whether a root ships a config, its resolved rule
count, and the effective mode.

`VAULTSPEC_RAG_PREPROCESS=off` is the **kill switch** and wins over everything: no root's
rules load, ever. Mirrored as `--no-preprocess` on `server start` and `index`. See the
[configuration reference](configuration.md#preprocessing) for the full variable and flag
inventory.

One operational note: the index tracks the preprocess configuration it was built with, so
changing the effective mode for a root (toggling `off`) triggers an automatic rebuild on
the next index run - correct, but expensive on a large corpus.

## Parser capability is not admission

The indexer has plain-text and HTML-normalization capabilities that explicit routes may
use for formats without an AST grammar. Those capabilities do not make every readable or
supported extension source code. The source profile or an explicit `target` decides
ownership first; only then does the owning pipeline select a parser or extractor. This
separation is what keeps arbitrary XML, schemas, workbooks, generated data, and other
project material out of code indexing by default.

## Illustrative extractors (project-side, not shipped)

These sketches show the schema generalizing across formats. They're examples for your
own `tools/`, not dependencies of vaultspec-rag. Licences are flagged because extractor
choice affects your project's licence posture.

**PDF - `pypdf` (BSD-3-Clause):**

```python
import json, sys
from pypdf import PdfReader  # BSD-3-Clause

src = sys.argv[1]
reader = PdfReader(src)
units = [
    {"text": page.extract_text() or "",
     "anchor": f"{src}#page={i + 1}",
     "locator": {"kind": "page", "value": i + 1}}
    for i, page in enumerate(reader.pages)
]
print(json.dumps({"schema_version": 1, "preprocessor_id": "pypdf",
                  "preprocessor_version": "1.0", "source_path": src, "units": units}))
```

`PyMuPDF` / `fitz` is faster but **AGPL-3.0**, which infects your project's licence; prefer
`pypdf` (BSD-3) or `pdfplumber` (MIT) for a licence-clean project.

**XLSX - `openpyxl` (MIT):** iterate worksheets, then rows; the sheet name is the
locator (`{"kind": "sheet", "value": ws.title}`). Legacy `.xls` needs `xlrd` (BSD) or a
conversion step.

**DOCX - `python-docx` (MIT):** iterate paragraphs; the locator is the paragraph index
(Word has no render-time page numbers).

**XML / XSD - stdlib `xml.etree` (PSF):** walk elements, emit element text with a
tag-path anchor; reach for `lxml` (BSD) only if you need XPath or source line numbers.

## See also

- [Configuration reference](configuration.md) - every environment variable, including
  the preprocess and HTML-strip knobs.
- [Search and index your project](search-and-index.md) - build, refresh, rebuild, and
  clean the index that drives preprocessing.
- [Run the background service](service-mode.md) - the resident watcher that re-extracts
  changed files automatically.
- [Support and help](../README.md#support-and-help) - where to ask questions and file
  issues.
