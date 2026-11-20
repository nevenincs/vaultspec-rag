---
tags:
  - '#adr'
  - '#preprocess-input-fingerprint'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:3d11e26970b4aa54b18d3bef2f5de2b9fb7a3e5833f0fda287b6f2467c495109'
related:
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - "[[2026-10-04-preprocess-root-approval-adr]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-10-26-stale-search-hits-adr]]"
  - '[[2026-06-10-preprocess-hooks-research]]'
  - '[[2026-09-07-explicit-reindex-authority-research]]'
  - '[[2026-07-13-preprocess-sandbox-research]]'
  - '[[2026-07-21-code-document-index-boundary-adr]]'
---

# `preprocess-input-fingerprint` adr: `declared hook inputs in extractor identity and admission-time rebuild refusal` | (**status:** `proposed`)

## Problem Statement

Two defects share one cause: the index cannot see an edit to a hook script, and it reports the identity changes it can see too late.

- **Undetected script edits.** A rule's identity covers the whole rule table: pattern, command, entry point, target, `extractor_version`, options, error policy, timeout, priority, order, batch, path independence and source-size cap (`src/vaultspec_rag/indexer/_config_epoch.py:233`, `src/vaultspec_rag/indexer/_config_epoch.py:340`). The extraction cache key covers the same execution fields (`src/vaultspec_rag/indexer/_preprocess_cache.py:108`). Neither reads any file the command runs. An edited script with an unchanged rule table keeps serving old extracted output. That includes a rebuild, because a rebuild hits the same cache key; no indexer path removes the cache directory (`src/vaultspec_rag/indexer/_preprocess_cache.py:60`). `2026-10-04-preprocess-root-approval-adr` names the same gap as residual risk for consent.
- **Late refusal.** A change the identity does see, such as an `extractor_version` bump, is refused correctly as `full_reindex_required`. The refusal happens only after a job is admitted, when checkpoint open finds no compatible committed parent (`src/vaultspec_rag/indexer/_checkpoint_common.py:740`, and the `RunLedgerCompatibilityError` handler at `src/vaultspec_rag/indexer/_document_indexer.py:1414` as committed; that file is under active edit, so its line moves). The coordinating session reports that 49 of 69 failed jobs are this refusal. Health already excludes it (`src/vaultspec_rag/server/_lifespan.py:1278`), watcher retry already treats it as terminal (`src/vaultspec_rag/watcher_retry_policy.py:195`), and job status already renders a rebuild command for it (`src/vaultspec_rag/cli/_status_labels.py:739`). It still creates one failed job record per attempt, which fills job history and failure filters with expected refusals.

## Considerations

- Full-corpus work needs explicit authority. Automatic origins never escalate (`2026-09-07-explicit-reindex-authority-adr`; `src/vaultspec_rag/_job_admission.py:189`).
- `extractor_version` is required and documented as the author-managed invalidation lever (`src/vaultspec_rag/indexer/_preprocess_config.py:122`, `src/vaultspec_rag/indexer/_preprocess_config.py:552`).
- A command string does not reliably name its script. Commands run through `uv run`, interpreters, shells and wrappers. Resolving them automatically is guesswork.
- Any new field in the identity payload changes every hook root's fingerprint unless it is omitted when unused. A changed fingerprint makes every incremental refuse until an explicit rebuild.
- The policy file is read once per operation, and the approval digest comes from that read (`src/vaultspec_rag/indexer/_preprocess_config.py:328`, `src/vaultspec_rag/indexer/_preprocess_config.py:378`).
- Admission already owns what an index request becomes, for HTTP, CLI, MCP, in-process callers and the watcher (`src/vaultspec_rag/_job_admission.py:208`, `src/vaultspec_rag/watcher_execution.py:289`).
- Checkpoint open refuses when any field of the published proof's compatibility key differs (`src/vaultspec_rag/indexer/_run_ledger_publication_identity.py:30`, `src/vaultspec_rag/indexer/_run_ledger_runtime.py:279`).
- `2026-10-26-stale-search-hits-adr` already defines service-owned `rebuild_required` with an executable root- and source-scoped rebuild command.

## Considered options

- **Resolve and hash the command's script automatically.** Rejected: unreliable for wrapped commands, and it changes every hook root's identity on upgrade, forcing a rebuild of each.
- **Hash the whole repository tree for hook roots.** Rejected: every unrelated edit would refuse incrementals.
- **Keep `extractor_version` as the only lever and document it.** Rejected as complete: it leaves the stale cache across rebuilds and relies on authors remembering.
- **Opt-in declared inputs whose content joins the rule's identity and cache key, omitted when undeclared.** Chosen.
- **Escalate a detected identity change to an automatic rebuild.** Rejected: it contradicts `2026-09-07-explicit-reindex-authority-adr`, and no new evidence justifies superseding it.
- **Refuse a provably incompatible incremental at admission, before a job exists.** Chosen as the companion.

## Constraints

**Declared inputs.**

- A `command` or `entry_point` rule may declare `inputs`: a list of root-relative gitignore-style patterns naming the files whose content defines the extractor, such as its script and helper modules.
- At policy load, from the same read that yields the approval digest, the loader resolves each pattern beneath the root and hashes every matched regular file. The rule's `inputs_digest` is one blake2b digest over the sorted root-relative paths and their content digests.
- Fail closed, never drop. A pattern that matches nothing, a path escaping the root, a symlink resolving outside it, an unreadable file, or a match beyond the bounds raises the existing typed `admission_config_invalid` policy error for the root. The rule is not dropped, so routing is unchanged. This follows the `extractor_version` precedent rather than the per-rule drop in `2026-06-10-preprocess-hooks-adr` D3. Initial bounds: 256 files and 32 MiB per rule. The bounds are implementation choices.
- `inputs_digest` joins the rule's content identity in both the aggregate and per-kind payloads, and the extraction cache identity. The key is omitted when a rule declares no inputs, so an undeclared rule keeps a byte-identical fingerprint and cache key.
- Upgrading forces no rebuild. Only a root that adds `inputs` changes its identity. That edit also changes the policy bytes, so it needs renewed approval and one explicit rebuild of the affected kind. After that, a script edit refuses incrementals for that kind with `full_reindex_required` until an explicit rebuild, and the rebuild re-extracts because the cache key changed.
- The digest is computed once per operation inside the single policy resolution, so admission, extraction, epochs and publication see the same value (`2026-07-21-code-document-index-boundary-adr`).
- `extractor_version` stays required and keeps its meaning.
- Approval is unchanged. Its digest covers the policy file only. Whether approval should also bind `inputs_digest` is left open.

**Admission-time refusal.**

- `index_job_spec` refuses an incremental code or document request before any job record exists when the source's published proof is readable and a policy-derived identity differs from it. The identities are content identity and chunking (preprocessing) identity, computed by the same functions checkpoint open uses (`src/vaultspec_rag/indexer/_checkpoint_common.py:656`). The refusal is the typed `full_reindex_required` error carrying the reason, which identity differs, and the executable root- and source-scoped rebuild command.
- The preflight may refuse only where checkpoint open would refuse. An absent, unreadable or unverifiable proof, or any identity the preflight cannot compute exactly, admits the request unchanged. Checkpoint open stays the final authority.
- The first-build admission for a never-built source (`2026-10-12-destructive-rebuild-lifecycle-adr`, 2026-10-14 amendment) is decided first and is unchanged.
- Watcher admission receives the same refusal. The controller enters `refused` with reason `full_reindex_required` and the rebuild command, and creates no job. The drift auditor projects it as `rebuild_required`.
- HTTP answers 409 with one error envelope. The CLI exits non-zero and emits one JSON envelope in JSON mode. MCP returns a tool error. The refusal logic lives in the service domain; adapters render it.
- Nothing escalates. No origin, automatic or explicit, turns the refusal into a rebuild.

**Versions.** No version bump and no release. This decision changes none of `SUPPORTED_SCHEMA_VERSION`, `RAW_CHUNK_SEMANTICS_VERSION`, `PARSER_CAPABILITY_VERSION`, the policy schema version, `STORAGE_SCHEMA_VERSION`, the `.vaultragpreprocess.toml` `version`, or the package version. `inputs` is an optional additive rule key. Wire responses gain fields additively.

**Reconciliation.** This refines `2026-06-10-preprocess-hooks-adr` D1 (rule keys) and D7 (cache key). The proposed amendment text for that record is applied only when this decision is accepted.

## Implementation

We will let a hook rule declare its input files, fold their content into the rule's extraction identity only when declared, and refuse a provably incompatible incremental at admission with a ready-to-run rebuild command instead of a failed job.

Declared inputs:

- `src/vaultspec_rag/indexer/_preprocess_config.py`: parse and validate `inputs` in `_build_rule` (`:414`). Compute `inputs_digest` in `load_preprocess_rules` (`:292`) after the policy read at `:328`. Add `inputs` and `inputs_digest: str | None` to `PreprocessRule` (`:104`). Both are plain values, so the rule stays pickle-safe for spawn workers.
- `src/vaultspec_rag/indexer/_config_epoch.py`: add `inputs_digest` to the rule entries of `content_payload` (`:233`) and `kind_content_payload` (`:340`), only when it is not `None`.
- `src/vaultspec_rag/indexer/_preprocess_cache.py`: add `inputs_digest` to the `execution` mapping in `PreprocessCacheIdentity.from_rule` (`:108`), only when it is not `None`. Correct the module docstring's key description.
- `src/vaultspec_rag/cli/_preprocess.py`: `preprocess list` and `preprocess check` show declared inputs and the digest; `check` reports input errors and exits non-zero.
- `docs/preprocessing-hooks.md`: document `inputs`, the rebuild it triggers, and that undeclared rules rely on `extractor_version`.

Admission-time refusal:

- `src/vaultspec_rag/_job_admission.py`: in `index_job_spec` (`:208`), after the first-build decision at `:241`, run the compatibility preflight for incremental code and document requests and raise the typed refusal.
- `src/vaultspec_rag/indexer/_run_ledger_publication_identity.py` or `src/vaultspec_rag/_publication_state.py`: expose one read-only accessor returning the published proof's compatibility key for a root and source, reusing `compatibility_for_signature` and the existing proof read. No new ledger query shape.
- `src/vaultspec_rag/_operator_commands.py`: reuse `index_command` (`:238`) for the rebuild command.
- `src/vaultspec_rag/server/_routes.py` and `src/vaultspec_rag/server/_routes_reindex.py`: map the refusal raised from admission to the 409 envelope with `rebuild_command`.
- `src/vaultspec_rag/watcher_execution.py`: near `:289`, settle a typed admission refusal as controller `refused` with `full_reindex_required`, restore captured scope through the existing uncreated-admission path, and create no job.
- `src/vaultspec_rag/_search_drift.py`: project the admission refusal as `rebuild_required`.
- CLI and MCP adapters render the existing typed error. Confirm that nothing in `src/vaultspec_rag/cli/` or `src/vaultspec_rag/mcp/_tools.py` rewrites it.
- Tests: an undeclared rule's fingerprint and cache key stay byte-identical, pinned against a value computed before the change; a declared script edit changes identity, refuses incremental at admission with no job record, and re-extracts on explicit rebuild; a missing input raises `admission_config_invalid`; a parity test shows the preflight refuses exactly when checkpoint open would; the watcher path enters `refused` without a job. Prove each guard can fail by mutation.

Lane overlap: `src/vaultspec_rag/indexer/_preprocess_config.py`, `src/vaultspec_rag/indexer/_preprocess_cache.py` and `src/vaultspec_rag/indexer/_config_epoch.py` belong to the preprocess hook modules another lane is editing. Sequence the declared-inputs work after that lane lands, or give it to that lane. The admission work does not touch `src/vaultspec_rag/indexer/_document_indexer.py`; its `RunLedgerCompatibilityError` refusal stays the final authority.

## Rationale

Declared inputs are exact where command parsing is guesswork. Omitting the key when unused gives the deciding property: no hook root is forced to rebuild by the upgrade, and the cost lands only on roots that opt in. Putting the digest in the cache key also closes the stale-cache-after-rebuild gap. Admission-time refusal moves an existing, correct refusal to before any job exists. Operators get the same typed outcome and command without a failed record per attempt. Because it may refuse only where checkpoint open would, it adds no authority and needs no supersession of `2026-09-07-explicit-reindex-authority-adr`.

## Consequences

- Authors who declare inputs get script edits detected. Each such edit needs one explicit rebuild of the affected kind. Authors who do not declare inputs keep today's behaviour.
- A missing or oversized declared input stops indexing for the root with a typed configuration error until fixed.
- Expected refusals stop appearing as failed jobs, so job history and failure filters show real faults.
- Policy load reads the declared input files once per operation. The bounds cap that cost.
- Reconsider if authors need inputs outside the root, such as a shared tool environment, or if approval should bind the input digest.
