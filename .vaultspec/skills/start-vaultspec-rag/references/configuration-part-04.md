# Configuration and environment: evidence group s1-0048

Read this part when working with: [src/vaultspec_rag/config/\_settings.py](../../../../src/vaultspec_rag/config/_settings.py), [src/vaultspec_rag/config/\_types.py](../../../../src/vaultspec_rag/config/_types.py).

This is static evidence. Implementation observations, documentation claims, and test expectations remain distinct; no tests were run. An imported dependency uninspected within this evidence group may be covered in another capability reference. All listed full-file ranges are covered; report-local dependency boundaries are not inventory gaps.

[Configuration and environment](configuration.md) provides module summaries, connections, and reconciled limitations.

## Capability summary

- [src/vaultspec_rag/config/\_settings.py](../../../../src/vaultspec_rag/config/_settings.py) owns RAG defaults, their typed wrapper, resolution and validation. Defaults cover Qdrant/local storage and maintenance, embedding/model and GPU/index budgets, service/jobs, watcher retry/scope, document preprocessing/chunking, vault ranking, and code-result noise controls (lines 85–575). It also declares two intent-weight profiles (lines 577–615).
- The wrapper parses comma-separated code-noise domains against the imported domain set; hidden domains are excluded from the demotion set, so hiding takes precedence (lines 622–652).
- It enforces paired bounds and cross-setting relations in addition to per-key schema checks: retry and queue/segment order, watcher delay/freshness and path limits, document overlap versus the derived chunk length, and the operator binary/digest pair (lines 686–711, 713–844, 847–982, 735–782, 1048–1109). Constructor validation collects distinct refusals and raises one error or a combined report (lines 654–679, 1048–1109).
- It exposes backend selection and URL helpers, hub cache reporting, and policy-specific properties for watcher legacy settings, log level, preprocessing, and derived document chunk size (lines 722–732, 784–797, 847–981, 1111–1211).
- It provides wrapper construction, cached configuration, shipped-default lookup, startup environment diagnostics, hub endpoint publication, model-repository descriptors, and managed status-directory resolution (lines 1377–1652).
- [src/vaultspec_rag/config/\_types.py](../../../../src/vaultspec_rag/config/_types.py) defines the recognized environment-variable vocabulary, the two-state preprocessing and index-profile literals, the binary-pair error and typed binary/model tuples, a shared status-directory default, and Hugging Face offline-mode detection (lines 11–18, 19–295, 298–368).

## Interfaces and data flow

- `VaultSpecConfigWrapper(base, rag_overrides)` keeps only override keys present in `_RAG_DEFAULTS`, then validates at construction. For known RAG keys resolution is CLI override → registered environment value → persisted `local_only` marker when applicable → shipped default. Environment values are parsed as booleans or through a declared setting bound; other values stay strings. Blank values are treated as unset by the registry helper. Unknown attributes delegate to the wrapped base config (lines 654–680, 983–1046, 1337–1375). Exact parsing and registry behavior are delegated to uninspected modules.
- `from_environment(overrides)` obtains the base config through core and wraps it. `get_config()` caches a singleton; passing an overrides mapping builds and stores a fresh wrapper. `rag_default(key)` returns the shipped default directly. `collect_environment_problems(cli_overrides)` builds a temporary wrapper (not the cached singleton), checks core environment and unattended declarations, and returns collected messages (lines 1377–1502).
- `effective_server_mode()` implements `qdrant_server and not local_only`; `effective_qdrant_url` uses configured URL or loopback at the configured port. `qdrant_operator_binary` returns no pair when both settings are absent, refuses exactly one, and otherwise returns the path and declared digest together (lines 722–782, 1111–1127). The exact digest-format check comes from the imported setting schema and was not inspected.
- `preprocess_mode` reads the live kill-switch variable first: a recognized false value returns `off`; otherwise the configured mode is resolved and unknown modes warn and fall back to `default`. The setting is also included in construction-time validation (lines 1080–1094, 1157–1211).
- `publish_model_hub_endpoint()` writes the configured package endpoint into the client endpoint environment variable only when the package-specific endpoint is set (lines 1505–1537). Model helpers resolve a configured revision or a committed revision and mark a repository pinned when a committed manifest exists; configured model lists omit the sparse repository when sparse is disabled (lines 1583–1647).
- The module docstring says CLI, stdio MCP, and HTTP-daemon process kinds share the startup refusal and endpoint-publication contract (lines 1446–1521). Those external call sites are not in the assigned slice and were not verified.

## Boundaries and dependencies

- Direct imports show dependencies on core configuration, environment parsing, and logging; sibling config path, registry, schema, and type modules; plus model-pin and sparse-profile modules (lines 9–45). Runtime code also imports the domain set (lines 629–633), and startup diagnostics lazily imports core checks and the registry package (lines 1481–1488). Their internals were not inspected.
- The wrapper delegates non-RAG attributes to the base config. Its class comment identifies `docs_dir` as the base field the RAG package reads, but package-wide use is outside the assigned files (lines 1331–1375).
- [src/vaultspec_rag/config/\_types.py](../../../../src/vaultspec_rag/config/_types.py) centralizes RAG and selected third-party/process environment names. Its comments describe the intended admission rule for enum members and distinguish configuration from process transport markers; those claims were not checked against other modules (lines 19–31, 250–295).
- The code itself establishes local behavior, but no separate documentation or test files were assigned. No test expectations or pass/fail outcomes are available from this slice.

## Evidence

| Claim                                                                                                      | Project-relative file:line-range                                                                            | Basis               |
| ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------- |
| RAG defaults span storage, model/index, service, watcher, preprocessing, ranking and code-noise settings   | [src/vaultspec_rag/config/\_settings.py:85–575](../../../../src/vaultspec_rag/config/_settings.py#L85)      | implementation      |
| Intent weight profiles and hide-over-demote domain parsing                                                 | [src/vaultspec_rag/config/\_settings.py:577–652](../../../../src/vaultspec_rag/config/_settings.py#L577)    | implementation      |
| CLI/environment/persisted-marker/default resolution and coercion                                           | [src/vaultspec_rag/config/\_settings.py:983–1046](../../../../src/vaultspec_rag/config/_settings.py#L983)   | implementation      |
| Construction validation sweeps bounded and boolean settings, checks relationships, and aggregates refusals | [src/vaultspec_rag/config/\_settings.py:1048–1109](../../../../src/vaultspec_rag/config/_settings.py#L1048) | implementation      |
| Effective backend mode gives `local_only` priority                                                         | [src/vaultspec_rag/config/\_settings.py:1111–1127](../../../../src/vaultspec_rag/config/_settings.py#L1111) | implementation      |
| Preprocessing kill switch and fallback behavior                                                            | [src/vaultspec_rag/config/\_settings.py:1157–1211](../../../../src/vaultspec_rag/config/_settings.py#L1157) | implementation      |
| Wrapper delegates unknown attributes to base; config factory/cache and diagnostics APIs                    | [src/vaultspec_rag/config/\_settings.py:1337–1502](../../../../src/vaultspec_rag/config/_settings.py#L1337) | implementation      |
| Process kinds call shared startup checks and endpoint publication                                          | [src/vaultspec_rag/config/\_settings.py:1446–1521](../../../../src/vaultspec_rag/config/_settings.py#L1446) | documentation claim |
| Model revision/pinning descriptors and enabled-model selection                                             | [src/vaultspec_rag/config/\_settings.py:1583–1647](../../../../src/vaultspec_rag/config/_settings.py#L1583) | implementation      |
| Environment vocabulary includes product, child-process, and selected third-party names                     | [src/vaultspec_rag/config/\_types.py:19–295](../../../../src/vaultspec_rag/config/_types.py#L19)            | implementation      |
| Binary/model value objects, status default, and offline-mode helper                                        | [src/vaultspec_rag/config/\_types.py:298–368](../../../../src/vaultspec_rag/config/_types.py#L298)          | implementation      |

## Uncertainty and follow-up

- No blocker to describing the assigned modules.
- For a verified external caller map, inspect call sites of `get_config`, `collect_environment_problems`, `publish_model_hub_endpoint`, `effective_server_mode`, and the model helper functions under `src/vaultspec_rag/`; the process-kind caller statement here is only a docstring claim.
- To explain delegated validation and persisted/runtime behavior, inspect [src/vaultspec_rag/config/\_schema.py](../../../../src/vaultspec_rag/config/_schema.py) (`checked_setting`, bounds, and `ENV_OVERRIDE_MAP`), `_registry.py` (`entry` and `PACKAGE`), `_paths.py` (`read_persisted_local_only`), and the imported core configuration/environment/logging symbols. Those internals were intentionally not read for this assignment.
