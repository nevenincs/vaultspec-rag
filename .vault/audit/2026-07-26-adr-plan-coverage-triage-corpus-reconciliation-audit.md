---
tags:
  - '#audit'
  - '#adr-plan-coverage-triage'
date: '2026-07-26'
modified: '2026-07-26'
related:
  - "[[2026-06-01-service-observability-adr]]"
  - "[[2026-06-01-service-operability-adr]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-06-24-vault-pipeline-search-adr]]"
  - "[[2026-06-30-mcp-optional-dependency-adr]]"
  - "[[2026-06-02-rag-index-performance-adr]]"
  - "[[2026-07-23-ci-self-hosted-gpu-runner-adr]]"
  - "[[2026-04-04-vaultragignore-adr]]"
  - "[[2026-04-12-vaultspec-rag-install-adr]]"
  - "[[2026-07-25-pool-orphan-guard-adr]]"
---

# `adr-plan-coverage-triage` audit: `ADR corpus reconciled against the codebase`

## Scope

All 121 ADRs, reconciled against the codebase and against each other. Each was
read whole, its declared status parsed from the body H1, its supersession edges
read from frontmatter, and the behaviour it decides located in the current
source and confirmed by symbol. Coverage was complete: 121 of 121.

Semantic search was unavailable throughout - the service was crashed with its
port still bound, and the vault index reported zero documents - so recall ran on
the documented fallback of the discovery verbs, grep, and whole-file reads. That
lowers confidence only for same-topic ADRs sharing no filename, feature tag, or
vocabulary; every finding below rests on a locator read directly.

The mechanical layer was already clean before this pass and stayed clean: a
uniform H1 status encoding across all 121, zero legacy `## Status` sections, and
a symmetric supersession graph where all six `superseded_by` edges are mirrored
by `supersedes:` lists. `adr-status` reports clean. Consequently nearly every
finding here is judgment-class, which is the expected shape for a corpus whose
CLI-owned hygiene is current.

Declared status: 113 `accepted`, 6 `superseded`, 2 `proposed`.

## Findings

### ci-cheap-tiers-left-the-hosted-fleet | critical | fork pull requests now execute on a self-hosted runner the decision reserved for the GPU tier

`2026-07-23-ci-self-hosted-gpu-runner-adr` rests its entire security argument on
a tier split: the cheap tiers stay on the hosted fleet so that, in its own
Consequences, "fork PRs run only the hosted tiers and never touch the
workstation or its secrets." That split no longer exists. Every job in
`.github/workflows/ci.yml` now runs on `[self-hosted, Linux, X64]` -
`workflow-lint` (`:29`), `lint-and-type` (`:44`), `tests` (`:121`),
`vault-audit` (`:229`), `dependency-audit` (`:258`) - and the workflow's
`pull_request:` trigger (`:6`) carries no branch or fork restriction. None of
those five jobs has a trusted-event `if:` gate; only `gpu-tests` does (`:173`).

Stated precisely, because the severity turns on it: the five migrated jobs run
on a **Linux** runner, while the GPU job targets `[self-hosted, windows, gpu,
cuda]`. They are therefore not demonstrably the same machine, and the ADR itself
notes the workstation "already hosts an unrelated runner". Two facts that would
settle the real exposure are not visible from the tree: what host backs the
Linux label, and whether the repository's require-approval-for-outside-
collaborators setting is enabled. The ADR named that setting as the mandatory
pairing for the gate. What is certain is that the decision's load-bearing
premise - untrusted code never reaches a self-hosted runner - is no longer what
the workflow does.

### parity-mandate-contradicts-the-search-scope-boundary | high | three accepted records disagree, and the reversal exists only in prose

`2026-06-01-service-observability-adr` and `2026-06-01-service-operability-adr`
are both `accepted` with no `superseded_by`, and both mandate bidirectional
CLI-MCP parity over the server-runtime surface.
`2026-06-30-mcp-search-scope-adr` retires exactly that framing by name in SB2
and SB4 - "parity is the wrong goal" - and codifies the opposing rule. The code
follows the later record: `src/vaultspec_rag/mcp/_admin_client.py:1-14` states
the admin verbs "are CLI-only on the public surface and are not registered on
the FastMCP instance", and the `@mcp.tool()` registry carries only search,
refresh, clean, and status tools, guarded by
`src/vaultspec_rag/tests/test_mcp_conformance_surface.py:81`.

No frontmatter edge records the reversal. `2026-06-11-service-jobs-operability-adr:65`
asserts supersession in prose only. The corpus's own
`2026-07-22-mcp-search-scope-surface-drift-audit` reached this conclusion a
month ago and it remains open. The two 2026-06-01 records are not wholly dead -
their watcher-config, logs, jobs, and metrics implementation content shipped and
remains accurate - so a blanket supersession would discard live material. Only
the parity clause is contradicted.

### orphaned-production-entry-point-survives-its-removal-decision | high | a decision that named the outcome "must not exist" left it reachable over HTTP

`2026-06-24-vault-pipeline-search-adr` D9 requires that `run_quality_probe` and
`run_benchmark` "move under the test tree or are deleted, leaving no orphaned
production entry point." The CLI half was done - no `quality` or `benchmark`
command is registered. The functions remain in production at
`src/vaultspec_rag/api.py:894` and `:991`, and they are still reachable:
`src/vaultspec_rag/server/_routes.py:2097` and `:2122` define the handlers, and
`:2282-2283` register `POST /benchmark` and `POST /quality` on the live daemon.
An HTTP-reachable entry point is precisely the condition the decision forbade,
so this is incomplete execution rather than a documented narrowing.

### supersession-chain-points-at-a-non-terminal-node | medium | the recorded successor was itself reversed, with no edge to say so

`2026-06-10-install-mcp-dependency-fix-adr:8` sets
`superseded_by: '2026-06-18-mcp-service-client-adr'`. That successor explicitly
carried the `mcp` core-dependency fact forward rather than reversing it,
superseding only the earlier record's framing.
`2026-06-30-mcp-optional-dependency-adr:29-33` then reverses the fact itself -
and carries no `supersedes:` frontmatter at all. The code confirms the last
record is the live one: `pyproject.toml:19-37` has no `mcp` among the core
dependencies and `:89-94` places it in the optional extra. The frontmatter graph
therefore routes a reader to a node that is no longer the terminus of the
decision it inherited.

### near-duplicate-performance-record | medium | one decision recorded three times on the same day, with rule text copied verbatim

`2026-06-02-rag-index-performance-adr` restates the problem, the
GIL and single-consumer-thread reasoning, and the codification rule slugs
(`gpu-consumer-single-thread`, `index-workers-stay-cpu-only`) of
`2026-06-02-index-perf-hardening-adr` and `2026-06-02-index-gpu-pipeline-adr`.
All three are `accepted`, dated the same day, and none links or supersedes
another. It is not a stub - it carries its own plan and execution records - which
makes it a fully tracked parallel record of work already decided elsewhere.

### two-shipped-decisions-still-await-ratification | medium | `proposed` is not a reliable signal of non-implementation in this corpus

`2026-04-04-vaultragignore-adr` is `proposed` yet governs nine production
modules (`src/vaultspec_rag/indexer/_ignore_specs.py`,
`_content_discovery.py`, `_codebase_indexer.py`, `_config_epoch.py`,
`_code_meta.py`, `_preprocess_config.py`, `_preprocess_glue.py`,
`_resolved_policy.py`, and `src/vaultspec_rag/watcher.py`).
`2026-04-12-vaultspec-rag-install-adr` is `proposed` yet shipped exactly as
specified - `src/vaultspec_rag/commands/_install.py:14-23` imports
`sync_provider`, `mcp_sync`, `Tool`, and the workspace-mode helpers from
`vaultspec_core`, which is the thin-core-delegator design the record chose.
These are the only two `proposed` records in the corpus and both are live.

### the-guard-shape-the-amendment-claims-was-never-built | medium | SB7 asserts a parametric rule; the guard is a widened literal list

`2026-06-30-mcp-search-scope-adr:123` states the conformance guard "is updated
to assert this rule ... rather than a frozen five-name list, so it keeps
enforcing the boundary as kinds are added rather than failing the next time the
surface legitimately grows." The guard at
`src/vaultspec_rag/tests/test_mcp_conformance_surface.py:31-44` is a twelve-name
literal `set`. The tool set was widened from five to twelve; the guard's *shape*
was not changed. The failure mode the triggering audit warned about - an
enumeration that goes red the next time a content kind is legitimately added -
is still live. The decision is delivered; its own prose describes a code shape
the code does not have.

### decisions-outlived-by-their-mechanisms | low | four accepted records describe machinery that no longer exists

Four records remain `accepted` while the specific mechanism each names is gone,
their intent carried forward by later architecture that no edge connects them
to. `2026-03-07-threading-lock-for-singleton-adr` describes a `get_comp()`
singleton under a `threading.Lock`; neither `get_comp` nor `RagComponents`
exists in production. `2026-03-07-vaultgraph-cache-adr` describes a module-level
`_graph_cache` in `api.py`; the locking-and-TTL principle now lives in
`src/vaultspec_rag/graph_cache.py:27`. `2026-03-07-path-resolve-engine-cache-adr`
describes an `_engine` dict in `api.py`, explicitly collapsed into
`ServiceRegistry` by a later record. `2026-06-04-async-service-index-adr`
specifies a `_background_tasks` task set that has no occurrences; the
non-blocking outcome it mandated is met by the job registry instead. In each
case the decision's intent survives and only its named machinery is stale.

### stdio-anchor-design-replaced-without-an-edge | low | a later record rewrote the module an earlier one created

`2026-07-16-mcp-stdio-lifetime-adr` is `accepted` with no `superseded_by`, but
`2026-07-17-stdio-watchdog-convergence-adr` replaces its ancestor-chain-primary
anchor with a client-PID-primary design in the same module. The module reflects
the later design: `resolve_stdin_client_pid` and `grace_prunable` both live in
`src/vaultspec_rag/server/_stdio_lifetime.py`. The convergence record frames
itself as binding rather than superseding, so whether this is supersession or
amendment is the author's to declare.

### a-tenth-decision-carries-no-plan | low | accepted and implemented, outside the earlier coverage triage

`2026-07-25-pool-orphan-guard-adr` is `accepted` and implemented at
`src/vaultspec_rag/indexer/_pool_guard.py` (`die_with_parent`, `spawn_pool`,
matching the record's chosen mechanism) but has no plan document. It postdates
the nine no-plan ADRs covered by
`[[2026-07-25-adr-plan-coverage-triage-audit]]` and so was never triaged. On that
audit's own precedent it is a delivered decision needing no plan, but the
judgment has not been recorded anywhere.

### plan-rollups-understated-completed-work | low | four steps were closed on verified deliverables; two were not

Three plans reported work as open that the tree shows complete, the same
false-negative class the taxonomy reconciliation surfaced. Closed on evidence:
`index-lifecycle-consolidation` `S01`-`S03`
(`src/vaultspec_rag/indexer/_index_lifecycle.py` exists and
`run_index_lifecycle` is routed from `_codebase_indexer.py:64`,
`_vault_indexer.py:26`, and `_document_indexer.py:30`), and
`mcp-project-root-contract` `S02`
(`src/vaultspec_rag/mcp/_resources.py:15,45`).

Two were deliberately left open because their scope clauses name files that do
not carry the work. `index-lifecycle-consolidation` `S04` scopes
`test_index_lifecycle_parity.py`, which does not exist; equivalent parity
assertions live in `src/vaultspec_rag/tests/test_index_lifecycle.py:290-337`,
and the step additionally requires a mutation proof no execution record
witnesses. `mcp-project-root-contract` `S03` scopes
`test_mcp_conformance_surface.py`, which contains no root assertion at all;
the equivalents live in
`src/vaultspec_rag/tests/test_mcp_project_root_contract.py:119,143`, and the
step's recording-daemon mechanism is unconfirmed. Closing either would assert
more than the tree proves.

## Recommendations

Applied during this pass, all content-preserving:

- Added the `related:` edge from `[[2026-04-12-vaultspec-rag-install-adr]]` to
  `[[2026-04-06-ecosystem-integration-adr]]`, which its body already cited.
- Closed four plan steps on verified deliverables, and deliberately left two
  open, per `plan-rollups-understated-completed-work`.
- Deleted a decision pointer from `pyproject.toml` that named a vault feature
  and the decision superseded, which the project's own no-dev-metadata rule
  forbids and its citation gate codifies but does not scan for in that file. The
  surrounding prose already stated the constraint, so the pointer was removed
  without replacement.

Requiring author judgment, none applied:

- **Settle what backs the self-hosted Linux label and whether outside-collaborator
  approval is enabled**, per `ci-cheap-tiers-left-the-hosted-fleet`. Then either
  return the cheap tiers to the hosted fleet as decided, or amend the record to
  state the new split and the compensating control. This is the one finding
  whose resolution should not wait on a curation cycle.
- **Resolve the parity mandate against the search-scope boundary.** A blanket
  supersession of the two 2026-06-01 records would discard implementation
  content that still ships; a targeted amendment retiring only the parity clause
  is the smaller instrument. Either way the reversal needs a frontmatter edge,
  not prose.
- **Finish or narrow D9**, per `orphaned-production-entry-point-survives-its-removal-decision`:
  delete the two routes and move the functions under the test tree, or record an
  amendment stating that an HTTP-only diagnostic surface is intended.
- **Point the supersession chain at its terminus** by giving
  `[[2026-06-30-mcp-optional-dependency-adr]]` a `supersedes:` entry.
- **Consolidate the duplicate performance record** into whichever of its two
  same-day siblings governs, and supersede it.
- **Ratify or reject the two `proposed` records.** Both govern shipping code, so
  leaving them unratified makes the status field misleading corpus-wide.
- **Reconcile SB7's wording with its guard**: either make the guard parametric
  as the amendment claims, or correct the amendment to describe the widened
  literal list that shipped. The ADR should not assert a code shape the code
  lacks.
- **Decide supersession or amendment for the four outlived mechanisms** and for
  the stdio anchor record. Marking them `deprecated` is available where no single
  successor names the exact mechanism replaced.
- **Record a verdict for `[[2026-07-25-pool-orphan-guard-adr]]`**, delivered but
  never triaged.

No archiving is recommended, and none was performed. Every retirement candidate
examined either still governs shipping behaviour or is already retired in place.
