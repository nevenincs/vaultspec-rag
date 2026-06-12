---
tags:
  - '#exec'
  - '#cli-service-operability-hardening'
date: '2026-06-12'
step_id: W04.S01
related:
  - '[[2026-06-11-cli-service-operability-hardening-epic-plan]]'
  - '[[2026-06-11-server-bound-search-production-readiness-adr]]'
---

# Wave 04 Slice 01 - Timeout Diagnostics And Coarse Timing

## Persona

Power user running several agent searches while the resident service may be busy or slow.

## Hardening Target

The prior timeout surface only said that the HTTP search timed out after the client
budget. It did not tell the operator whether the service was ready, whether same-project
searches were serialized, whether jobs were active, or what command should be run next.

## Research

Service-backed RAG discovery was run against the resident service:

- `uv run vaultspec-rag search "timeout backpressure queue service search diagnostics default timeout CLI server jobs running" --type code --json --max-results 8 --port 8766 --timeout 180`

The relevant implementation locations were:

- `src/vaultspec_rag/cli/_http_search.py`
- `src/vaultspec_rag/cli/_search.py`
- `src/vaultspec_rag/cli/_render.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

## Implementation

- Added coarse server-route timing to successful `/search` responses:
  - `status_seconds`
  - `search_seconds`
  - `serialization_seconds`
  - `server_total_seconds`
  - `queue_wait_seconds: null` because this route cannot yet measure true queue wait.
- Added timeout diagnostics in the CLI HTTP search path:
  - probes `/health`
  - probes `/jobs?limit=5&phase=running`
  - reports backend concurrency contract
  - reports whether active jobs suggest an indexing conflict
  - suggests valid next commands.
- Updated shared service-error rendering so JSON and human output preserve:
  - `backend_capabilities`
  - `diagnostics`
  - `port`
  - `timeout_seconds`
  - `remediation`.

## Automated Evidence

- `uv run ruff check src/vaultspec_rag/cli/_http_search.py src/vaultspec_rag/cli/_render.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`

Result: 4 passed.

## Manual Persona Test

The resident service was restarted to exercise the current implementation:

- stopped PID `51476`
- started PID `29376`
- port `8766`

Commands:

- `uv run vaultspec-rag search "timeout diagnostics service status jobs" --type code --json --max-results 2 --port 8766 --timeout 120`
- `uv run vaultspec-rag search "intentional short timeout diagnostics" --type code --json --max-results 2 --port 8766 --timeout 0.000001`
- `uv run vaultspec-rag search "intentional short timeout diagnostics" --type code --max-results 2 --port 8766 --timeout 0.000001`
- `uv run vaultspec-rag server status --json`
- `uv run vaultspec-rag server jobs --running --json --port 8766`

Observed:

- Successful search returned timing metadata. In the manual run:
  - `status_seconds`: about 1.59s
  - `search_seconds`: about 6.87s
  - `server_total_seconds`: about 8.45s
- Short-timeout JSON failure returned:
  - `error: http_search_timeout`
  - `status: ready`
  - `running_jobs: 0`
  - `same_project_search_strategy: serialized`
  - valid remediation commands.
- Human timeout output showed:
  - the timeout reason
  - service status
  - running job count
  - backend contract table
  - next actions.

## Manual Finding

The first remediation attempt incorrectly suggested:

- `vaultspec-rag server status --port 8766`

That command is invalid because `server status` does not currently accept `--port`. The
remediation was corrected to:

- `vaultspec-rag server status`

and the integration test now asserts that exact command appears in timeout diagnostics.

## Outcome

This slice makes timeout failures actionable without adding more competing status
interfaces. It does not yet solve performance or true queue attribution. It exposes the
current server-bound cost clearly enough for the next performance and backpressure slice.

## Post-Review Corrections

Code review found that timeout diagnostic probes could throw while handling the original
timeout. The probe path now catches health/jobs probe failures and returns
`available: false` inside the structured `http_search_timeout` payload. Review also found
that `active_indexing_conflict` overstated confidence when the jobs probe failed. The
diagnostic now uses `summary.running` when available and reports `null` when conflict
state cannot be established.

## Deferred

- Search while indexing still needs a controlled manual reproduction.
- `server status --port` was later implemented in the status convergence follow-up.

## Follow-Up: Avoid Redundant Cold Status Work

Manual measurement after a daemon restart showed the first service-backed search paying a
visible pre-search status cost:

- `status_seconds`: about 1.56s
- `search_seconds`: about 6.82s
- `server_total_seconds`: about 8.38s

The route previously called `get_status(root)` before search. On a cold project, that can
open/count the local Qdrant store before the actual search loads the same project slot.
The route now performs the search first and gathers status afterward, so index-state
metadata can reuse the loaded project slot.

Verification:

- `uv run ruff check src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run ty check src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start --port 8766`
- `uv run vaultspec-rag search "search route timing embedding qdrant rerank phase attribution" --type code --json --max-results 3 --port 8766 --timeout 180`
- repeated the same search once warm.

Observed against current resident service PID `50236` on port `8766`:

- Cold search after the change reported `status_seconds` about 0.0004s and
  `server_total_seconds` about 7.62s.
- Warm repeated search reported `server_total_seconds` about 0.86s.
- Remaining cold latency is inside `search_seconds`, so true embedding/Qdrant/rerank
  attribution still requires a service-domain diagnostic search API rather than wrapper
  timing around the public list-returning search functions.

## Follow-Up: Search Phase Timing

Added service-domain timed search variants for the HTTP route:

- `search_vault_timed`,
- `search_codebase_timed`,
- `VaultSearcher.search_vault_timed`,
- `VaultSearcher.search_codebase_timed`.

The `/search` timing payload now reports:

- `model_load_seconds`,
- `project_lease_seconds`,
- `embedding_seconds`,
- `qdrant_seconds`,
- `rerank_seconds`,
- `postprocess_seconds`,
- `serialization_seconds`,
- `server_total_seconds`,
- `phases` with detailed sub-phases such as `glob_filter_seconds`,
  `result_mapping_seconds`, `prefer_seconds`, `dedup_seconds`, and
  `graph_rerank_seconds` where applicable.

Verification:

- `uv run ruff check src/vaultspec_rag/search/_searcher.py src/vaultspec_rag/api.py src/vaultspec_rag/__init__.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run ty check src/vaultspec_rag/search/_searcher.py src/vaultspec_rag/api.py src/vaultspec_rag/__init__.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start --port 8766`
- `uv run vaultspec-rag search "phase timing embedding qdrant rerank postprocess" --type code --json --max-results 2 --port 8766 --timeout 180`
- `uv run vaultspec-rag server status --json --port 8766`

Observed against current resident service PID `58528` on port `8766`:

- cold JSON search included all flat timing fields and the detailed `phases` map,
- `embedding_seconds` was about 0.55s,
- `qdrant_seconds` was about 0.40s,
- `rerank_seconds` was about 0.095s,
- `postprocess_seconds` was about 0.095s,
- the remaining cold cost was attributable to setup fields, especially project/model
  setup outside the core query phases.

## Follow-Up: GPU Queue Wait Timing

Added true GPU-lock wait timing inside the service-domain searcher:

- Query embedding and CrossEncoder reranking now acquire the shared GPU lock through a
  timed context.
- `phases.gpu_queue_wait_seconds` and `phases.queue_wait_seconds` accumulate time spent
  waiting to enter those GPU sections.
- The top-level `/search` timing payload now reports numeric `queue_wait_seconds` instead
  of `null`.

Verification:

- `uv run ruff check src/vaultspec_rag/search/_searcher.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run ty check src/vaultspec_rag/search/_searcher.py src/vaultspec_rag/server/_routes.py src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run pytest src/vaultspec_rag/tests/integration/test_service_search_diagnostics.py`
- `uv run --no-sync python tools/complexity_gate.py`
- `uv run vaultspec-rag server stop`
- `uv run vaultspec-rag server start --port 8766`
- `uv run vaultspec-rag search "queue wait gpu lock timing" --type code --json --max-results 2 --port 8766 --timeout 180`

Observed against resident service PID `18512` on port `8766`:

- `queue_wait_seconds` was numeric rather than `null`.
- `phases.gpu_queue_wait_seconds` matched the top-level queue wait value.
- The manual run showed near-zero queue wait (`~0.000002s`) and cold cost remained under
  `project_lease_seconds` (`~6.53s`), confirming the remaining startup slowdown is setup
  latency, not observed GPU-lock contention.
