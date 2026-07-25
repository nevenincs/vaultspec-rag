<vaultspec type="config">
## Vaultspec Rules

You MUST respect these rules at all times:

---
name: gpu-discipline
trigger: always_on
---

# GPU discipline

## Rule

- Load torch through the single centralised loader. Never import it directly on
  a compute path.
- Keep service call paths torch-free: MCP server, service client, CLI
  service-control commands.
- Provision the GPU build only. Never accept a CPU wheel silently.
- Run GPU encoding on exactly one dedicated consumer thread that owns the GPU
  lock.
- Never add a second GPU consumer thread. Never use CUDA streams to parallelise
  compute on one device. Never encode inline on the pool-draining thread.
- Hold the GPU lock across forward calls only. Tokenisation, pair assembly,
  tensor post-processing, score conversion and storage I/O go outside it.
- Do CPU-only work in index workers. Never initialise CUDA in one.
- Create the chunk worker pool with `spawn`.
- Keep every `torch` import function-local in every module a worker can reach.
- Bound and liveness-guard every wait that shuts the consumer down.

## Why

- This project is GPU-only and never runs inference on CPU.
- Two compute-bound kernels serialise on one device regardless of streams. The
  only real parallelism is CPU-produce against GPU-consume.
- There is one GPU lock per process. Every millisecond held beyond the forward
  pass serialises every root.
- A spawn worker re-imports its whole chain. A module-scope torch import there
  initialises CUDA in every worker and reintroduces the subprocess CUDA crash
  class.
- Indexing holds the writer lock. An unbounded wait turns one stalled call into
  a wedged indexer.
- A bare install resolves torch from the public index, because the GPU pin is
  workspace-scoped and absent from published wheel metadata.

## How

- Good: a compute site calls the loader and uses what it returns. The loader
  raises on a CPU-only build, an absent GPU, or absent torch, with one message.
- Good: read-only probes that must tolerate a torch-free host keep a guarded
  function-local import and report no CUDA rather than raising. Only exception.
- Good: one consumer thread drains a bounded queue and is the only code touching
  CUDA; shutdown sends its sentinel only while the thread is alive, with a timed
  put and a bounded join.
- Good: build reranker pairs and apply the character cap before the lock; call
  predict inside; convert scores after release.
- Good: a fresh-interpreter test asserts importing the worker leaves `torch` out
  of `sys.modules`.
- Bad: a module-scope `import torch`, or a fresh inline CUDA-availability check
  on a compute path.
- Bad: wrapping result mapping, densification or an upsert in the locked block.
- Bad: constructing an embedding model, calling `torch.cuda.*`, or opening the
  store inside a worker.

---
name: guard-tests-prove-they-can-fail
trigger: always_on
---

# Guard tests prove they can fail

## Rule

- Prove a guard test can fail before trusting it.
- Break the guard, run the test alone, watch it fail on the assertion it names,
  restore, watch it pass. One uninterrupted sequence.
- Never leave a mutation on disk across a pause or a handoff.
- Record both directions where the test's next reader will find them.

## Why

- A passing guard test proves the guard did not crash. Nothing more.
- It cannot tell a rejected forbidden thing from one that never reached the
  check.
- Coverage reporting success over a regressed path is worse than none. It
  consumes the attention that would have gone looking.

## How

- Require the failure to land on the intended assertion, not on an import or a
  collection error.
- Comment the mutation a narrow assertion catches. The next reader loosens an
  unexplained matcher.
- Assert the exact branch. A message shared by several branches passes whichever
  fires.
- Never relax a matcher or edit an expected string to make a guard test pass.
- Applies to guards, interceptions and negative assertions only.

---
name: no-dev-metadata-in-code
trigger: always_on
---

# No dev metadata in code

## Rule

- State the constraint. Never state where it was decided.
- Never write any of these in source, tests, config, comments or docstrings:
  - a dated vault stem
  - a wave, phase or step id
  - a feature name taken from the vault
  - a decision-enumeration token
  - a `.vault/` path
  - a codified rule name
- Vault documents cite code by `path:line`. Code cites nothing.

## Why

- The vault and the harness are removable. A pointer into them dangles once they
  are gone.
- A pointer says where to go. A constraint says what to do.

## How

- Delete the pointer when the prose already states the constraint.
- State the constraint first when it does not, then delete the pointer.
- Repair the sentence. A pointer is usually the object of its clause; deleting
  the token alone strands the sentence.
- Read every removal in the diff. No linter and no gate sees broken prose.
- Keep product vocabulary: indexing `.vault/` markdown, parsing `adr/` doc ids,
  advertising `type:adr`.
- Keep vault-shaped test data. A fixture filename is a value, not a citation.

---
name: pinned-binaries-verify-before-execute
trigger: always_on
---

# Pinned binaries verify before execute

## Rule

- Verify every provisioned native binary against a committed SHA256 pin before
  extraction, and again before execution.
- Never extract or run an unverified artifact.
- Take the digest from a reviewed code constant, never from live release
  metadata.
- Download over HTTPS with a pinned host, and re-check the scheme across
  redirects.
- Discard archive-embedded paths on extraction.

## Why

- Download-then-execute is the load-bearing security boundary.
- A digest read from the same source as the artifact proves nothing.
- Archive-embedded paths enable traversal outside the destination.

## How

- Good: hash the archive and compare to the constant before extracting; flatten
  members by basename; re-hash the extracted binary immediately before spawning.
- Good: resolve an operator-supplied binary through the same supervised path;
  treat a mismatch as a hard failure and delete the partial artifact.
- Bad: extracting before verifying.
- Bad: an extract-all honouring archive-embedded paths.

---
name: rerankers-score-real-content
trigger: always_on
---

# Rerankers score real content

## Rule

- Feed the reranker the token-bounded full candidate content.
- Never feed it a display snippet, a title, or any fixed-width prefix.

## Why

- A fixed-character snippet discards the model's semantic capacity and biases
  ranking toward candidates whose opening characters echo the query.
- It passes every test while silently degrading ranking quality.

## How

- Good: carry the full content on the result object, cap it at a generous
  multiple of the token bound, and let the reranker's tokenizer truncate.
- Bad: passing the display snippet as the document side.

---
name: service-surface
trigger: always_on
---

# Service surface

## Rule

- Implement health, status, jobs, logs and search diagnostics as service-domain
  behaviour. Adapt CLI and MCP to it. Never let an entry point own or duplicate
  it.
- Bound every operator list and tail command. Make them filterable. Bias them to
  current actionable state, not full history.
- Emit exactly one structured envelope on every exit path of a lifecycle verb in
  JSON mode, success and failure alike.
- Treat an already-satisfied request as success: exit zero with an already-done
  status.
- Exit non-zero in both human and JSON mode when the requested state is not
  achieved.

## Why

- Entry points that drift show operators conflicting names, contracts and
  remediation for one condition.
- Full history and unfiltered tails hide running work behind stale noise.
- A broker misreads a non-zero already-running start as a gateway error, and
  must be able to start or stop speculatively.
- A stop that leaves the service running is a failure and must not report
  success.

## How

- Good: filter in the service route, pass the same parameters through the CLI
  verb and the MCP tool, keep the envelope stable across adapters.
- Good: default the jobs view to a bounded set; expose state, failed, job-id and
  since filters; search a bounded log window before returning a filtered tail.
- Good: converge every terminal branch on one success or one failure helper per
  verb, and carry initiator attribution on terminating outcomes.
- Bad: a CLI-only path computing different phases from the service.
- Bad: rendering every recorded job by default.
- Bad: printing human text on a JSON path, or emitting zero or two envelopes.

---
name: storage-discipline
trigger: always_on
---

# Storage discipline

## Rule

- Local mode: one reentrant lock per collection, plus one lifecycle lock for
  open, close, and collection create or drop.
- Server mode: no point-operation locks.
- Never reintroduce a store-wide mutex across collections.
- Acquire the lifecycle lock before any collection lock, never the reverse.
- Keep maintenance read-and-drop only. Never reach a stop, terminate or reclaim
  helper from it. Never import the CLI from a maintenance module.
- Require classification AND a persisted continuous grace window before any
  automatic deletion.
- Archive data-bearing namespaces successfully before destroying them.
- Never auto-touch an unknown or unverifiable namespace.
- Reset the grace clock on any live or unverifiable observation, and persist it
  across restarts.
- Point the Qdrant storage-dir environment variable at a temp path in any test
  that writes the identity sidecar or takes the machine lock.

## Why

- Collections are independent locally, and a remote server handles its own
  concurrency; client-side locking there only caps throughput.
- One store-wide lock dragged a four-second search to a ninety-five-second
  median by sharing a mutex with unrelated scans.
- Maintenance sharing a process with lifecycle verbs reads as the cause whenever
  a daemon dies in the same window.
- A valid root can transiently not exist: an unplugged drive, an offline share,
  a rename, a worktree being recreated.
- Resetting the clock on any contrary observation means races can only extend
  protection, never shorten it.
- The identity sidecar and the machine lock derive from the storage-dir knob,
  not the status-dir knob. Isolating the wrong one writes into the operator's
  real managed directory and contends for the real lock.

## How

- Good: a per-collection lock accessor returning that collection's reentrant
  lock locally and a null context in server mode.
- Good: a fresh-interpreter test asserts no CLI module loads from the
  maintenance modules; a source scan asserts none names a terminate, reclaim or
  stop helper.
- Good: orphaned-only input, per-tier grace windows, riskless empty namespaces
  first under a per-cycle cap, points re-counted immediately before the drop.
- Good: raise on any snapshot failure so the delete is never reached for
  unarchived data.
- Good: a fixture points the storage dir at a temp path, resets config, runs,
  then releases the lock and restores the environment.
- Bad: a store method taking a global lock around a point operation.
- Bad: dropping a namespace on one survey saying its root was missing.
- Bad: destroying a point-bearing namespace after a failed archive.
- Bad: a restart-if-degraded branch in a maintenance cycle.

---
name: vaultspec-cli.builtin
trigger: always_on
---

# Vaultspec Core CLI

This project is vaultspec-managed. See `vaultspec.builtin.md` for framework rules and
workflow concepts.

## Mandate

All `.vault/` reads, mutations, audits, and repairs route through `vaultspec-core`
owning-verb logic; never hand-write frontmatter, filenames, plan structure, or new
`.vault/` documents (editing scaffolded body prose is permitted, see "Allowed manual
edits"). The vaultspec MCP tools are the primary transport where the server is
connected, the `vaultspec-core` CLI verbs otherwise; both terminate in the same
owning-verb logic that enforces templates, taxonomy, wiki-links, and schema, so
bypassing it produces drift the `check` tool and `vaultspec-core spec doctor` will flag.

## Orientation

Orient before working in a project you have no session context for: the `status` tool
reports the in-flight plans and their next open Step, and the `find` tool locates the
documents and features behind them (CLI: `vaultspec-core status [TARGET]`). Orientation
is descriptive, read-only, and the zeroth move, not a pipeline phase.

## Tools and operations

The nine MCP tools cover the hot path by capability: `status` (orientation), `find`
(document and feature discovery), `create` (scaffold documents, batchable), `edit`
(body-prose edits, batchable), `plan_progress` (mark Steps checked or unchecked),
`plan_edit` (author and restructure Step rows), `check` (validate and repair), and the
`discover`/`invoke` gateway that reaches every remaining verb.

Operations without a first-class hot tool fall into two honest bands:

- **Gateway-only, CLI-first:** `sync`, `spec <resource> sync`, and the above-Step plan
  verbs (`tier promote/demote`, `wave`, `phase`, `epic intent`). The `discover`/`invoke`
  gateway also reaches these, but `invoke`'s destructive annotation forces host
  confirmation on every call, so the CLI is the better default even when connected.
- **CLI-only:** `vault feature index`, `spec mcps add/remove/sync`, and `uninstall` have
  no MCP path at all; run them through the CLI.

For anything else, the `discover` tool and the bundled CLI reference
(`.vaultspec/reference/cli.md`, locally resident) are the catalogs of every command,
option, argument, and exit code.

Where the vaultspec MCP server is not connected, the `vaultspec-core` CLI verbs carry
every operation; the bundled CLI reference is the catalog.

## CLI fallback

- Run `vaultspec-core <cmd>`, or `uv run --no-sync vaultspec-core <cmd>` in uv
  environments; `--target DIR`, `--dry-run`, `--json`, `--force`, and `<cmd> --help`
  cover targeting, previewing, and the full flag and exit-code reference.
- Sync-shaped results (`install`, `sync`, `spec <resource> sync`, `migrations run`) read
  with one vocabulary - `created`, `updated`, `unchanged`, `removed`, `restored`,
  `skipped`, `failed`; `unchanged` is a successful no-op, `skipped` carries a reason,
  only `failed` stops the pipeline.

## Allowed manual edits

Permitted: editing body prose of a document scaffolded through the `create` tool or
`vaultspec-core vault add`, and editing sources under `.vaultspec/rules/`, `skills/`,
`agents/`, `hooks/`, or `mcps/` followed by `vaultspec-core sync`. Forbidden:
hand-writing frontmatter, filenames, or new `.vault/` documents, and editing files
inside generated provider directories (`vaultspec-core sync` regenerates them).

---
name: vaultspec-discovery.builtin
trigger: always_on
---

# Codebase and intent discovery

Begin every pipeline phase - Research, ADR, Plan, Execute - by grounding in what the
project already decided and built. The project's own benchmarking is unambiguous: a
semantic-search-led hybrid sweep finds a feature fastest and at the lowest context cost
\- roughly 1.3-2x cheaper than broad keyword search on a large tree - and recalls
governing decisions with near-zero noise. Lead with it. The validated sequence is locate
by meaning, read the epicenter whole, confirm with grep:

1. **Locate by meaning.** For code, lead with
   `vaultspec-rag search "<concept and domain nouns>" --type code` (narrow with
   `--language`/`--path`); it reaches the right file in about one call where broad
   globbing floods context. For decisions and intent,
   `vaultspec-rag search "<intent>" --type vault --doc-type adr` - the directed ADR
   filter, sharper than catch-all `--type vault`. `vaultspec-core status [target]`,
   `vaultspec-core vault list`, and `vaultspec-core vault graph` are first-class for
   orientation, in-flight plan state, and project health - reach for them to get your
   bearings on intent. For a small, well-named module, list the directory.
1. **Read** the epicenter file - or, when extending a feature, the nearest existing
   analogue - in full. This whole-file read is the breakthrough in nearly every run.
1. **Confirm** exact symbols and insertion points with a targeted grep, which is sharper
   than semantic search at exact-symbol lookup.
1. For decision discovery, round out recall by listing `.vault/adr/` and filtering by
   feature - semantic search alone can miss lower-ranked or opaquely-named records.

Do not lead with broad `Glob`/grep sweeps; their context cost scales badly on large
codebases, and grep earns its place at the confirmation step. Where `vaultspec-rag` is
not installed, the `vaultspec-core` discovery verbs and grep carry the same sequence.

---
name: vaultspec-rag.builtin
trigger: always_on
---

# vaultspec-rag — semantic search for code and decisions

Discover by MEANING when you do not know the exact name, instead of grepping keywords or
guessing identifiers. vaultspec-rag does two jobs: find the CODE, and find the DECISIONS -
the ADRs (architecture decision records) that govern it.

Server mode is the default backend. If a search reports the service is down, start it with
`uvx vaultspec-rag server start` (small or offline projects opt into the on-disk local
backend with `--local-only`). The running service auto-reindexes on file changes.
DO NOT manually reindex during normal work.

## Discover code by meaning

`--type code` searches source by meaning. Phrase the query as a short behaviour plus the
concrete domain nouns the target code would use: the behaviour drives semantic matching, the
nouns drive exact matching, so a bare keyword or pure prose finds less than both together.

```
uvx vaultspec-rag search "retry backoff around failed webhook delivery" --type code
```

## Discover architecture decisions

When you need the WHY - the rationale, constraints, or decision behind code - search the
vault's ADRs, not the source. `--type vault --doc-type adr` returns the governing records.

```
uvx vaultspec-rag search "decision on gpu lock scope around the forward pass" --type vault --doc-type adr
```

`--doc-type` also accepts `audit`, `plan`, `reference`, `research`, and `exec` (comma-separate
to union several).

## Cut noise with filters

Semantic search competes production code against its own noise - overlapping tests, parallel
locale files, generated and vendored trees, worktree clones. Code search is production-biased
by default: it hides duplicate/derivative domains (`generated`, `worktree`) and demotes
`tests`, `docs`, `locale`, and `vendored` beneath production. When noise still crowds a page,
narrow by DOMAIN rather than raising `--max-results`. The domains are `prod`, `tests`, `docs`,
`locale`, `generated`, `vendored`, `worktree`.

Steer with inline query tokens (comma-separated, repeatable):

```
uvx vaultspec-rag search "fixture setup helpers exclude:tests" --type code
uvx vaultspec-rag search "auth token validation only:prod" --type code
uvx vaultspec-rag search "translation table lookup include:locale" --type code
```

`exclude:` hides a domain, `only:` keeps just the named domains, and `include:` re-admits a
domain the default profile hides or demotes. Compose with path and category filters:

```
uvx vaultspec-rag search "request handler" --type code --include-path "src/**" --exclude-path "**/legacy/**"
uvx vaultspec-rag search "encode batch" --type code --prefer production
```

The full option set is `uvx vaultspec-rag search --help`. The same search is available through
MCP as the `search_codebase` and `search_vault` tools.

---
name: vaultspec.builtin
trigger: always_on
---

# Spec Skills

This project follows a spec driven development framework and mandates a vaultspec
pipeline of: research -> decision (ADR) -> plan -> verify (+ audit either as closeout or
pipeline start).

The workflow persists the following documents, bound by a single feature tag:

- `.vault/research/yyyy-mm-dd-<feature>-research.md`: The `<Research>` findings.

- `.vault/reference/yyyy-mm-dd-<feature>-reference.md`: A project, code, or research
  grounding `<Reference>`, useful for grounding implementation details prior to ADR
  authoring.

- `.vault/adr/yyyy-mm-dd-<feature>-adr.md`: Research-derived `<ADR>`.

- `.vault/plan/yyyy-mm-dd-<feature>-plan.md`: The `<Plan>` to execute, authored and
  managed through the plan verbs - the `plan_progress` and `plan_edit` MCP tools where
  connected, the `vaultspec-core vault plan` CLI otherwise.

- `.vault/exec/yyyy-mm-dd-<feature>/.../<step>.md`: The individual `<Step Record>`.

- `.vault/exec/yyyy-mm-dd-<feature>/...-summary.md`: The `<Phase Summary>`.

- `.vault/audit/yyyy-mm-dd-<feature>-audit.md`: The `<Audit>` report. A feature with
  multiple audits, references, or research documents disambiguates each with an optional
  narrative infix - `yyyy-mm-dd-<feature>-<topic>-<type>.md` - scaffolded through the
  owning verb's `--topic` flag (`vault add` for audit, reference, and research only),
  never by hand-picking a filename.

- `.vault/index/<feature>.index.md`: The auto-generated `<Feature Index>` linking every
  document for a feature. The index regenerates as a side effect of the `create` and
  `edit` tools; regenerate it manually with `vaultspec-core vault feature index` when
  working through the CLI, and never author it by hand.

Use the following pipeline skills:

- `vaultspec-research`
- `vaultspec-code-research`
- `vaultspec-adr`
- `vaultspec-write`
- `vaultspec-execute`
- `vaultspec-code-review`

The following helper skills are available:

- `vaultspec-curate`
- `vaultspec-documentation`
- `vaultspec-team`
- `vaultspec-projectmanager`

## Documentation Hierarchy

The documentation trail follows a strict dependency graph. Artifacts lower in the
hierarchy should reference those above them. Source code sits outside this hierarchy
entirely: vault documents cite code by `path:line` locator, and tracked source-file
content never references `.vault/` documents, identifiers, or harness contents (opt-in
git commit trailers are the sanctioned linkage channel).

- **Brainstorm** / **Research** / **Reference** (`.vault/research/`,
  `.vault/reference/`)

- **Audits** (`.vault/audit/yyyy-mm-dd-{feature}-audit.md`, optionally
  `.vault/audit/yyyy-mm-dd-{feature}-{topic}-audit.md`)

  - *Depends on:* the artifacts under review (plans, execution records, code)
  - *References:* the artifacts under review

- **Architecture Decision Records (ADR)** (`.vault/adr/`)

  - *Depends on:* brainstorm, research, audits

- **Implementation Plans** (`.vault/plan/`)

  - *Depends on:* ADRs, research, audits, (previous or related feature plans)
  - *Cardinality:* one plan executes one ADR or a cluster of ADRs (the epic roll-up);
    every governing ADR is listed in `related:`. One ADR is never spread across several
    concurrent plans.

- **Execution Records**
  (`.vault/exec/{yyyy-mm-dd-feature}/{yyyy-mm-dd-feature-{phase}-{step}}.md`)

  - *Depends on:* Plans.
  - *References:* The Plan being executed.
  - *Location:* Inside feature-specific folder.
  - *Filename:* `{yyyy-mm-dd-feature-{phase}-{step}}.md` where `{phase}` and `{step}`
    are the canonical container identifiers (`P##`, `S##`) from the plan, zero-padded to
    a minimum of two digits. At `L1` the `{phase}` segment is omitted; at `L3`/`L4` a
    `{wave}` segment (`W##`) is prepended.
  - *Examples:*
    - L1: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-S01.md`
    - L2: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-P01-S01.md`
    - L3 / L4:
      `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-W01-P01-S01.md`

- **Summaries**
  (`.vault/exec/{yyyy-mm-dd-feature}/{yyyy-mm-dd-feature-{phase}-summary}.md`)

  - *Depends on:* Execution Records.
  - *References:* The Plan and key Artifacts produced.
  - *Location:* Inside feature-specific folder.
  - *Filename:* `{yyyy-mm-dd-feature-{phase}-summary}.md` where `{phase}` is the
    canonical Phase identifier (`P##`).
  - *Examples:*
    - L2: `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-P01-summary.md`
    - L3 / L4:
      `.vault/exec/2026-02-04-editor-demo/2026-02-04-editor-demo-W01-P01-summary.md`

- **Feature Indexes** (`.vault/index/{feature}.index.md`)

  - *Auto-generated* as a side effect of the `create` and `edit` tools; regenerate
    manually with `vaultspec-core vault feature index` when working through the CLI,
    never authored by hand.
  - *Filename:* `{feature}.index.md` (no date prefix).
  - *Example:* `.vault/index/editor-demo.index.md`

## Must follow

- We **ALWAYS** use **Obsidian-style Wiki Links** for internal documentation.

- **Always** populate the `related:` field in the YAML frontmatter with
  `'[[wiki-links]]'` (quoted as strings).

- **Never** use relative paths (`../`) in wiki links; assume a flat namespace or
  vault-root resolution.

- **Always** check if a referenced file exists before linking (if possible).

- **Always** include the relevant `#{feature}` tag in the YAML frontmatter using the
  `tags:` field.

- **Always** use the `tags:` field (not `feature:`) as a YAML list.

- **Always** quote wiki-links in YAML: `- '[[file-name]]'`.

## Tag Taxonomy

**ALLOWED TAGS - DO NOT REMOVE - REFERENCE:** `#adr` `#audit` `#exec` `#index` `#plan`
`#reference` `#research` `#{feature}`

Every document in `.vault/` MUST include the required tag pair in the frontmatter
`tags:` field:

- **Directory Tag**: Based on the `.vault/` subfolder location (`#adr`, `#audit`,
  `#exec`, `#index`, `#plan`, `#reference`, `#research`)

- **Feature Tag**: Groups related documents across the feature lifecycle (kebab-case,
  e.g., `#editor-demo`)

**CRITICAL:** No structural tags like `#step`, `#summary`, `#phase*`, or `#design` are
allowed. Every document carries exactly one directory tag plus exactly one `#{feature}`
tag - no more, no less. Any additional tag is read as a second feature tag and fails
validation.

### Directory Tags (Required for ALL documents)

The directory tag is determined by the file's location in `.vault/`:

| Directory           | Tag          | Description                              |
| :------------------ | :----------- | :--------------------------------------- |
| `.vault/adr/`       | `#adr`       | Architecture Decision Records            |
| `.vault/audit/`     | `#audit`     | Audit reports and assessments            |
| `.vault/exec/`      | `#exec`      | Execution records (steps & summaries)    |
| `.vault/index/`     | `#index`     | Auto-generated feature indexes           |
| `.vault/plan/`      | `#plan`      | Implementation plans                     |
| `.vault/reference/` | `#reference` | Implementation references and blueprints |
| `.vault/research/`  | `#research`  | Research and brainstorming               |

### Tag Format

All documents use YAML list syntax with exactly 2 tags (one directory tag, one feature
tag):

```yaml
---
tags:
  - '#plan'
  - '#feature-name'
date: '2026-02-06'
modified: '2026-02-06'
related:
  - '[[related-file]]'
---
```

`modified:` is a CLI-maintained last-modified stamp: set equal to `date:` at scaffold,
refreshed by every mutating verb and by `vaultspec-core vault check all --fix`, parsed
leniently but rewritten to the canonical quoted `yyyy-mm-dd` form, never hand-edited.

**Examples:**

- Plan file: `tags: ['#plan', '#editor-demo']`
- ADR file: `tags: ['#adr', '#editor-demo']`
- Exec step: `tags: ['#exec', '#editor-demo']`
- Exec summary: `tags: ['#exec', '#editor-demo']`
- Research: `tags: ['#research', '#text-layout']`
- Reference: `tags: ['#reference', '#text-layout']`
- Feature index (auto-generated): `tags: ['#index', '#editor-demo']`

### Feature Tags

Feature tags use kebab-case and group all documents related to a specific feature or
work stream:

- Format: `#{feature}` (e.g., `#live-preview-blocks`, `#grid-layout`,
  `#syntax-highlighting`)

- Must be consistent across all documents in the feature's lifecycle

- Always quoted in YAML

## Placeholder Naming Conventions

Templates use curly-brace placeholders `{...}` to indicate values that must be replaced.
Follow these conventions:

### Frontmatter Placeholders

| Placeholder      | Format                | Example                   |
| :--------------- | :-------------------- | :------------------------ |
| `{feature}`      | lowercase, kebab-case | `editor-demo`             |
| `{yyyy-mm-dd}`   | lowercase, ISO 8601   | `2026-02-06`              |
| `{yyyy-mm-dd-*}` | lowercase pattern     | `2026-02-04-feature-plan` |
| `{tier}`         | uppercase enum        | `L1`, `L2`, `L3`, `L4`    |
| `modified`       | CLI-maintained stamp  | `2026-02-06`              |

### Document Body Placeholders

Container identifiers (`{wave}`, `{phase}`, `{step}`) use the canonical uppercase
zero-padded form from the plan template hint blocks. `{feature}` uses lowercase
kebab-case. Narrative placeholders (`{topic}`, `{title}`) use concise prose.

| Placeholder | Format              | Example                   |
| :---------- | :------------------ | :------------------------ |
| `{feature}` | kebab-case          | `editor-demo`             |
| `{wave}`    | uppercase canonical | `W01`, `W02`              |
| `{phase}`   | uppercase canonical | `P01`, `P02`              |
| `{step}`    | uppercase canonical | `S01`, `S02`              |
| `{topic}`   | concise prose       | `event handling`          |
| `{title}`   | concise prose       | `display map integration` |

### Machine-Filled Placeholders

A separate placeholder class is filled by the CLI, never by the author. Machine-filled
placeholders use snake_case to distinguish them from author-replaced placeholders; do
not fill or rename them by hand - scaffold the document through the owning CLI verb
instead.

| Placeholder       | Filled by                            | Value                                           |
| :---------------- | :----------------------------------- | :---------------------------------------------- |
| `{heading}`       | `vaultspec-core vault add exec`      | The originating Step row's action text          |
| `{step_id}`       | `vaultspec-core vault add exec`      | The Step's canonical identifier (`S##`)         |
| `{plan_stem}`     | `vaultspec-core vault add exec`      | The parent plan's filename stem                 |
| `{scope_block}`   | `vaultspec-core vault add exec`      | A Scope section listing the Step's scoped files |
| `{document_list}` | `vaultspec-core vault feature index` | The feature's full document list                |

### General Rules

- **YAML frontmatter**: Always lowercase, kebab-case

- **Document titles/headings**: The shipped templates are canonical for level-one
  headings. Top-level vault documents use backticks around both the `{feature}` segment
  and the narrative `{title}`, `{topic}`, or `{phase}` segment. Examples:
  `# {feature} research: {topic}` represents the literal template heading '# `{feature}`
  research: `{topic}`', and `# {feature} plan` represents '# `{feature}` plan'.
  Narrative segments should be concise prose; canonical uppercase identifiers remain
  required for `{wave}`, `{phase}`, and `{step}` identifier segments.

- **File names**: lowercase kebab-case for narrative segments (`{feature}`, `{type}`);
  canonical uppercase identifiers for `{wave}`, `{phase}`, `{step}` segments. Patterns:

  - Top-level docs: `yyyy-mm-dd-{feature}-{type}.md` (e.g.,
    `2026-02-04-editor-demo-plan.md`)

  - Narrative infix (audit, reference, research only):
    `yyyy-mm-dd-{feature}-{topic}-{type}.md` (e.g.,
    `2026-02-04-editor-demo-engine-wire-reference.md`), scaffolded with the owning
    verb's `--topic` flag

  - Exec Steps (L1): `yyyy-mm-dd-{feature}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-S01.md`)

  - Exec Steps (L2): `yyyy-mm-dd-{feature}-{phase}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-P01-S01.md`)

  - Exec Steps (L3 / L4): `yyyy-mm-dd-{feature}-{wave}-{phase}-{step}.md` (e.g.,
    `2026-02-04-editor-demo-W01-P01-S01.md`) inside `.vault/exec/yyyy-mm-dd-{feature}/`
    folder.

  - Exec Summaries (L2): `yyyy-mm-dd-{feature}-{phase}-summary.md` (e.g.,
    `2026-02-04-editor-demo-P01-summary.md`)

  - Exec Summaries (L3 / L4): `yyyy-mm-dd-{feature}-{wave}-{phase}-summary.md` (e.g.,
    `2026-02-04-editor-demo-W01-P01-summary.md`) inside the feature folder.

- **Replace ALL placeholders**: No template should be committed with `{...}`
  placeholders remaining. Run `vaultspec-core vault check all --fix` to validate and
  format documents before committing - it reconciles frontmatter, strips leftover
  template annotations, and applies markdown hygiene fixes. The dedicated
  `vaultspec-core vault check placeholders` check surfaces any `{...}` residue left in
  body prose, which must be filled in by hand or by the owning CLI verb.
</vaultspec>
