---
tags:
  - '#adr'
  - '#preprocess-root-approval'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:d9cab542157a99d1fd1f852bd393341d197273d1796d1ac28f73cc8e8b7e26c8'
related:
  - "[[2026-07-13-preprocess-sandbox-research]]"
  - "[[2026-07-14-preprocess-sandbox-removal-adr]]"
  - "[[2026-07-13-index-drift-hardening-adr]]"
  - "[[2026-06-10-preprocess-hooks-adr]]"
  - '[[2026-07-13-preprocess-sandbox-adr]]'
---

# `preprocess-root-approval` adr: `Per-root, digest-bound approval gates repository-authored hook execution` | (**status:** `accepted`)

## Problem Statement

A root's `.vaultragpreprocess.toml` selects commands that indexing launches with the operator's privileges. Since `2026-07-14-preprocess-sandbox-removal-adr` every root's rules execute by default, so repository data and repository-authored executable policy share one trust level: a contributor who can change the file gets code execution on any host that indexes or watches the root. A reported high-severity finding (untrusted executable configuration) requires that execution be opt-in per canonical root and bound to the exact policy.

## Considerations

- The removal ADR reopened audit C1 as an accepted risk and named a per-root trust designation as a pathway left open. This record takes that pathway.
- `2026-07-13-index-drift-hardening-adr` D5-D8 shipped trust-on-first-use once. `2026-07-13-preprocess-sandbox-research` finding A records why it was withdrawn: enforcement in the rule loader returned zero rules for an untrusted root, so routing, the watcher change filter and the HTTP response all went silent for non-interactive clients.
- Rules now resolve for every root and execution is gated separately at one predicate, the seam the `off` kill switch uses (`src/vaultspec_rag/indexer/_preprocess_config.py:687`, `src/vaultspec_rag/indexer/_resolved_policy.py:554`). A gate placed there keeps routing and ownership intact and inherits whatever that seam already does with earlier extracted output.
- The `/reindex` pre-flight block and the `server start` notice already tell a non-interactive client whether hooks will run (`src/vaultspec_rag/server/_routes_reindex.py:53`).
- The sandbox research finding B ranks trust-store forgery by a running hook as critical. A gate that refuses execution before approval removes that path for unapproved code; an approved hook already holds the operator's privileges.

## Considered options

- Keep default-on execution and treat the finding as the accepted risk of the removal ADR: rejected, because the request is to close it.
- Restore trust-on-first-use as first built (resolved-rule-set hash, loader enforcement, interactive confirmation, a trust-all switch): rejected. Loader enforcement is the cause of the silent no-op, and a trust-all switch restores the finding wherever it is set.
- Approval of the exact policy bytes per canonical root, enforced at the execution predicate and reported on every surface: chosen.
- Restore OS containment alongside approval: not decided here. The removal ADR's measured per-file cost and its withdrawal of the sandbox stand until a contained design is evidenced.

## Constraints

Authorization: the user's 2026-10-04 request to fix the reported finding authorizes making repository-authored execution opt-in per canonical root, binding approval to the exact policy digest, and requiring renewed approval on change. This reverses the removal ADR's commitment that a root's hooks run by default with no consent gate. That record's removal of OS containment, its direct bounded subprocess launch, curated child environment, project-root working directory, output cache and kill switch remain in force.

- A root's rules execute only while an approval record matches both the canonical root and the SHA-256 of the policy file's bytes. Any byte change, or the same policy at a different path, is unapproved.
- Fail closed: an absent, unreadable, malformed or unrecognised approval store approves nothing.
- Approval is granted only by a local operator command. No HTTP route, MCP tool, environment variable or repository file grants it, and there is no machine-wide trust-all setting.
- Approval records live in the managed status directory, never in the repository, and are written owner-only.
- One predicate answers whether hooks run, for indexing, the watcher, the service and `preprocess run-one` alike. The digest and the rules a run executes come from the same read of the policy file.
- An unapproved root keeps its routing and ownership, launches no extractor, and reports the unapproved state with the approval command on every surface that reports hook state. Clients are never prompted. What happens to output extracted before the root became unapproved is the existing behaviour of a disabled transform, not a commitment of this record.
- The `off` kill switch wins over approval.
- Approval is consent, not containment. An approved hook runs with the operator's privileges, and the digest covers the policy file, not the programs its commands launch.

## Implementation

We will gate hook execution on a per-root approval record. `load_preprocess_rules` attaches the digest of the bytes it parsed; `resolve_index_policy` resolves approval once into the operation's policy snapshot; `hook_state` takes approval as an input and yields a distinct `unapproved` state that every consumer of the predicate inherits. For the execution fingerprint an unapproved root is identical to a switched-off one, so granting or losing approval reconverges the index exactly as toggling the kill switch does and no other root's identity changes.

`preprocess approve` prints the rules and records the root and digest; `preprocess revoke` removes the record; `preprocess status`, `status`, `server start`, the `/reindex` pre-flight block, the document dry run and index results report the state. A write to the store refuses to proceed when the existing store could not be read, so a transient read failure cannot discard other roots' approvals. The store is one JSON sidecar keyed by canonical root key. The verb names, sidecar filename and report field names are implementation details that may change within these constraints.

## Rationale

Gating at the execution predicate rather than the loader is what separates this from the withdrawn design: rules still resolve, so discovery, reconciliation and the watcher filter are unaffected, and the remaining cost of a gate for non-interactive clients is visibility, which the pre-flight block already carries. Hashing the file bytes is exact and cannot omit a field that later becomes execution-relevant, at the price of re-approval after a comment edit. A scriptable operator command gives unattended deployments a consent path that the repository cannot reach.

## Consequences

- Breaking: on upgrade, every root with rules stops running hooks until approved, and each run lists the affected paths. Approval changes the execution identity, so the next index run reconverges; the extraction cache amortises it.
- Earlier extracted output is not uniformly kept while a root is unapproved. The document indexer retains it on full and incremental runs (`src/vaultspec_rag/indexer/_document_indexer.py:882`, `src/vaultspec_rag/indexer/_document_indexer.py:1021`, `src/vaultspec_rag/indexer/_document_indexer.py:1108`). The code indexer retains it only on scoped incremental runs; a full run omits the held-back path from the generation it builds and an unscoped incremental run counts it as deleted (`src/vaultspec_rag/indexer/_codebase_preprocess.py:96`, `src/vaultspec_rag/indexer/_codebase_indexer.py:987`). That is how the kill switch already behaves; it now applies to every unapproved root, so a root with code-targeted rules loses that output from search until it is approved and indexed again. Approving before the first index run after upgrade avoids it.
- A revocation does not reach a job already admitted with an approved snapshot; that job runs the rules that were approved when it was admitted.
- Unattended deployments must run the approval command when provisioning a root and again whenever its policy changes. Each worktree or clone is its own root.
- Residual risk, named: an approved hook is uncontained code execution as the operator; an operator can approve without reading; a later change to a script an approved command launches is not detected; any process running as the operator can write the store; and the root key folds case on Windows, so on a volume with per-directory case sensitivity two directories differing only in case share one approval.
- The containment half of the finding (an approved hook cannot read unrelated files or reach the network) is not met. A follow-on decision should weigh contained execution for approved hooks, such as a persistent sandboxed hook host, against measured per-file cost. A second follow-on should decide whether the code indexer retains held-back output the way the document indexer does.
