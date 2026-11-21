---
tags:
  - '#audit'
  - '#destructive-rebuild-lifecycle'
date: '2026-11-21'
modified: '2026-11-21'
body_schema: 'body-v2'
body_hash: 'sha256:6ebbf94a381677a9b47eef1e6f395f8b3674721adb3586be40f7d4bb68b88ec4'
related:
  - "[[2026-10-12-destructive-rebuild-lifecycle-plan]]"
---

# `destructive-rebuild-lifecycle` audit: `final integrated review of the reset-first rebuild`

## Scope

Final integrated review of plan `2026-10-12-destructive-rebuild-lifecycle-plan`, Steps S01 to S06, against its Verification section and the binding commitments of `2026-10-12-destructive-rebuild-lifecycle-adr` (including the 2026-10-14 first-build amendment) and the related ADRs. Diff base `21ca01702^`, target `9cac1d16b` (S06; `c489b57c4` is its pre-rewrite twin and differs only in two doc lines). Step commits: `21ca01702`, `aed9ef3aa`, `6216cf517` with `e8d06dd96`, `773cc887f`, `35292862f`, `9cac1d16b`; related `55dfadab3`, `020f3ba3a`, `867984a80`, `2aeffef0c`, `99689f01f`. Commit `d693c6f65` landed on the branch during the review, and another worker had uncommitted edits in this worktree to `_rebuild_lifecycle.py`, `_public_search.py`, the search availability modules and `service.py`. Both are outside this review; locators below are at `9cac1d16b`. Workflows traced: explicit rebuild from HTTP, CLI and MCP through admission, reset, ingestion and certification; immediate, bounded and combined search during a rebuild; pause, cancel, resume, restart and a new rebuild; watcher and incremental fencing; maintenance isolation; and stale other-backend pointer handling under the user decision of 2026-11-21. Discovery used targeted grep and reads, not semantic search.

## Findings

### reset-lock-wait-unbounded | high | The reset waits for a collection lock with no time limit while holding the store lifecycle lock, and the health check then stalls every root

`src/vaultspec_rag/store_collections.py:261`. `_drop_collection` takes `_lifecycle_lock` and then waits on `_point_lock(collection)` with no timeout. It runs inside `run_control.protected()` (`src/vaultspec_rag/indexer/_rebuild_lifecycle.py:281`), so cancel, pause and the no-progress deadline cannot interrupt it. This is the known deadlock in `test_blocked_document_write_polls_cancel_and_releases_writer`, and `test_blocked_document_write_expires_at_no_progress_deadline` has the same shape. The same pattern appears in two more places. First, `recreate_empty_source` waits on the collection lock with no timeout in the same protected span (`store_collections.py:390`). Second, `ServiceRegistry.health` holds the registry-wide `_lock` while it calls `conformance_verdicts()`, which takes each store's `_lifecycle_lock` (`src/vaultspec_rag/service.py:1307-1317`, `store_collections.py:668`). Failure scenario: a local-mode rebuild resets while a long reader holds the vault collection lock, for example a full id scan, a donor batch or a slow search. The reset parks holding the lifecycle lock. The next `/health` poll then parks holding the registry lock, and every `lease`, search lease and admission for every root blocks behind it. Other sources' ensure-on-first-read and `close()` also block. Nothing inverts the order (no collection-lock holder takes the lifecycle lock), so this is a stall bounded only by the collection-lock holder, not a cycle. Today every full rebuild goes through this path, and it breaks the ADR commitments that other sources keep serving and that no-progress deadlines stay enforced. Fix: acquire the collection lock with a timeout loop driven by the run policy, as `_point_write_lock` does. Do not hold the lifecycle lock while waiting: release it, call `policy.wait`, and retry within the deadline. Make `health()` copy the slot list under the registry lock and read the verdicts after releasing it.

### abandoned-reset-reported-retryable | medium | A reset that failed or was abandoned before completion is reported to search as brief and retryable for as long as it stays unfinished

`src/vaultspec_rag/_publication_state.py:274`, `src/vaultspec_rag/server/_search_availability.py:163`, `src/vaultspec_rag/_search_state.py:168`. Any source whose recorded reset phase is `intent` or `discarded` refuses reads with `index_transition`, `retryable=True` and the text "The reset is brief; retry the search." If discard or recreate raises (a surviving local directory, a backend that is down, a pointer refusal after intent) or the job is cancelled, the phase stays unfinished until a new rebuild runs. Every search then repeats a retry instruction that can never succeed. This contradicts the ADR requirement that retryability and remediation reflect the actual job state. Fix: when the fence is not serving, check whether a live job owns that reset generation. If none does, project a non-retryable rebuild-required fact that names the failed reset.

### reset-outside-interruption-classification | medium | All three producers run the reset outside interruption classification, and documents also run it outside the event owner

`src/vaultspec_rag/indexer/_document_indexer.py:1187`, `_codebase_indexer.py:651`, `_vault_indexer.py:308`. `reset_for_rebuild` runs before `preserve_incomplete_generation()`. A reset failure, or the cancel that `RunPolicy.protected` delivers on exit, leaves the generation `RUNNING` with no owner and no `REBUILD_INCOMPLETE` or `CANCELLED` classification. For documents, checkpoint open and reset also run before `run_index_lifecycle`, so a document reset refusal emits no `started` or `failed` lifecycle event. Code and vault run both inside the event owner, so the three domains report the same failure differently. Fix: move the document open and reset inside the lifecycle callable, as code and vault do. Wrap the reset in `preserve_incomplete_generation()` in all three producers.

### server-mode-fence-check-then-write | medium | In server mode, the epoch check and the upsert are not atomic, so a writer outside the writer lease could still land in the replacement

`src/vaultspec_rag/_store_writes.py:203`. `admit_write()` checks the epoch before each attempt. In server mode `_point_lock` is a null context, so a reset can bump the epoch, drop the collection, recreate it and record completion between that check and the upsert. Within one service the per-indexer writer lock and the exclusive maintenance lease prevent this. It was not demonstrated for a second process writing the same server collection, such as an in-process CLI run next to the service. Fix: confirm and document that cross-process writer exclusion exists in server mode, or check the epoch again after each acknowledged write and fail the run so finalization never certifies a mixed collection.

### search-hot-path-ledger-opens | medium | Each search opens the run ledger several times with schema verification, and that cost has not been measured

`src/vaultspec_rag/indexer/_rebuild_lifecycle.py:256`, `src/vaultspec_rag/server/_search_readiness.py:234`. Capturing the fence constructs a `RunLedger`, which runs the read-only preflight and schema verification. Validating opens a second connection. `ReadinessRevisionRegistry.snapshot` captures the epoch again. A combined search makes about nine SQLite opens across three sources against a ledger that a rebuild is writing to at the same time. Ledger contention also becomes an `index_transition` refusal. The plan requires search latency distributions against a baseline. The three-domain module prints p50 and p95 but asserts nothing, and it has not run. Fix: read the reset state through the lightweight `read_source_reset` path on capture as well, and measure before closing the plan.

### acceptance-matrix-gaps | medium | Required items in the plan's verification matrix have no test

No test was found that a repeated request id resets at most once, that a queued or refused job deletes nothing, that a model or schema mismatch or a source change during a pause never mixes epochs, or that a crash after applied writes, a unit checkpoint or the final proof commit recovers correctly. Service restart mid-rebuild relies on `test_service_job_control_pause_restart`, which was only collected. The search latency, throughput and peak-storage records the plan requires do not exist. Fix: add these to the real-storage and service lanes before the final review gate.

### commit-scope-mixing | medium | The stale-pointer fixes landed inside an unrelated torch commit

`d693c6f65`, titled as a torch CUDA-index refactor, also changes `_store_models.py`, `store_collections.py`, `storage_archive.py`, `_donor_candidates.py`, `_routes_reindex.py`, `cli/_index.py` and `_job_errors.py`. Those changes add the typed `ServedPointerUnverifiableError` and `established_served_code_collection`, and the CLI clean envelope. This matches a commit that recorded another worker's staged changes. Those fixes then have no plan Step, no ledger rows and no review. Fix: record those changes against S06 or a new Step, and review them, including the CLI clean JSON envelope, under the 2026-11-21 pointer decision.

### production-assert | low | An `assert` guards a production refusal path

`src/vaultspec_rag/server/_search_route_availability.py:492`. Under `python -O` the assert disappears and the next line dereferences `None`. Fix: raise a typed error or narrow by construction.

### carried-test-doubles | low | Monkeypatch doubles that predate this work were extended rather than removed

`src/vaultspec_rag/tests/test_donor_admission.py` replaces `read_served_pointer`, the storage manifest and the proof reader with stand-ins. `test_code_rebuild_stale_evidence.py` replaces `delete_publication_points` with a failing stand-in. Both were adapted in this plan rather than replaced with real components. Fix: drive these through real pointer files and real store failures in a follow-on.

### combined-empty-unfenced | low | A combined search where every count is zero skips epoch validation

`src/vaultspec_rag/_public_search.py` `_empty_or_failed_combined_outcome` returns success without validating the per-domain fences that were captured. It cannot leak old content, but a reset crossing the request goes unreported. Fix: run `_validated_epoch` on the empty outcomes as well.

### s06-open | low | S06 is still unchecked in the plan

The S06 commit and its ledger rows exist, but the Step checkbox is open. It should close through `plan_progress` once this review's high finding is resolved and the pending verification passes.

## Recommendations

- `reset-lock-wait-unbounded` reopens S01 and S06. Resolve it together with the GPU-lane deadlock fix on the other branch, and confirm both blocked-write tests pass in both directions.
- A second explicit rebuild requested while a rebuild is paused is deduplicated by `active_work_identity` (mode and authority match) into the paused job instead of starting a fresh reset. A follow-on decision should state whether "a new rebuild request starts a fresh generation" applies while equivalent work is paused.
- Verification still pending: the GPU-lane modules `test_rebuild_three_domain_contract`, `test_rebuild_partial_search`, `test_rebuild_replacement_corpus`, `test_index_job_control_*`, `test_first_build_lifecycle` and `test_service_job_control_pause_restart` were only collected. The CPU unit lane passed (8253 passed; parallel-load failures rerun serially, five `test_service_runtime` failures attributed to another worker's torch edits). This review ran no additional checks; no infrastructure was available for the GPU lane.
