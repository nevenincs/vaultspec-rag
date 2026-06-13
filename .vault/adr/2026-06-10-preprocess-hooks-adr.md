---
tags:
  - '#adr'
  - '#preprocess-hooks'
date: '2026-06-10'
modified: '2026-06-10'
related:
  - "[[2026-06-10-preprocess-hooks-research]]"
---

# `preprocess-hooks` adr: `document preprocessing hook infrastructure` | (**status:** `accepted`)

## Problem Statement

Downstream projects run vaultspec-rag as a resident index/search service over large mixed
corpora, but high-value grounding material is invisible to the indexer when it is binary
(PDF, XLS/XLSX, DOCX), carries an unsupported extension (XSD, plain-text tails like
`.txt/.xml/.properties`), or indexes poorly as raw markup (large structured HTML). These
formats are domain-specific; vaultspec-rag must not learn them. This ADR commits the
architecture for a **general preprocess-hook infrastructure** — any project registers its
own extraction logic against a versioned contract vaultspec-rag owns, and the output is
indexed first-class. Tracked upstream as issue 185; derived from the approved research.
The decisions below (D1–D13) are terms of art that the implementation plan and every
execution step cite directly.

## Considerations

- **Sibling-of-`.vaultragignore` precedent.** The ignore file is root-only, line-parsed,
  compiled to a `pathspec.GitIgnoreSpec`, OR-combined with `.gitignore` (ignore wins), and
  warns-and-degrades on read error. The new config must feel identical to authors.
- **The two CPU/GPU rules are load-bearing.** `index-workers-stay-cpu-only` and
  `gpu-consumer-single-thread` constrain where arbitrary preprocessor code may run. The
  embed/upsert seam (single GPU consumer owning `gpu_lock`) must stay untouched.
- **Untrusted versioned boundary.** Preprocessor output is cross-process JSON from project
  code; it needs schema validation and per-file fault isolation, mirroring how the repo
  already treats its MCP wire boundary with pydantic v2 (a core dependency).
- **Incremental and watcher already exist.** The PR-152 targeted-reindex path
  (`incremental_index(changed_paths=...)`) and the watcher's debounce/cooldown/single-writer
  machinery are stable parents; preprocessing must slot beneath them, not beside them.
- **Trust model is decided.** Preprocessors are arbitrary project code; they run only when
  declared in the project-root config — same trust as the project's own code — stated
  plainly in docs. This ADR does not sandbox; it isolates by process where it cheaply can.

## Constraints

- **`entry_point` (in-process) preprocessors cannot be made CPU-only-safe or timed out.**
  Arbitrary user code imported into a spawn worker can `import torch`/init CUDA (defeating
  the `index-workers-stay-cpu-only` lazy-import invariant) and has no portable safe
  interrupt for synchronous CPU-bound callables. This is the single load-bearing safety
  tension; D6 and D9 resolve it.
- **Local-mode Qdrant ignores payload indexes** (server-mode only). Index declarations stay
  correct for completeness but yield no local filter pushdown — a known prior finding.
- **Spawn workers receive plain paths, not the config object.** Any knob the worker needs
  (resolved rules, `html_strip`, emitted-size cap) must be threaded into the worker call;
  workers cannot read parent config state.
- **No new heavy dependencies.** `tomllib`, `html.parser`, `subprocess`, `pathspec`,
  `pydantic` are all already available; the feature adds none. Illustrative extractors
  (pypdf, openpyxl, python-docx, xml.etree) live **project-side**, never in vaultspec-rag.
- **Parent stability.** `.vaultragignore` resolution, the spawn-pool chunk path, the GPU
  consumer, `incremental_index(changed_paths=...)` (PR 152), and the jobs registry are all
  shipped and stable. No frontier-risk dependency.

## Implementation

The feature layers cleanly below the existing chunk path; the embed/upsert seam is never
touched. The numbered decisions are the contract.

**D1 — Registration config.** A root-only `.vaultragpreprocess.toml`, resolved per-root
inside `CodebaseIndexer` via a new `_build_preprocess_rules()` (mirroring
`_build_vaultragignore_spec`), parsed read-only with stdlib `tomllib`. It is an
array-of-`[[rule]]` tables plus a top-level `version`. Each rule: `pattern` (one
gitignore-style glob, matched with `pathspec.GitIgnoreSpec` for dialect parity), **exactly
one of** `command` or `entry_point`, optional `priority` (lower = higher precedence),
`on_error` (`skip` | `fail` | `passthrough`, default `skip`), command-only `timeout_s`, and
an opaque `[rule.options]` sub-table forwarded to the preprocessor. The config is structured
per-root data and does **not** live in `config.py` (scalar knobs only).

**D2 — Matching determinism and composition.** Rules sort once at construction by
`(priority, file_index)`; the first whose `pattern` matches wins. Ignore wins absolutely —
a preprocess match never resurrects a `.gitignore`/`.vaultragignore`-excluded file. A
preprocess match **does** expand the indexable-extension set: a matched `.pdf` is admitted
even though it is not in `SUPPORTED_EXTENSIONS`. This is the one deliberate, scoped
exception to the extension gate, distinct from the inviolable ignore boundary.

**D3 — Config error policy.** A missing or malformed `.vaultragpreprocess.toml` degrades
(warn, zero rules — never wedge the resident service). A per-rule schema violation (both or
neither of `command`/`entry_point`; unknown `on_error`; unresolvable `entry_point`) drops
that rule with a warning and keeps the valid ones. Hard-fail (non-zero exit) is reserved
for an explicit validation verb (D13).

**D4 — Output schema.** Preprocessor output is validated at ingest by a pydantic v2
`PreprocOutput` wrapper: `schema_version: int`, `preprocessor_id: str`,
`preprocessor_version: str`, `source_path: str`, **exactly one of** `units: list[PreprocUnit]` or `text: str`, plus a doc-level `metadata` dict. `PreprocUnit`: `text`
(required), optional `title`/`section`/`anchor`, optional `locator { kind: byte|page|sheet|line|char|none, value: int|str, end?: int|str }`, and a `metadata` dict
whose values are JSON scalars/lists. All models set `extra="forbid"`. The `units`/`text`
XOR is enforced by a model validator. In `text` mode the indexer runs the emitted text
through the existing `TextSplitter` path, so a preprocessor that only extracts text need
not also chunk.

**D5 — Schema versioning and fault isolation.** The indexer pins `SUPPORTED_SCHEMA_VERSION = 1`. `model_validate` runs per-source-file inside a `ValidationError` handler that logs
and skips — never raising out of the indexing loop, matching the established per-file
isolation. A newer `schema_version` is rejected with an explicit "upgrade vaultspec-rag"
per-file error; an older one is accepted if still constructable (adapter table reserved for
when v2 lands). The wire format is one JSON object per invocation on **stdout** (primary),
with an optional sidecar cache file (D7) for expensive extractors. Output never carries
`vector`/`sparse_*` — embedding is the GPU consumer's exclusive job.

**D6 — Execution model.** A `preprocess_decoded(path, root_dir, rules, ...)` step is
inserted at the top of **both** `chunk_file` and `chunk_and_hash_file` in the CPU-only
spawn worker (after read+hash, before decode/chunk), so emitted text replaces `content` and
full-index/incremental stay in chunk-identity parity. The **`command`** form runs the real
compute in a `subprocess.run` grandchild — a separate OS process that cannot pollute the
worker import chain or CUDA state, so `index-workers-stay-cpu-only` holds **by
construction** — and is time-bounded by `subprocess.run(timeout=rule.timeout_s)` (mirroring
the existing deadline-bounded GPU-consumer shutdown), with `TimeoutExpired` → preprocess
skip. The embed/upsert seam and the single GPU consumer are untouched, so
`gpu-consumer-single-thread` is respected.

**D7 — Cache.** Re-preprocessing is keyed on `(source_hash, preprocessor_id, preprocessor_version, schema_version)`, reusing the existing byte-identical blake2b source
digest. Output is cached one JSON per source under
`.vault/data/search-data/preprocess-cache/<sha-prefix>/<source-hash>.json`, written
atomically (`.tmp` + `os.replace`); per-source files avoid a single-writer manifest
bottleneck across parallel workers, and the shard prefix bounds directory size.
Version-bump precision falls out for free: a version change alters the key (filename) →
miss → re-run, while sources matched by unchanged rules keep hitting their old cache. A
`clean=True` rebuild `rmtree`s the cache subtree; incremental runs leave orphans (harmless,
bounded by churn).

**D8 — Incremental, watcher, single-writer.** Because preprocessing lives **below**
`_chunk_paths` / `incremental_index(changed_paths=...)`, a changed preprocessable file
routes preprocess → cache → chunk transparently with no new incremental plumbing, and the
watcher routes it through the **same** debounce/cooldown and `_writer_lock` single-writer
machinery unchanged — **except** the three extension-gate sites become preprocess-rule-aware
so a `.pdf` change actually triggers a reindex: the watcher's `_is_code_change`, the
full-scan extension gate, and the scoped-path extension gate.

**D9 — `command`-only in v1; `entry_point` deferred.** v1 ships the **`command`** rule form
only. It is uniformly process-isolated, cleanly timed out, and CPU-only-safe by
construction — the smallest blast radius that satisfies the trust model. The `entry_point`
form is **deferred to a follow-up** because it cannot be CPU-only-enforced or bounded
in-worker; when it lands it will carry its own ADR resolving whether to run it in-worker
(accept-and-document the contract) or out-of-process (uniform isolation). The config parser
still recognises `entry_point` syntactically and rejects it in v1 with a clear "not yet
supported" per-rule message (D3), so configs are forward-shaped.

**D10 — Size cap.** For a preprocess-matched file the source extension, `_MAX_FILE_SIZE`,
and binary gates are relaxed (a 12 MB binary PDF is legitimate). The cap moves to **emitted
text length**, enforced inside the worker after preprocessing via a new
`preprocess_max_emitted_bytes` config knob (following the `_RAG_DEFAULTS` +
`_ENV_OVERRIDE_MAP` pattern) — never by overloading `_MAX_FILE_SIZE`, whose semantics now
differ. Over-cap emission is a preprocess skip (D11).

**D11 — Failure visibility (no-swallow).** `IndexResult` gains `preprocess_skipped`,
`preprocess_failed`, and a `preprocess_failures` file list (default-valued so existing
constructors stay valid). `FileChunkResult` carries per-file preprocess status back to the
orchestrator, which accumulates counts and the file list where it already inspects every
result. Jobs/watcher summary strings append `~skipped !failed` when non-zero, and the CLI
`--json` source dicts gain the three fields. Per the no-swallow mandate every skip/fail
**both** logs a warning **and** increments a surfaced counter.

**D12 — Storage and surfacing.** Preprocessed units are stored in a dedicated `preproc_docs`
Qdrant collection (they are neither code nor vault markdown; overloading either collection's
KEYWORD indexes confuses the filter builders). Payload: `source_path → path` (KEYWORD,
required for purge-by-path reconciliation), `preprocessor_id` (KEYWORD), `preprocessor_version`
/ `schema_version` (unindexed), unit `text → content`, `title`, optional KEYWORD `section`,
unindexed `anchor`, and a **split** locator — `locator_value_int` (INTEGER, numeric kinds)
vs `locator_value_str` (KEYWORD, string kinds) since a polymorphic field cannot take one
typed index. Free-form metadata is stored under one payload key, with an opt-in per-rule
allowlist promoting selected keys to top-level KEYWORD fields (never auto-index arbitrary
keys). Stored-chunk ID: `source_path:locator_kind:locator_value:blake2b(text)`, falling back
to the `path:line_start-line_end:hash` form for text-split units with no native locator.
Surfacing `anchor`/`locator` to users requires `SearchResult`, the pydantic
`SearchResultItem`, and the CLI renderer to be edited in lockstep, populated at
`_map_codebase_results`.

**D13 — CLI surface and the two adjacent asks.** v1 adds a minimal `vaultspec-rag preprocess`
verb group consistent with existing CLI conventions and the `--json` envelope: `preprocess list` (resolved rules for the root), `preprocess check` (validate the config — the only
hard-fail path, non-zero on invalid), and `preprocess run-one <path>` (run the matching rule
against one file and print the validated `PreprocOutput`, for authoring/debugging — no
indexing side effect). Independently: **(adjacent-a)** add `.txt`, `.xml`, `.xsd`,
`.properties` to `LANGUAGE_MAP` (grammar `None`; labels `text`/`xml`) and bump the test
floor; **(adjacent-b)** an `html_strip` bool (default **on**, `VAULTSPEC_RAG_HTML_STRIP`)
strips tags from `.html` via stdlib `html.parser` inside the worker (threaded in as a call
parameter), with raw-markup fallback on any parse error.

## Rationale

The architecture follows the established seams rather than cutting new ones, which is why
the blast radius stays small. D1–D3 reuse the `.vaultragignore` resolution, parsing, and
degrade-on-error precedent verbatim, so the config is learnable in one read. D4–D5 treat
preprocessor output exactly as the codebase already treats its untrusted MCP wire boundary —
pydantic v2, `extra="forbid"`, per-file `ValidationError` isolation — inheriting a proven
fault model. D6 and D9 are the crux: by shipping the `command` form first and running it in
a subprocess grandchild, the load-bearing `index-workers-stay-cpu-only` constraint holds by
process construction with no trust assumptions, and `timeout_s` is enforceable; deferring
`entry_point` removes the one mechanism that could violate both CPU/GPU rules. D7 reuses the
existing blake2b digest and atomic-sidecar idiom so version-bump precision is a free
consequence of key composition. D8 exploits the fact that PR-152 already routes changed
paths through `_chunk_paths`, so preprocessing inherits incremental and watcher behaviour by
position. D10–D11 close the two honesty gaps the research surfaced (the wrong size axis, and
silently-swallowed coverage loss). Grounding for every claim is in the research findings
F1–F8.

## Consequences

- **Gains.** Any project makes previously-invisible binaries first-class with a few lines of
  TOML and a small extractor script; the contract generalises across PDF/XLSX/DOCX/XML and
  arbitrary custom types; coverage gaps become visible counts instead of silent absence; the
  two adjacent asks help every project immediately, hook or not.
- **Costs and difficulties.** A third Qdrant collection adds a surface to maintain and to
  reconcile on delete. Result surfacing touches three types in lockstep (a real but bounded
  edit). Threading rules/knobs into spawn workers is fiddly and must stay pickle-safe.
  `command` preprocessors fork a subprocess per matched file — fine at the corpus scale
  described, but a pathological rule that matches thousands of tiny files pays process-spawn
  overhead; `timeout_s` and the emitted-size cap bound the damage, not the count.
- **Honest limits.** v1 cannot run in-process Python extractors (`entry_point`); projects
  needing them wait for the follow-up or wrap their logic in a `command` script. Local-mode
  Qdrant gives no filter pushdown on the new payload indexes. The trust model is explicit,
  not enforced: a malicious project-root config is a project-trust failure, by design.
- **Pathways opened.** The `entry_point` follow-up; richer locator-aware result rendering
  (page/sheet deep-links in the UI); a future `preprocess add` authoring verb (the one case
  that would justify `tomlkit` round-trip writing); and a sidecar-cache warm-up path for
  OCR-class extractors.

## Post-review amendments

The code review (audit `2026-06-11-preprocess-hooks`) reconciled three decisions with the
as-built implementation. These amendments are authoritative over the original decision text
above:

- **D12 (storage), amended.** Preprocessed units are stored in the existing `codebase_docs`
  collection with extended `CodeChunk` payload (`source_path`, `preprocessor_id`, `anchor`,
  split `locator_value_int`/`locator_value_str`), **not** a dedicated `preproc_docs`
  collection. This was a deliberate, user-approved deviation: it keeps the single GPU
  consumer and the embed/upsert/search seam untouched (the rule-critical invariant) and was
  the smaller path to a tested v1. The review confirmed the overload is internally
  consistent — no existing code-search filter breaks, and purge-by-source-path reconciles
  via the existing `path`-keyed deletion. A dedicated collection remains a possible future
  refinement.

- **D7 (cache key), amended.** The cache key is `(source_hash, command, schema_version)`,
  not `(source_hash, preprocessor_id, preprocessor_version, schema_version)`. The producing
  `preprocessor_version` is known only from the output, so it cannot participate in a
  read-time lookup; the rule's `command` is the project's invalidation lever (change the
  command, or run a clean rebuild, to force re-extraction). A version bump that leaves the
  command string unchanged will serve cached output until a clean rebuild — documented in
  the hooks guide.

- **D11 (failure visibility), amended.** `IndexResult` carries `preprocess_skipped` and
  `preprocess_failures` (two fields, not three). `on_error=fail` aborts the run by raising
  rather than incrementing a separate `preprocess_failed` counter, so that field and the
  `!failed` summary token are intentionally absent. Skip counts are surfaced on **all**
  index paths (full, incremental, scoped/watcher) and in the jobs summary and CLI `--json`.

## Codification candidates

- **Rule slug:** `preprocessors-run-out-of-process`.
  **Rule:** Project-supplied preprocessors execute only as `command` subprocesses
  (separate OS process, bounded by `timeout_s`); never import or run arbitrary project
  extractor code inside the CPU-only spawn worker's interpreter, so the
  `index-workers-stay-cpu-only` invariant holds by construction. (Promote only if the
  `entry_point` follow-up reaffirms out-of-process as the standing default.)

- **Rule slug:** `preprocess-coverage-is-never-silent`.
  **Rule:** Every file a preprocess rule skips or fails must both log a warning and
  increment a surfaced `IndexResult` counter that reaches `status`/`jobs`/CLI `--json`;
  silent index-coverage gaps are the failure mode this feature exists to remove.
