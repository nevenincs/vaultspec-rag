---
tags:
  - '#exec'
  - '#provider-mcp-enrollment'
date: '2026-07-16'
modified: '2026-07-22'
body_hash: 'sha256:8c72be67a2212a28e81e7150cd7a1d9ae9e313824a45336dc1e69034b027da38'
step_id: 'S66'
related:
  - "[[2026-07-15-provider-mcp-enrollment-plan]]"
---

# Bound real service startup around complete cache preparation and offline readiness

## Scope

- The S65 `live_service` readiness failure.
- Dense, sparse, and enabled reranker cache completeness.
- Bounded cold-cache online repair.
- Cache-only resident-service construction.
- One whole startup deadline with retained stage and process diagnostics.
- Ambient-offline cold-repair isolation and configuration-aware marker proof.
- Pre-readiness Qdrant identity publication and failure cleanup.
- Real service-job terminal polling.
- Repeated failed-selector, adjacent service, S56, and static verification.

## Description

- Reuse the S56 snapshot-completeness and killable acquisition worker for every
  model eagerly loaded by the resident service.
- Spend the existing explicit model-setup budget across cache verification,
  bounded online repair, daemon spawn, and health readiness instead of applying
  an unrelated fixed readiness timeout.
- Explicitly clear inherited Hugging Face offline variables during bounded
  cache preparation, restore them afterward, and set supported offline
  variables only before spawning the test daemon.
- Make production model constructors pass `local_files_only=True` when those
  supported offline variables are enabled; leave normal product construction
  online-capable by default.
- Require the daemon log to prove cache-only dense and sparse construction,
  require the reranker marker only when the effective configuration enables
  it, and contain no configured Hugging Face endpoint.
- Publish the supervised Qdrant identity before model warming and stop and
  clear an active owned supervisor if startup fails or is cancelled before
  readiness.
- Make the adjacent service-jobs poll wait for the submitted job identifier
  under the established 120-second real-job deadline.

## Outcome

- The fixture now verifies or repairs the configured dense, sparse, and enabled
  reranker snapshots before spawn. Warm caches perform no acquisition process;
  incomplete or cold caches retain the existing bounded online-repair path.
- The same explicit 600-second budget bounds model preparation and readiness.
  Timeout reports retain completed stages, elapsed and remaining time, model
  identifiers, process identifier, port, offline environment, and service or
  worker output.
- The test daemon inherits `HF_HUB_OFFLINE=1` and
  `TRANSFORMERS_OFFLINE=1`. `ServiceRegistry` explicitly propagates the
  resulting cache-only mode to `EmbeddingModel` and `CrossEncoder`, while the
  default remains online-capable when neither variable is set.
- The online preparation phase explicitly removes ambient
  `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE`, then restores the caller's
  values. A real cold-cache loopback regression proved that an ambient-offline
  parent still reached the bounded acquisition endpoint.
- The live fixture requires the dense cache-only marker, conditionally requires
  the reranker marker from the same effective enabled configuration, and
  rejects appearances of the configured Hugging Face endpoint. A real
  reranker-disabled configuration regression passed without requiring an
  unconfigured marker.
- A formal independent review found three MEDIUM deadline and cleanup holes:
  the cleanup guard began after post-spawn status work, a fixed health-request
  timeout and uncapped sleep could exceed the shared startup budget, and the
  adjacent job poll used unfiltered independently timed administration calls.
  All three were corrected before commit.
- Cleanup now begins immediately after `_spawn_service` returns. Health probes
  and sleeps are capped by the remaining startup budget and cannot credit a
  ready response received after expiry. The exact job poll sends `job_id`,
  bounds every real administration request by its remaining 120-second budget,
  rejects late terminal responses, and retains the last exact job and envelope.
- A fresh independent re-review confirmed those three findings closed and then
  found three additional MEDIUM edge cases: ambient offline variables could
  disable the alleged online repair phase, offline verification always required
  a reranker marker even when disabled, and a Qdrant child started before model
  warming could escape pre-yield failure cleanup before its PID reached the
  normal heartbeat.
- The repair context now supports explicit variable removal and clears both
  offline switches. Marker verification derives the reranker expectation from
  effective configuration. The daemon publishes Qdrant PID and port
  immediately after supervised readiness and its pre-yield failure or
  cancellation path stops and clears the owned supervisor before releasing the
  machine lock.
- A real startup-expiry regression observed the published Qdrant PID and
  listener while the service was warming, expired a 50-millisecond health
  budget, terminated startup, and proved the service process, Qdrant process,
  service listener, and Qdrant listener were all absent.
- The final review pass found that `_service_env` began its restoration guard
  after environment mutation and setup, so a real context-entry failure could
  leak isolated status, storage, port, and removed offline values. The guard
  now encloses every mutation, mirror, reset, and yield step. A real invalid
  environment-key entry failure proved every inherited value was restored.
- The same review found that POSIX Qdrant runs in a detached session and could
  survive when non-cancellable model warming forced `_terminate_pid` to
  escalate from `SIGTERM` to `SIGKILL` before lifespan cleanup ran.
  `_terminate_pid` now captures a child only when the managed identity matches
  a positive recorded creation-time witness for the exact live service PID,
  configured storage, recorded and live pinned Qdrant versions, ready recorded
  port, and Qdrant process image. It revalidates and reaps that child after
  forced service termination and reaps the POSIX service child record so a
  zombie is not misreported as running.
- The first final review rejected the shared legacy owner helper because it
  deliberately degrades an identity without a creation-time witness to PID-only
  liveness. The forced-stop path now reads the live owner start time directly
  and fails closed unless both recorded and live values are positive and match.
  A real zero-witness WSL regression killed the SIGTERM-resistant service owner
  while proving the Qdrant PID and listener were unchanged until explicit
  test-owned cleanup.
- The first combined rerun recreated the isolated WSL environment, removed its
  pinned Qdrant binary, contended with the simultaneous Windows GPU lifecycle,
  and exposed that real Qdrant startup logs can precede the harness readiness
  line. No test-owned WSL process or listener remained. The pinned 1.18.2 binary
  was restored, the real-process reader was made log-tolerant, and all POSIX
  gates were rerun sequentially.
- Final real WSL execution passed the actual cached-model startup-expiry case,
  the positive witnessed SIGTERM-resistant service-owner case, and the
  zero-witness negative case. The positive cases proved service and Qdrant
  processes and listeners absent; the negative case proved no Qdrant signal or
  listener change before explicit cleanup. Windows retained its kill-on-close
  Job Object behavior and the complete direct lifecycle passed 10 of 10 again.
- The original failed real reindex selector passed repeated remediation
  executions with explicit offline-log verification. Setup fell from the failed
  90-second boundary to observed successful fixture times between 16.37 and
  52.29 seconds.
- The complete jobs registry passed 9 of 9. The complete service-jobs group
  initially exposed a separate five-second test-helper race; after targeting
  the submitted job under the established 120-second job deadline, the focused
  case and all 62 service-jobs cases passed. A real filtered-administration
  50-millisecond deadline regression completed its call in 0.057 seconds.
- The Windows direct service lifecycle passed 10 of 10, including a real unreachable
  health-endpoint 50-millisecond deadline regression whose call completed in
  0.082 seconds and the real startup-expiry cleanup regression. Service
  registry passed 37 of 37, server 120 of 120, and config plus model-setup
  regressions 56 of 56.
- All four S56 intent-ranking assertions passed against the complete
  1,119-document pre-S66 corpus; the real worker fixture completed in
  105.13 seconds inside its 600-second boundary.
- Repository Ruff lint, Ty, strict BasedPyright, every complexity gate,
  affected-file formatting, and `git diff --check` passed. The repository-wide
  format check retained one pre-existing failure in untouched
  `src/vaultspec_rag/cli/_preprocess.py`; S66 did not reformat unrelated code.
- Published `vaultspec-core==0.1.45` reported the vault structurally clean
  across structure, frontmatter, modified stamps, annotations, Markdown, links,
  placeholders, orphans, references, and encoding. Its 25 warnings are existing
  feature-index, research-reference, and legacy ADR-status corpus warnings.

## Notes

- Existing real delayed-504, persistent failure, retained final URL and response,
  and incomplete-sharded-cache regressions remain green.
- A fresh independent re-review inspected the strict creation-witness
  correction, positive and negative real POSIX regressions, preserved Windows
  Job Object path, and all prior S66 findings. It returned PASS with no
  actionable finding.
- No mock, fake, stub, patch, monkeypatch, skip, or xfail was introduced.
- No dependency declaration or lock file changed.
- S66 is corrective evidence only and earns no S67 release-campaign credit.
  It does not authorize a pull request, approval, merge, tag, publication, or
  release.
