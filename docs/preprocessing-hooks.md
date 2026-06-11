# Document-preprocessing hooks

vaultspec-rag indexes Markdown vault docs and source code out of the box. A large
fraction of a real project's grounding material, though, lives in formats the indexer
cannot read directly: PDFs, spreadsheets, Word documents, XML schemas, and large HTML
pages that index poorly as raw markup.

Preprocessing hooks let **your project** supply its own extraction logic for those
formats. You register a command per file pattern; vaultspec-rag runs it, validates the
output against a versioned schema, and indexes the extracted text first-class - searchable
with deep-link anchors back into the original document. vaultspec-rag never learns your
formats; it owns the contract and runs your extractor.

## How it works

1. You add a `.vaultragpreprocess.toml` to your project root (a sibling of
   `.vaultragignore`) mapping file patterns to extraction commands.
1. During indexing, a file matching a rule is handed to your command, which prints one
   JSON document on stdout.
1. vaultspec-rag validates that JSON, turns it into searchable chunks (carrying your
   anchors and locators), and indexes them.
1. Search results for those chunks surface the source path and a deep-link anchor (for
   example `report.pdf#page=12`) instead of a line number.

A matched file is indexed even when its extension is unsupported, it exceeds the
source-size cap, or it is binary - your extractor turns it into text. Files excluded by
`.gitignore` or `.vaultragignore` are never resurrected by a preprocess rule; ignore
always wins.

## Configuring rules

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
priority = 10                      # lower number wins when several rules match
```

Rule fields:

- **`pattern`** (required) - one gitignore-style glob. Add more `[[rule]]` tables for more
  patterns.
- **One of `command` or `entry_point`** (required, exactly one):
  - `command` is a command template. `{path}` is substituted with the source file path.
    The command is split with shell-style tokenisation and run **without** a shell, so
    spaces and metacharacters in paths cannot inject. On Windows, **use forward slashes**
    in the interpreter/script path (a backslash path breaks the POSIX-style tokeniser even
    inside a TOML literal).
  - `entry_point` is a `"module:callable"` reference. The callable
    (`def my_callable(source_path: str) -> Mapping | BaseModel`) is run **out-of-process**
    by vaultspec-rag (same isolation and `timeout_s` bound as `command`); the module must
    be importable in the service's Python environment.
- **`priority`** (optional, default 100) - lower sorts first; ties break by file order.
  The first matching rule wins.
- **`on_error`** (optional, default `skip`):
  - `skip` - drop the file from the index and report it (never a silent gap).
  - `fail` - abort the whole index run (use when missing a document is unacceptable).
  - `passthrough` - index the raw file unprocessed instead of failing.
- **`timeout_s`** (optional) - kill the command after this many seconds and treat it as a
  failure per `on_error`.
- **`[rule.options]`** (optional) - an opaque table forwarded to your preprocessor for its
  own use.

> **Note.** Both `command` and `entry_point` rules run out-of-process (a subprocess), so
> they share the same CPU-only isolation and `timeout_s` bound. An `entry_point` callable
> must be importable in the service's environment and return a mapping (or pydantic model)
> shaped like the output schema below.

Inspect and validate your configuration:

```bash
vaultspec-rag preprocess list            # show resolved rules, in precedence order
vaultspec-rag preprocess check           # validate the config; non-zero exit on error
vaultspec-rag preprocess run-one a.pdf   # trial the matching rule against one file
```

All three accept `--json`. `check` is the only command that fails (non-zero exit) on an
invalid config; `list` and `run-one` degrade gracefully.

## The output schema

Your command receives a source file path and prints **one JSON object** on stdout. It is
the contract between your extractor and the indexer; invalid output is a per-file error,
never a crash.

```jsonc
{
  "schema_version": 1,                 // required; the schema major (currently 1)
  "preprocessor_id": "pdf-extract",    // required; your extractor's id
  "preprocessor_version": "1.2.0",     // required; your extractor's version
  "source_path": "docs/report.pdf",    // required; the path you were given
  // EXACTLY ONE of `units` or `text`:
  "units": [                           // (a) pre-chunked units
    {
      "text": "Quarterly revenue ...", // required
      "title": "Q3 Results",           // optional
      "section": "Finance > Q3",       // optional
      "anchor": "docs/report.pdf#page=12", // optional deep-link into the source
      "locator": {"kind": "page", "value": 12}, // optional; kind in
                                                 // byte|page|sheet|line|char|none
      "metadata": {"author": "ACME"}   // optional; JSON-scalar values
    }
  ],
  "text": "....",                      // (b) plain extracted text (indexer chunks it)
  "metadata": {}                       // optional document-level metadata
}
```

Rules:

- Provide **either** `units` (you chunk) **or** `text` (the indexer runs it through the
  normal text splitter) - never both, never neither.
- Unknown fields are rejected, so a typo is a loud validation error.
- A `schema_version` newer than the running vaultspec-rag is rejected with an "upgrade
  vaultspec-rag" message.
- The `anchor` is surfaced verbatim in search results; the `locator` is rendered as, for
  example, `page 12` or `sheet Summary`.

## Caching and incremental indexing

Successful extraction output is cached under the data directory, keyed on the source
content hash plus your command. An unchanged file is not re-extracted on a full or restart
reindex. A changed file produces a new hash and is re-extracted; to force re-extraction of
unchanged files after upgrading your extractor, change its command or run a clean rebuild
(`reindex_*(clean=true)`), which drops the cache. The filesystem watcher routes a changed
matched file (for example an edited `.pdf`) through your extractor on the same
debounce/cooldown machinery as code changes.

## Failure visibility

Coverage gaps are the problem this feature exists to remove, so they are never silent.
Files skipped by an `on_error = "skip"` rule are counted and listed:

- `IndexResult.preprocess_skipped` / `preprocess_failures` on a full index,
- the `~N` suffix on the `server service jobs` reindex summary,
- the `preprocess_skipped` / `preprocess_failures` fields in `vaultspec-rag index --json`,
- and a warning in the service log for every skip on every path.

## Size limits

The source-size cap is relaxed for matched files (a 12 MB PDF is legitimate). The cap
instead applies to the **emitted** text via `VAULTSPEC_RAG_PREPROCESS_MAX_EMITTED_BYTES`
(default 10 MiB), so a runaway extractor that emits tens of megabytes is skipped while a
large PDF that distils to a few kilobytes indexes fine.

## Security posture

Preprocessors are arbitrary project code executed by the indexing service. They run
**only** when declared in the project-root `.vaultragpreprocess.toml` - the same trust
model as the project's own code and build scripts. Each preprocessor (both `command` and
`entry_point`) runs in a separate OS process, so it cannot touch the indexer's GPU or
interpreter state, and `timeout_s` bounds runaway extractors. The captured output is also
size-bounded so a runaway extractor cannot exhaust memory. Treat `.vaultragpreprocess.toml`
as you would any
executable project configuration: review it in code review, and do not point it at
untrusted commands.

## Adjacent improvements

Two related changes help every project, with or without hooks:

- `.txt`, `.xml`, `.xsd`, and `.properties` are now indexed as plain text by default.
- `.html` sources are normalised to text (tags, `script`, and `style` stripped) before
  chunking, so HTML hits carry semantic content instead of markup. Disable with
  `VAULTSPEC_RAG_HTML_STRIP=0`.

## Illustrative extractors (project-side, not shipped)

These sketches show the schema generalising across formats. They are examples for your own
`tools/`, not dependencies of vaultspec-rag. Licences are flagged because extractor choice
affects your project's licence posture.

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

> `PyMuPDF`/`fitz` is faster but **AGPL-3.0** - it infects your project's licence the
> moment you import it. For a licence-clean project use `pypdf` (BSD-3) or `pdfplumber`
> (MIT); reach for PyMuPDF only under a commercial licence.

**XLSX - `openpyxl` (MIT):** iterate worksheets, then rows; the sheet name is the locator
(`{"kind": "sheet", "value": ws.title}`). Legacy `.xls` needs `xlrd` (BSD) or a conversion
step.

**DOCX - `python-docx` (MIT):** iterate paragraphs; the locator is the paragraph index
(Word has no render-time page numbers).

**XML / XSD - stdlib `xml.etree` (PSF):** walk elements, emit element text with a tag-path
anchor; reach for `lxml` (BSD) only if you need XPath or source line numbers.

A licence-clean stack is `pypdf` + `openpyxl` (+ `xlrd`) + `python-docx` + `xml.etree`, and
never imports PyMuPDF.
