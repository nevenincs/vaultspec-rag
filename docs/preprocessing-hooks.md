# Document preprocessing hooks

vaultspec-rag indexes Markdown vault docs and source code out of the box. A large
fraction of a real project's grounding material, though, lives in formats the indexer
can't read directly: PDFs, spreadsheets, Word documents, XML schemas, and large HTML
pages that index poorly as raw markup.

Preprocessing hooks let your project supply its own extraction logic for those formats.
You register a command per file pattern. vaultspec-rag runs it, validates the output
against a versioned schema, and indexes the extracted text first-class. The indexed chunks
are searchable with anchors that deep-link back into the original document. vaultspec-rag
never learns your formats; it owns the contract and runs your extractor.

## How it works

1. Add a `.vaultragpreprocess.toml` to your project root (a sibling of
   `.vaultragignore`) mapping file patterns to extraction commands.
1. During indexing, a file matching a rule is handed to your command, which prints one
   JSON document on stdout.
1. vaultspec-rag validates that JSON, turns it into searchable chunks (carrying your
   anchors and locators), and indexes them.
1. Search results for those chunks surface the source path and an anchor (for
   example `report.pdf#page=12`) instead of a line number.

vaultspec-rag indexes a matched file even when its extension is unsupported, it exceeds
the source-size cap, or it's binary. Your extractor turns it into text. A preprocess rule
never re-includes files excluded by `.gitignore` or `.vaultragignore`. Ignore always wins.

## Configure rules

Create `.vaultragpreprocess.toml` at the project root:

```toml
version = 1

[[rule]]
pattern  = "*.pdf"                 # gitignore-style glob (same dialect as .vaultragignore)
command  = "my-pdf-extract {path}" # {path} is replaced with the file path
on_error = "skip"                  # skip | fail | passthrough  (default: skip)
timeout_s = 60                     # wall-clock bound for the command

[[rule]]
pattern  = "docs/**/*.xlsx"
command  = "python tools/xlsx_extract.py {path}"
priority = 10                      # lower priority sorts first; first matching rule wins; ties break by file order
```

Rule fields:

- **`pattern`** (required) - one gitignore-style glob. Add more `[[rule]]` tables for
  more patterns.
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

- `preprocess list` prints each resolved rule with its pattern, priority, failure
  handling, timeout, and command, sorted in precedence order.
- `preprocess check` strictly validates `.vaultragpreprocess.toml` and reports the first
  defect. It's the only command that fails (exit 1) on a bad config; `list` and
  `run-one` load rules leniently and degrade instead.
- `preprocess run-one <path>` runs the matching rule against one file and prints the
  validated output, with no indexing side effect. It exits 1 only when the extractor
  itself aborts, not on a config defect.

All three accept `--json` for scripting.

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

## Cache and incremental indexing

Successful extraction output is cached under the data directory, keyed on the source
content hash plus your command (or `entry_point`) and the schema version. An unchanged
file isn't re-extracted on a full or restart reindex. A changed file produces a new hash
and is re-extracted. Only successful outputs are cached, so a transient extractor failure
is never made sticky.

To force re-extraction of unchanged files after upgrading your extractor, either change
the rule's command (or `entry_point`) or run a clean rebuild, which drops the cache:

- From the CLI: `vaultspec-rag index --rebuild --type code` (or `--type all`), or
  `vaultspec-rag clean code` followed by a fresh index. See
  [rebuild from scratch](search-and-index.md#rebuild-from-scratch) for the full rebuild
  and clean surface.
- From the MCP tools: `reindex_vault(clean=true)` or `reindex_codebase(clean=true)`.

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

## Size limits

The source-size cap is relaxed for matched files (a 12 MB PDF is legitimate). The cap
instead applies to the **emitted** text via `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES`
(default 10 MiB), so a runaway extractor that emits tens of megabytes is skipped while a
large PDF that distills to a few kilobytes indexes fine. See the
[configuration reference](configuration.md#core-variables) for this and the other
environment variables.

## Security posture

Preprocessors are arbitrary project code executed by the indexing service. They run
**only** when declared in the project-root `.vaultragpreprocess.toml`, the same trust
model as the project's own code and build scripts. Treat `.vaultragpreprocess.toml` as you
would any executable project configuration. Review it in code review, and don't point it at
untrusted commands.

## Adjacent improvements

Two related changes help every project, with or without hooks:

- `.txt`, `.xml`, `.xsd`, and `.properties` are indexed as plain text by default.
- `.html` sources are normalized to text (tags, `script`, and `style` stripped) before
  chunking, so HTML hits carry semantic content instead of markup. Disable with
  `VAULTSPEC_RAG_HTML_STRIP=0`.

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
