---
tags:
  - '#audit'
  - '#destructive-rebuild-lifecycle'
date: '2026-11-21'
modified: '2026-11-21'
body_schema: 'body-v2'
body_hash: 'sha256:fdb9f23b1a240a08a0a2dc820c070c05b506aad7e4dd54de85ea1d96e83b1b66'
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

Resolution (`edcb39fba`): a read that finds a reset unfinished raises `UnfinishedResetError` with the reset's fence (`src/vaultspec_rag/_publication_state.py`), and `storage_refusal_fact` (`src/vaultspec_rag/server/_search_availability.py`) classifies it from the job snapshot. A live owner of that generation, or an active rebuild of the same root and source, keeps the retryable `index_transition`. A paused owner is not retryable and names `vaultspec-rag server job resume <id>`. No live owner is `rebuild_required`, not retryable, HTTP 409, naming the generation and the rebuild command. Tests: `test_an_unfinished_reset_is_classified_by_the_job_that_owns_it`, `test_the_service_answers_an_abandoned_reset_with_409_and_a_live_one_with_503`, and the HTTP, CLI and MCP cases in `test_service_search_reset_transition.py`.

### reset-outside-interruption-classification | medium | All three producers run the reset outside interruption classification, and documents also run it outside the event owner

`src/vaultspec_rag/indexer/_document_indexer.py:1187`, `_codebase_indexer.py:651`, `_vault_indexer.py:308`. `reset_for_rebuild` runs before `preserve_incomplete_generation()`. A reset failure, or the cancel that `RunPolicy.protected` delivers on exit, leaves the generation `RUNNING` with no owner and no `REBUILD_INCOMPLETE` or `CANCELLED` classification. For documents, checkpoint open and reset also run before `run_index_lifecycle`, so a document reset refusal emits no `started` or `failed` lifecycle event. Code and vault run both inside the event owner, so the three domains report the same failure differently. Fix: move the document open and reset inside the lifecycle callable, as code and vault do. Wrap the reset in `preserve_incomplete_generation()` in all three producers.

Resolution: `reset_for_rebuild` (`src/vaultspec_rag/indexer/_checkpoint_common.py:262`) now runs the reset and the fence rebinding inside `preserve_incomplete_generation()`, so every domain classifies a failed or interrupted reset as `rebuild_incomplete` before it propagates. `DocumentIndexer.full_index` (`src/vaultspec_rag/indexer/_document_indexer.py:1181`) opens its checkpoint and resets inside the `run_index_lifecycle` body, as code and vault do, so a document reset failure emits `started` and `failed`. `test_a_failed_reset_classifies_its_rebuild_and_reports_the_failure` in `test_rebuild_replacement.py` holds each source's collection lock on a real local store until the reset expires at its no-progress deadline. It failed on the terminal-state assertion for all three domains with the wrapper removed, and on the event assertion for documents only with the old document ordering restored; both passed once restored.

### server-mode-fence-check-then-write | medium | In server mode, the epoch check and the upsert are not atomic, so a writer outside the writer lease could still land in the replacement

`src/vaultspec_rag/_store_writes.py:203`. `admit_write()` checks the epoch before each attempt. In server mode `_point_lock` is a null context, so a reset can bump the epoch, drop the collection, recreate it and record completion between that check and the upsert. Within one service the per-indexer writer lock and the exclusive maintenance lease prevent this. It was not demonstrated for a second process writing the same server collection, such as an in-process CLI run next to the service. Fix: confirm and document that cross-process writer exclusion exists in server mode, or check the epoch again after each acknowledged write and fail the run so finalization never certifies a mixed collection.

Resolution, partial (`dc2af2f35`): `test_server_mode_write_fence.py` proves the window exists against a real Qdrant server. Two stores on one root take no client lock; the writer's fence passes, the other store resets to completion, and the admitted upsert lands in the replacement while `run_store_operation_with_retry` reports success. No cross-process writer exclusion exists in server mode. The post-write fence re-check in `src/vaultspec_rag/_store_writes.py` is not applied here, because the lock-deadlock branch owns that file; with it the test flips to expect `SourceResetEpochError`. The re-check detects the crossing and fails the stale run; it does not stop the stale point landing. Preventing that needs a cross-process writer lease in server mode, which is a decision for the orchestrator.

Resolution, detection applied: `run_store_operation_with_retry` (`src/vaultspec_rag/_store_writes.py:265`) re-checks the fence after every acknowledged attempt. A run that crosses a reset now fails with `SourceResetEpochError` and certification refuses it, since the run never reaches finalization. `test_a_write_crossing_another_clients_reset_fails_its_run` asserts the refusal. The leaked point stays in the replacement until the next rebuild discards it. Preventing the leak is pending the user's choice between epoch-stamped points and a cross-process writer lease.

### search-hot-path-ledger-opens | medium | Each search opens the run ledger several times with schema verification, and that cost has not been measured

`src/vaultspec_rag/indexer/_rebuild_lifecycle.py:256`, `src/vaultspec_rag/server/_search_readiness.py:234`. Capturing the fence constructs a `RunLedger`, which runs the read-only preflight and schema verification. Validating opens a second connection. `ReadinessRevisionRegistry.snapshot` captures the epoch again. A combined search makes about nine SQLite opens across three sources against a ledger that a rebuild is writing to at the same time. Ledger contention also becomes an `index_transition` refusal. The plan requires search latency distributions against a baseline. The three-domain module prints p50 and p95 but asserts nothing, and it has not run. Fix: read the reset state through the lightweight `read_source_reset` path on capture as well, and measure before closing the plan.

### acceptance-matrix-gaps | medium | Required items in the plan's verification matrix have no test

No test was found that a repeated request id resets at most once, that a queued or refused job deletes nothing, that a model or schema mismatch or a source change during a pause never mixes epochs, or that a crash after applied writes, a unit checkpoint or the final proof commit recovers correctly. Service restart mid-rebuild relies on `test_service_job_control_pause_restart`, which was only collected. The search latency, throughput and peak-storage records the plan requires do not exist. Fix: add these to the real-storage and service lanes before the final review gate.

Resolution, partial (`d58bfc785`): real job manager and real local storage now cover a repeated request id (one reset), queued and capacity-refused requests (no deletion, no reset recorded), and a model change across a pause and restart (a fresh generation that resets again). `test_rebuild_crash_recovery.py` covers a crash after applied writes and after the proof commit. Source change during a pause, a crash at a unit checkpoint, and the latency, throughput and peak-storage records remain open.

### commit-scope-mixing | medium | The stale-pointer fixes landed inside an unrelated torch commit

`d693c6f65`, titled as a torch CUDA-index refactor, also changes `_store_models.py`, `store_collections.py`, `storage_archive.py`, `_donor_candidates.py`, `_routes_reindex.py`, `cli/_index.py` and `_job_errors.py`. Those changes add the typed `ServedPointerUnverifiableError` and `established_served_code_collection`, and the CLI clean envelope. This matches a commit that recorded another worker's staged changes. Those fixes then have no plan Step, no ledger rows and no review. Fix: record those changes against S06 or a new Step, and review them, including the CLI clean JSON envelope, under the 2026-11-21 pointer decision.

Resolution, partial (`0ad16d72a`): review of the clean surfaces found that the MCP clean tools collapsed a clean failed in every domain into one `clean_failed` exception string, dropping each domain's typed kind, such as `served_pointer_unverifiable`, and its remediation. The tools now return the service envelope unchanged, proven through real MCP processes against a real server. Recording the `d693c6f65` changes against a Step remains open.

### production-assert | low | An `assert` guards a production refusal path

`src/vaultspec_rag/server/_search_route_availability.py:492`. Under `python -O` the assert disappears and the next line dereferences `None`. Fix: raise a typed error or narrow by construction.

Resolution (`edcb39fba`): `storage_refusal_fact` is total over `StorageGeometryError | IndexTransitionError` and always returns a fact, so `typed_storage_refusal` needs no assert.

### carried-test-doubles | low | Monkeypatch doubles that predate this work were extended rather than removed

`src/vaultspec_rag/tests/test_donor_admission.py` replaces `read_served_pointer`, the storage manifest and the proof reader with stand-ins. `test_code_rebuild_stale_evidence.py` replaces `delete_publication_points` with a failing stand-in. Both were adapted in this plan rather than replaced with real components. Fix: drive these through real pointer files and real store failures in a follow-on.

Open: not rewritten. `test_code_rebuild_stale_evidence.py` also substitutes through `monkeypatch.context()` as `patch.setattr`, which the substitution guard's needle does not count.

### combined-empty-unfenced | low | A combined search where every count is zero skips epoch validation

`src/vaultspec_rag/_public_search.py` `_empty_or_failed_combined_outcome` returns success without validating the per-domain fences that were captured. It cannot leak old content, but a reset crossing the request goes unreported. Fix: run `_validated_epoch` on the empty outcomes as well.

Resolution: already in place since `6216cf517`. `search_combined_timed` returns the empty outcome through `_fenced_combined_outcome`, and `test_a_reset_crossing_a_combined_search_fences_that_domain` covers that composition. No test reaches the call site itself; removing the wrap left the suite green, because no real component can place a reset between capture and validation of a zero-count search.

### s06-open | low | S06 is still unchecked in the plan

The S06 commit and its ledger rows exist, but the Step checkbox is open. It should close through `plan_progress` once this review's high finding is resolved and the pending verification passes.

## Recommendations

- `reset-lock-wait-unbounded` reopens S01 and S06. Resolve it together with the GPU-lane deadlock fix on the other branch, and confirm both blocked-write tests pass in both directions.
- A second explicit rebuild requested while a rebuild is paused is deduplicated by `active_work_identity` (mode and authority match) into the paused job instead of starting a fresh reset. A follow-on decision should state whether "a new rebuild request starts a fresh generation" applies while equivalent work is paused.
- Verification still pending: the GPU-lane modules `test_rebuild_three_domain_contract`, `test_rebuild_partial_search`, `test_rebuild_replacement_corpus`, `test_index_job_control_*`, `test_first_build_lifecycle` and `test_service_job_control_pause_restart` were only collected. The CPU unit lane passed (8253 passed; parallel-load failures rerun serially, five `test_service_runtime` failures attributed to another worker's torch edits). This review ran no additional checks; no infrastructure was available for the GPU lane.

## Re-review of the merged branch at 20fbf2924

Scope: behaviour changed in `2bc747e8f..20fbf2924`, covering the GPU-fix merges, the post-write epoch re-check, reset ordering, and the strict type fixes. No critical or high findings. On this sha the GPU main selection failed seven tests in `test_rebuild_three_domain_contract.py`, which match the first two findings below.

### reset-intent-before-control-edge | medium | A cancel or deadline at lock acquisition leaves the reset intent recorded with the proof deleted

`src/vaultspec_rag/indexer/_rebuild_lifecycle.py:354-376`: `begin_source_reset` advances the epoch, records the intent, and deletes the proof and receipts (`src/vaultspec_rag/indexer/_run_ledger_source_resets.py:113-119`) before entering `RunPolicy.protected()`. That protected entry is where a pending cancel or latched deadline is delivered (`src/vaultspec_rag/_run_policy.py:153`). A cancel in that window leaves storage untouched, yet search answers `rebuild_required` until the next rebuild. Fix: enter the protected span before recording the intent.

Resolution: `_reset_one` in `src/vaultspec_rag/indexer/_rebuild_lifecycle.py` now enters the run's protected span together with the held locks, so a cancel or latched deadline pending at lock acquisition is delivered before `begin_source_reset` records anything. `test_a_control_edge_reached_while_taking_locks_leaves_storage_and_ledger_alone` in `src/vaultspec_rag/tests/test_rebuild_lifecycle.py` covers cancel and deadline on a real local store. With the intent recorded first again it failed on its no-intent assertion for both edges; restored, it passes.

### reset-lock-probe-starvation | medium | Under steady local-mode search load, a reset can wait out its whole budget and fail

`src/vaultspec_rag/_store_writes.py:153-167` only probes each collection lock with a zero timeout. Local searches take the same non-fair reentrant lock (`src/vaultspec_rag/_store_search.py:218`, `:352`), so continuous searches can make every probe miss, and the reset fails with `NO_PROGRESS_TIMEOUT`. Fix: wait a bounded slice on the busy lock while holding nothing, then retry the ordered acquisition immediately.

Resolution: `hold_within_budget` in `src/vaultspec_rag/_store_writes.py` now releases everything it holds when a later lock is busy, waits one bounded slice on that busy lock holding nothing, and retries the ordered acquisition at once. Pause, cancel and the no-progress budget are still delivered before every attempt, and server mode still takes no collection locks. `src/vaultspec_rag/tests/test_reset_lock_acquisition.py` covers it on a real local store: a reset finishes inside its budget beside sixteen threads searching back to back, and a parked reset leaves the other lock free to a third thread. With the old pause-and-reprobe the first failed with the run's no-progress timeout; with the wait moved inside the held locks the second failed on its free-sample count; restored, both pass.

### reset-lock-set-snapshot | low | The set of collections to lock is listed before any lock is held

`src/vaultspec_rag/store_collections.py:361-369` lists the owned collections before taking locks, and `:390-392` acts on that list. Not reachable today, because only the canonical name is recreated. Fix: list again under the lifecycle lock and refuse on a mismatch.

Resolution: `held_for_reset` in `src/vaultspec_rag/store_collections.py` now lists the owned collections a second time once every lock is held and refuses with a `RuntimeError`, before any intent is recorded, when the set differs from the one it locked. The codebase has no dedicated error for a changed collection set, so it uses the `RuntimeError` that `discard_source_storage` raises for the same class of refusal. `test_a_reset_refuses_when_its_collections_change_while_it_takes_locks` in `src/vaultspec_rag/tests/test_reset_lock_acquisition.py` creates a historical code generation while the reset waits; with the second listing neutralised it failed with DID NOT RAISE, and restored it passes.

The seven GPU-lane failures were defects in the test, not in the source. The module was marked for the resident-model tier although it spawns its own service, and its setup and assertions were wrong. Both are corrected in the test. Each narrowed guard there is proven against a production mutation, recorded beside the assertion.

### partial-delete-purge-uncovered | low | No test covers deleting some files before a reset rebuild of vault or code

Skipping the reset's point discard goes undetected for vault and code, because the surviving files rewrite their points under the same ids. A file deleted between the previous index and the rebuild would leave stale points that no test checks. `src/vaultspec_rag/tests/integration/test_indexer_integration.py:1023` covers only the case where every vault file is deleted. Recommendation: in a follow-on, add a real-store test that deletes some vault and code files before an explicit rebuild, and assert that their points are gone.
