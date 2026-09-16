<vaultspec type="config">
## Vaultspec Rules

You MUST respect these rules at all times:

---
name: canonical-code
trigger: always_on
---

# Canonical code

## Rule

- One behaviour, one implementation. Delete the other.
- Never add a forwarding shim, a delegating wrapper, or a compatibility alias.
- Never keep a symbol alive for tests. If only tests reach it, delete it and
  repoint them at the production path.
- Never leave a re-export in the module a symbol moved out of.
- Never mirror logic that lives elsewhere. Import it.
- Search by meaning before writing anything. Prove no implementation exists.
- Collapse the duplicate when you find one. Never carry both across a seam.

## Why

- A second implementation drifts. The copy that never gets the fix is the one
  that ships the bug.
- A test-only path proves nothing about production. Parity asserted against code
  production no longer runs asserts nothing at all.
- A shim reads as an abstraction and is dead weight. It hides the real caller and
  survives every later refactor.
- Grep cannot find a function whose name you cannot guess. Semantic search can.

## How

- Search behaviour plus domain nouns before adding a helper, method or module.
- Read the candidates. Semantic search locates; it does not enumerate. A sampled
  negative is not a negative.
- Treat extraction as a dedup opportunity, not a move.
- Check callers before keeping anything. Zero production callers means delete.
- Repoint tests at the production entry point in the same change that removes
  the path they were exercising.
- Bad: a method whose body is one call into the module that now owns it.
- Bad: importing a name only to re-export it for callers that could import it
  directly.
- Bad: two functions that differ only by a constant or a label string.
- Bad: keeping the old path "until callers migrate". Migrate them now.

---
name: gates-run-explicitly
trigger: always_on
---

# Gates run explicitly

## Rule

- Run lint, format, type-check, and the tests covering what you touched before
  every commit.
- Capture each gate's exit code on its own. Never read an exit code through a
  pipe.
- Never commit code you know to be failing.
- Never pass a flag that skips a check.
- Never relax a check to make a commit succeed.
- Never install a commit hook. Never add a configuration or task that installs
  one.
- Delete the hook configuration the workspace sync regenerates. Never commit it.
- Never run `git stash`, in any form.
- Never run a destructive git operation: no `checkout` of paths, no `reset`, no
  `clean`, no `revert`, no `rebase`, no force-push.
- Commit with an explicit pathspec. Never a bare commit.
- Commit on your own branch and stop.
- Never merge your own branch into the default branch.
- Never push to the default branch.
- Hold "no push, no merge" until someone else lands the work. Never treat it as
  expiring because you believe you are finished.

## Why

- A hook that rewrites the working tree to the staged state reverts every
  unstaged change, and cannot be made safe when workers share a tree.
- A tree-wide hook fails every worker's commit whenever any file anywhere is
  red, so one unrelated defect halts all work.
- The stash stack is shared by every worktree. A stash takes other workers'
  uncommitted changes with it.
- A bare commit records whatever else is staged, so one worker's half-finished
  change lands under another's message.
- The default branch runs CI under a concurrency group, so every push cancels
  the run in flight. Enough workers landing themselves means no run ever
  finishes, and releases go out over gates that never executed.
- A cancelled run reports as cancelled, not failed, so a destroyed backstop
  raises no alarm.
- Continuous integration is the only backstop once nothing runs locally. That
  raises the bar on verifying by hand; it does not lower it.

## How

- Run the linter over the package, the type-checker over the files you changed,
  and the tests exercising the branches you touched. Commit those paths by name.
- Run the error and fallback branch tests after a de-shim or a move. A
  function-local import on a cold branch passes both linters and fails only when
  that branch runs.
- Read the merge commits before blaming a foreign session for churn on the
  default branch. A merge of a dispatched lane's branch is your own.
- Filter by workflow when reading CI results. An unfiltered list mixes in
  release automation.
- Set work aside with a commit on your own branch. Never anywhere else.
- Wait when nobody answers. Never land because the work looks finished.

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
- A store-wide lock sharing a mutex with unrelated scans collapses search
  latency by more than an order of magnitude.
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

# Vaultspec tools

Every `.vault/` mutation, listing, and repair goes through the owning verbs: MCP tools
when connected, else the `vaultspec-core` CLI. Bypassing them produces drift that
`check` flags. A record's body is read as a file.

## Tools

The MCP server exposes `status` (in-flight plans and next open Step), `find` (documents
and features), `create` (scaffold, batchable), `edit` (body prose, batchable),
`plan_progress` (check or uncheck Steps), `plan_edit` (author and restructure Step
rows), `log` (append a Step's ledger rows), `check` (validate and repair), and the
`discover`/`invoke` gateway to every other verb. `invoke` asks for host confirmation on
every call, so the above-Step plan verbs (`tier`, `wave`, `phase`, `epic intent`) and
`vaultspec-core sync` are better run through the CLI even when connected.
`vaultspec-core vault feature index`, `vaultspec-core spec mcps`, and `uninstall` are
CLI-only.

The bundled CLI reference, `.vaultspec/reference/cli.md`, catalogues every command,
flag, and exit code. Run `vaultspec-core <cmd>`, or
`uv run --no-sync vaultspec-core <cmd>` in uv environments; `--dry-run`, `--json`, and
`<cmd> --help` preview and explain. Sync-shaped commands report created, updated,
unchanged, removed, restored, skipped, or failed; only `failed` stops.

## Manual edits

Permitted: body prose of a scaffolded record, including the `proposed`, `accepted`,
`rejected`, or `deprecated` token in an ADR's heading (`superseded` is set by
`vaultspec-core vault adr supersede`). Policy sources under `.vaultspec/rules/`,
`skills/`, `agents/`, `hooks/`, and `mcps/` are the user's: propose changes, apply them
only on request, then run `vaultspec-core sync`. Forbidden: frontmatter, filenames, plan
structure, Step checkboxes, new `.vault/` files, and anything inside generated provider
directories.

---
name: vaultspec-discovery.builtin
trigger: always_on
---

# Discovery

Discover before changing: at each phase start, and before a session's first edit to
source or vault, at any horizon. The sequence is locate by meaning, read the epicenter
whole, confirm with grep.

1. **Locate by meaning.** Code:
   `vaultspec-rag search "<concept and domain nouns>" --type code` (narrow with
   `--language` or `--path`). Decisions:
   `vaultspec-rag search "<intent>" --type vault --doc-type adr`. Orientation: the
   discovery verbs `vaultspec-core status [target]`, `vaultspec-core vault list`, and
   `vaultspec-core vault graph` (MCP: `status`, `find`). A small, well-named module is
   listed directly.
1. **Read** the epicenter file, or the nearest existing analogue when extending a
   feature, in full.
1. **Confirm** exact symbols and insertion points with a targeted grep.
1. For decisions, also list `.vault/adr/` filtered by feature; search alone misses
   lower-ranked or opaquely named records. Search across features before narrowing:
   shared decisions can govern work under another tag. Read accepted decisions that
   cover the scope and follow their evidence links. This discovery does not itself
   require a persisted Research or Reference record.

Do not lead with broad glob or grep sweeps on a large tree; grep is the confirmation
step. Where `vaultspec-rag` is unavailable, the `vaultspec-core` discovery verbs and
grep carry the same sequence.

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

# Vault records

Every `.vault/` record belongs to one feature and is scaffolded by its owning verb: the
`create` tool where the MCP server is connected, otherwise
`vaultspec-core vault add <type> --feature <feature>`. The verb owns the filename and
the frontmatter; the author writes body prose only. The frontmatter schema, tag pair,
placeholders, and filename patterns are catalogued in
`.vaultspec/reference/vault-schema.md`; never hand-write them.
`vaultspec-core vault check all --fix` repairs drift and strips leftover template hints.

## Record types

- **Research** (`.vault/research/`) grounds a decision: claim-first findings, each with
  a re-fetchable locator, and a `## Sources` list. It frames options; it never records
  the decision. Requires nothing.
- **Reference** (`.vault/reference/`) grounds work in code: how this or another codebase
  implements the thing, as patterns with `file:line` locators, not copied code. Requires
  nothing.
- **ADR** (`.vault/adr/`) records one decision and only the decision, citing research
  and other evidence by stem, never restating it. Requires sufficient Research,
  Reference, or Audit evidence. Its heading starts `proposed`; approval, unchanged
  reuse, amendments, and supersession follow the vaultspec system section.
  `vaultspec-core vault adr supersede OLD --by NEW` owns supersession after the
  successor is accepted. Pending amendment text never replaces accepted content.
- **Plan** (`.vault/plan/`) sequences authorized work with decision coverage assessed
  under the vaultspec system section. When no costly decision is involved and no ADR
  governs, its Description records that assessment. Otherwise, `related:` lists every
  governing ADR (`--related`, repeatable, at scaffold; `vaultspec-core vault link add`
  later). Scaffold with `--tier L1..L4`; build and change structure only through the
  `plan_progress` and `plan_edit` tools or the `vaultspec-core vault plan` verbs.
  Conventions are in the hint blocks of `.vaultspec/templates/plan.md`.
- **Ledger** (`.vault/exec/`) is the mechanical log of a plan's execution, one per plan,
  append-only.
  `vaultspec-core vault exec log --feature <feature> --step S## --related <plan-stem> --row A:path`
  (the `log` tool when connected) creates it on first use and appends one
  `S## A|M|D|R path` row per path touched; `--verify` adds a check line, `--by` the
  persona, `--note` an exception (data loss, skipped work, a scaffold left in code, a
  persistent failure). Rows are written only by the verb. No narrative.
- **Audit** (`.vault/audit/`) holds findings from review or curation, one
  `### {topic} | {level} | {summary}` entry each, appended as a rolling log, with
  recommendations that name a decision for a follow-on ADR rather than making it.
  Requires the artifacts it reviews.
- **Feature index** (`.vault/index/`) is generated: the `create` and `edit` tools
  regenerate it; after CLI scaffolds run `vaultspec-core vault feature index`.

A feature that needs a second ADR, audit, reference, or research record disambiguates it
with the owning verb's `--topic` flag, never a hand-picked filename.

## Links and boundaries

- `related:` carries quoted Obsidian wiki-links (`- '[[stem]]'`), set by the owning
  verbs. Bodies carry no wiki-links and no markdown links; a source file is named in
  backticks, a code fact is cited as `path:line`.
- Vault records cite code; code never cites the vault. The `Vaultspec-Step` and
  `Vaultspec-Feature` commit trailers (`vaultspec-core vault plan trailer emit`) are the
  only link from git history to a record; emit them when the project's recent commits
  already carry them.
- Each fact has one home: research grounds, the ADR decides, the plan sequences, the
  ledger logs, the audit finds. A fact needed elsewhere is cited by stem, not restated.
</vaultspec>
